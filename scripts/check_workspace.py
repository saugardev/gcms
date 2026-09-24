"""Check a running Rust API against the exact saved report (no analysis rerun)."""

import argparse
import hashlib
import json
import os
import statistics
import struct
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--acquisition", type=Path, help="Check imported raw scans against data.ms")
    args = parser.parse_args()
    document = json.loads(args.report.read_text())
    report = document.get("analysis", document)

    def request(path, status=200, method="GET"):
        try:
            response = urlopen(Request(args.url + path, method=method, headers={"Authorization": "Session " + os.environ.get("GCMS_SESSION_TOKEN", "")}), timeout=10)
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
    for query in ("", "index=-1", "index=1.5", "time_seconds=NaN", "time_seconds=inf", "time_seconds=-1", "index=0&time_seconds=0"):
        request(f"{path}/scans?{query}", status=400)
    request(f"{path}/scans?index=2147483647", status=404)
    for query in ("", "mz=NaN", "mz=-1", "mz=4000", "mz=83&tolerance=inf", "mz=83&tolerance=-0.1", "mz=83&tolerance=5.1"):
        request(f"{path}/ions?{query}", status=400)
    if args.acquisition:
        raw = args.acquisition.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == report["provenance"]["input_data_ms_sha256"]
        trace = saved["raw_chromatogram"]
        count = struct.unpack_from("<H", raw, 0x142)[0]
        position = struct.unpack_from(">H", raw, 0x10A)[0] * 2 - 2
        assert len(trace["time_seconds"]) == len(trace["raw_tic"]) == count
        # Verify every native scan total; inspect exact spectra across the whole acquisition.
        sampled = {0, 1, count-1, count-2, *(i*count//10 for i in range(1, 10))}
        extracted = {(83, 0.5): [], (83.05, 0): [], (153.1, 0.1): [], (1000, 0.5): []}
        for index in range(count):
            time_seconds = struct.unpack_from(">I", raw, position+2)[0] / 1000
            pairs = struct.unpack_from(">H", raw, position+12)[0]
            ions = {}
            for mz, encoded in struct.iter_unpack(">HH", raw[position+18:position+18+pairs*4]):
                mass = mz / 20
                ions[mass] = ions.get(mass, 0) + (encoded & 0x3FFF) * 8**(encoded >> 14)
            assert trace["time_seconds"][index] == time_seconds
            assert trace["raw_tic"][index] == sum(ions.values())
            for (mz, tolerance), expected in extracted.items():
                expected.append(sum(value for mass, value in ions.items() if abs(mass-mz) <= tolerance+1e-9))
            if index in sampled:
                scan = request(f"{path}/scans?index={index}")
                assert scan == {"scan_index": index, "time_seconds": time_seconds,
                                "spectrum": {"mz": sorted(ions), "intensity": [ions[m] for m in sorted(ions)]}}
                assert request(f"{path}/scans?time_seconds={time_seconds}") == scan
                if index+1<count:
                    near = time_seconds+(trace["time_seconds"][index+1]-time_seconds)*0.49
                    assert request(f"{path}/scans?time_seconds={near}") == scan
            position += 28+pairs*4
        assert request(f"{path}/scans?time_seconds=0")["scan_index"] == 0
        assert request(f"{path}/scans?time_seconds=999999")["scan_index"] == count-1
        for (mz, tolerance), expected in extracted.items():
            result = request(f"{path}/ions?mz={mz}&tolerance={tolerance}")
            assert result == {"mz": mz, "tolerance": tolerance, "intensity": expected}
        print(f"Verified all {count} raw scan timestamps/totals and {len(sampled)} exact native spectra.")
        print("Verified four full ion traces, including exact masses, tolerance boundaries and absent ions.")
    request("/v1/analyses/invalid", status=400)
    request("/v1/analyses/" + "0" * 64, status=404)
    request(f"{path}/components/invalid", status=400)
    request(f"{path}/components/component-9999", status=404)
    request("/v1/analyses", status=405, method="POST")
    request("/v1/analyze", status=404, method="POST")
    routes = [path, f"{path}/components/{report['components'][0]['component_id']}", f"{path}/spectra?components={ids.split(',')[0]},{ids.split(',')[-1]}"]
    if args.acquisition:
        routes.append(f"{path}/scans?time_seconds=2820")
        routes.append(f"{path}/ions?mz=83&tolerance=0.5")
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
