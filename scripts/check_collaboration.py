"""Exercise Rust sessions, shared decisions and WebSockets in a disposable DB schema.

Run after building gcms-api (debug), with DATABASE_URL set:
  uv run --with websockets python scripts/check_collaboration.py
Existing analyses/users are never changed. Requires psql and schema-create rights.
"""

import asyncio
import hashlib
import json
import os
import socket
import subprocess
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

ROOT = Path(__file__).resolve().parents[1]


def sql(statement, database):
    uri = urlsplit(database)
    environment = {
        **os.environ,
        "PGHOST": uri.hostname or "127.0.0.1",
        "PGPORT": str(uri.port or 5432),
        "PGDATABASE": uri.path.lstrip("/"),
        "PGUSER": unquote(uri.username or ""),
        "PGPASSWORD": unquote(uri.password or ""),
        "PGOPTIONS": dict(parse_qsl(uri.query)).get("options", ""),
    }
    result = subprocess.run(
        ["psql", "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1", "-c", statement],
        env=environment,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


async def run(database, origin, request):
    aid = "a" * 64
    base = f"/v1/analyses/{aid}"
    component = base + "/components/component-0001"
    endpoint = component + "/candidates/"
    fixture = {
        "component": {
            "component_id": "component-0001",
            "status": "ambiguous",
            "candidates": [
                {"group_id": "candidate-a", "identities": [{"name": "Alpha"}]},
                {"group_id": "candidate-b", "identities": [{"name": "Beta"}]},
            ],
        },
        "review": None,
    }
    sql(
        f"INSERT INTO analyses(id,sample_name,metadata,chromatogram,peaks) VALUES ('{aid}','Auth test','{{}}','{{}}','[]'); INSERT INTO components(analysis_id,id,data) VALUES ('{aid}','component-0001','{json.dumps(fixture)}');",
        database,
    )
    for path in [
        "/v1/analyses",
        base,
        component,
        base + "/spectra",
        base + "/scans",
        base + "/ions",
        base + "/reviews",
    ]:
        request(path, status=401)
    users = []
    for name in ["Ana", "Ben"]:
        result = request(
            "/v1/auth/register",
            "POST",
            {"name": name, "email": f"{name}@example.test", "password": "test-password-123"},
            status=201,
        )
        users.append(result)
    ana, ben = [user["session_token"] for user in users]
    request(
        "/v1/auth/register",
        "POST",
        {"name": "Duplicate", "email": " ANA@example.test ", "password": "test-password-123"},
        status=409,
    )
    request(
        "/v1/auth/register", "POST", {"name": "X", "email": "bad", "password": "short"}, status=400
    )
    for email in ["ana@example.test", "unknown@example.test"]:
        request(
            "/v1/auth/login", "POST", {"email": email, "password": "incorrect-password"}, status=401
        )
    login = request(
        "/v1/auth/login", "POST", {"email": " ANA@example.test ", "password": "test-password-123"}
    )
    assert login["session_token"] != ana
    assert request("/v1/me", token=ana)["user"]["name"] == "Ana"
    assert sql("SELECT bool_and(password_hash LIKE '$argon2id$%') FROM app_users", database) == "t"
    assert (
        sql("SELECT count(*) FROM app_sessions WHERE octet_length(token_hash)=32", database) == "3"
    )
    for index in range(11):
        request(
            "/v1/auth/login",
            "POST",
            {"email": "limited@example.test", "password": "incorrect-password"},
            status=401 if index < 10 else 429,
        )
    request(
        endpoint + "missing/decision",
        "PUT",
        {"decision": "accepted", "expected_version": 0},
        ana,
        404,
    )
    request(
        endpoint + "candidate-a/decision",
        "PUT",
        {"decision": "wrong", "expected_version": 0},
        ana,
        400,
    )
    request(
        endpoint + "candidate-a/decision",
        "PUT",
        {"decision": "accepted", "expected_version": 0},
        status=401,
    )
    ws_url = origin.replace("http:", "ws:") + base + "/events"
    for cookie, ws_origin, expected in [
        (ana, "https://evil.example", 403),
        ("invalid", "http://127.0.0.1:3000", 401),
    ]:
        try:
            async with connect(
                ws_url, origin=ws_origin, additional_headers={"Cookie": f"mafer_session={cookie}"}
            ):
                raise AssertionError("Unexpected WebSocket access")
        except InvalidStatus as error:
            assert error.response.status_code == expected
    async with (
        connect(
            ws_url,
            origin="http://127.0.0.1:3000",
            additional_headers={"Cookie": f"mafer_session={ana}"},
        ) as ws_a,
        connect(
            ws_url,
            origin="http://127.0.0.1:3000",
            additional_headers={"Cookie": f"mafer_session={ben}"},
        ) as ws_b,
    ):
        assert json.loads(await ws_a.recv())["type"] == "ready"
        assert json.loads(await ws_b.recv())["type"] == "ready"
        saved = request(
            endpoint + "candidate-a/decision",
            "PUT",
            {"decision": "accepted", "expected_version": 0},
            ana,
        )
        event_a = json.loads(await asyncio.wait_for(ws_a.recv(), 3))
        event_b = json.loads(await asyncio.wait_for(ws_b.recv(), 3))
        assert event_a == event_b == saved["event"]
        assert event_b["actor"]["name"] == "Ana"
        assert request(base + "/reviews", token=ben)["reviews"] == [saved["review"]]
        stale = request(
            endpoint + "candidate-b/decision",
            "PUT",
            {"decision": "accepted", "expected_version": 0},
            ben,
            409,
        )
        assert stale["review"] == saved["review"]
        saved = request(
            endpoint + "candidate-b/decision",
            "PUT",
            {"decision": "accepted", "expected_version": 1},
            ben,
        )
        assert [d["decision"] for d in saved["review"]["decisions"]] == ["unreviewed", "accepted"]
        await ws_a.recv()
        await ws_b.recv()
        unchanged = request(
            endpoint + "candidate-b/decision",
            "PUT",
            {"decision": "accepted", "expected_version": 2},
            ben,
        )
        assert unchanged["event"] is None and unchanged["review"]["version"] == 2

        def compete(group):
            return request(
                endpoint + group + "/decision",
                "PUT",
                {"decision": "rejected", "expected_version": 2},
                ana,
                None,
            )

        with ThreadPoolExecutor(2) as executor:
            results = list(executor.map(compete, ["candidate-a", "candidate-b"]))
        assert sorted(status for status, _ in results) == [200, 409]
        await ws_a.recv()
        await ws_b.recv()
        review = request(base + "/reviews", token=ben)["reviews"][0]
        assert review["version"] == 3
        saved = request(
            endpoint + "candidate-b/decision",
            "PUT",
            {"decision": "unreviewed", "expected_version": 3},
            ben,
        )
        if saved["event"]:
            await ws_a.recv()
            await ws_b.recv()
        assert request(component, token=ana) == fixture, "Computed analysis was modified"
        assert (
            int(sql("SELECT count(*) FROM review_events", database)) == saved["review"]["version"]
        )
        assert (
            sql("SELECT count(*) FROM candidate_decisions WHERE decision='accepted'", database)
            == "0"
        )
        request("/v1/auth/logout", "POST", token=ben, status=204)
        request("/v1/me", token=ben, status=401)
        try:
            await asyncio.wait_for(ws_b.recv(), 3)
            raise AssertionError("Revoked session still receives events")
        except ConnectionClosed as error:
            assert error.rcvd.code == 1008
    # Reconnection receives ready, followed by a snapshot containing all committed changes.
    async with connect(
        ws_url,
        origin="http://127.0.0.1:3000",
        additional_headers={"Cookie": f"mafer_session={ana}"},
    ) as ws:
        assert json.loads(await ws.recv())["type"] == "ready"
        assert (
            request(base + "/reviews", token=ana)["reviews"][0]["version"]
            == saved["review"]["version"]
        )
        hashed = hashlib.sha256(ana.encode()).hexdigest()
        sql(
            f"UPDATE app_sessions SET expires_at=now()-interval '1 second' WHERE token_hash=decode('{hashed}','hex')",
            database,
        )
        request("/v1/me", token=ana, status=401)
        try:
            await asyncio.wait_for(ws.recv(), 17)
            raise AssertionError("Expired WebSocket did not close")
        except ConnectionClosed as error:
            assert error.rcvd.code == 1008
    print(
        "PASS: sessions, expiry/revocation, throttling, shared decisions, conflicts, audit history, immutable analysis, two WebSocket clients and reconnect snapshots"
    )


def main():
    database = os.environ["DATABASE_URL"]
    schema = "test_collaboration_" + uuid.uuid4().hex
    sql(f'CREATE SCHEMA "{schema}"', database)
    parts = urlsplit(database)
    scoped = urlunsplit(
        parts._replace(
            query=urlencode([*parse_qsl(parts.query), ("options", f"-csearch_path={schema}")])
        )
    )
    binary = ROOT / "services/rust/target/debug/gcms-api"
    process = None
    try:
        with socket.socket() as port:
            port.bind(("127.0.0.1", 0))
            address = f"127.0.0.1:{port.getsockname()[1]}"
        origin = "http://" + address
        env = {
            **os.environ,
            "DATABASE_URL": scoped,
            "GCMS_BIND": address,
            "APP_ORIGIN": "http://127.0.0.1:3000",
        }
        subprocess.run([binary, "migrate"], env=env, check=True, capture_output=True)
        with tempfile.TemporaryFile() as logs:
            process = subprocess.Popen([binary, "serve"], env=env, stdout=logs, stderr=logs)

            def request(path, method="GET", body=None, token=None, status=200):
                headers = {"Content-Type": "application/json"}
                if token:
                    headers["Authorization"] = "Session " + token
                try:
                    response = urlopen(
                        Request(
                            origin + path,
                            data=json.dumps(body).encode() if body is not None else None,
                            headers=headers,
                            method=method,
                        ),
                        timeout=15,
                    )
                except HTTPError as error:
                    response = error
                with response:
                    result = response.read()
                    result = json.loads(result) if result else None
                    if status is None:
                        return response.status, result
                    assert response.status == status, (path, response.status, status, result)
                    return result

            for _ in range(100):
                try:
                    request("/health")
                    break
                except URLError:
                    time.sleep(0.05)
            else:
                raise AssertionError("API did not start")
            asyncio.run(run(scoped, origin, request))
    finally:
        if process:
            process.terminate()
            process.wait(timeout=5)
        sql(f'DROP SCHEMA "{schema}" CASCADE', database)


if __name__ == "__main__":
    main()
