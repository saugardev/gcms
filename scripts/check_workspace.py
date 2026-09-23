"""Check a running Rust API against the exact saved report (no analysis rerun)."""

import argparse
import json
import statistics
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    document = json.loads(args.report.read_text())
    report = document.get("analysis", document)

    def request(path, status=200, method="GET"):
        try:
            response = urlopen(Request(args.url + path, method=method), timeout=10)
        except HTTPError as error:
            response = error
        with response:
            assert response.status == status, (path, response.status, status)
            assert "db_api;dur=" in response.headers["Server-Timing"]
            assert response.headers["Cache-Control"] == "no-store"
            body = response.read()
            return json.loads(body) if status == 200 else None

    assert request("/health")["storage"] == "postgresql"
    items = request("/v1/analyses")["analyses"]
    matches = [item for item in items if item["sample_name"] == report["sample_name"]]
    assert matches, "Import the saved report first"
    saved = None
    for item in matches:
        candidate = request(f"/v1/analyses/{item['id']}")
        if candidate["metadata"]["provenance"] == report["provenance"]:
            saved = candidate
            break
    assert saved is not None, "No matching saved provenance"
    path = f"/v1/analyses/{saved['id']}"
    assert saved["chromatogram"] == report["chromatogram"]
    assert len(saved["peaks"]) == len(report["components"])
    assert [p["apex_seconds"] for p in saved["peaks"]] == sorted(
        c["apex_seconds"] for c in report["components"]
    )
    # Read every component: verifies storage boundaries, candidate spectra and review traces.
    for component in report["components"]:
        result = request(f"{path}/components/{component['component_id']}")
        assert result["component"] == component
        assert result["review"] == document.get("annotations", {}).get(component["component_id"])
    ids = ",".join(c["component_id"] for c in reversed(report["components"]))
    compared = request(f"{path}/spectra?components={ids}")["spectra"]
    expected = sorted(report["components"], key=lambda c: (c["apex_seconds"], c["component_id"]))
    assert compared == [{k: c[k] for k in ("component_id", "apex_seconds", "spectrum")} for c in expected]
    request(f"{path}/spectra", status=400)
    request(f"{path}/spectra?components=invalid", status=400)
    request(f"{path}/spectra?components=component-9999", status=404)
    request("/v1/analyses/invalid", status=400)
    request("/v1/analyses/" + "0" * 64, status=404)
    request(f"{path}/components/invalid", status=400)
    request(f"{path}/components/component-9999", status=404)
    request("/v1/analyses", status=405, method="POST")
    request("/v1/analyze", status=404, method="POST")
    routes = [path, f"{path}/components/{report['components'][0]['component_id']}", f"{path}/spectra?components={ids.split(',')[0]},{ids.split(',')[-1]}"]
    for route in routes:
        times = []
        for _ in range(10):
            start = time.perf_counter()
            request(route)
            times.append((time.perf_counter() - start) * 1000)
        print(f"{route}: median {statistics.median(times):.1f} ms (10 local HTTP reads)")
    print(f"Verified {len(saved['peaks'])} components, spectra, candidates and stored traces.")


if __name__ == "__main__":
    main()
