"""Portable numerical fixtures and repeatable timings for both numerical engines."""

import hashlib
import json
import os
import platform
import resource
import shutil
import subprocess
import sys
from pathlib import Path
from time import perf_counter

import numpy as np

from .io import Run, read_library, read_run
from .models import Parameters
from .pipeline import analyze

ARRAY_NAMES = (
    "time_seconds",
    "mz",
    "intensity",
    "corrected",
    "baseline_tic",
    "noise",
    "reference_intensity",
    "reference_mass_fraction",
    "component_spectra",
    "scores",
    "component_apex_scan",
    "component_bounds_scan",
    "component_area",
)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def load_bundle(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    if manifest["bundle_version"] != "1.0":
        raise ValueError("Unsupported benchmark bundle version")
    arrays = [np.load(folder / f"{name}.npy", allow_pickle=False) for name in ARRAY_NAMES[:3]]
    run = Run(
        *arrays, manifest["sample_name"], manifest["input_data_ms_sha256"], manifest["metadata"]
    )
    run.validate()
    library = read_library(folder / "library.msp")
    if library.sha256 != manifest["library_sha256"]:
        raise ValueError("Bundle library hash mismatch")
    for name in ARRAY_NAMES[:3]:
        if (
            hashlib.sha256((folder / f"{name}.npy").read_bytes()).hexdigest()
            != manifest["arrays"][name]["sha256"]
        ):
            raise ValueError(f"Bundle input hash mismatch: {name}")
    return run, library, Parameters.model_validate(manifest["parameters"])


def export_bundle(run, library, library_path, params, folder, engine="python"):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    arrays = {}
    report = analyze(run, library, params, arrays=arrays, engine=engine)
    manifest = {
        "bundle_version": "1.0",
        "algorithm_version": report.algorithm_version,
        "sample_name": run.name,
        "metadata": run.metadata,
        "input_data_ms_sha256": run.source_sha256,
        "library_sha256": library.sha256,
        "parameters": params.model_dump(),
        "arrays": {},
        "float_comparison": {"rtol": 1e-6, "atol": 1e-8},
    }
    for name in ARRAY_NAMES:
        array = np.ascontiguousarray(arrays[name], dtype="<i8" if "_scan" in name else "<f8")
        path = folder / f"{name}.npy"
        np.save(path, array, allow_pickle=False)
        manifest["arrays"][name] = {
            "shape": list(array.shape),
            "dtype": array.dtype.str,
            "order": "C",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    shutil.copyfile(library_path, folder / "library.msp")
    write_json(folder / "report.json", report.model_dump(mode="json"))
    write_json(folder / "manifest.json", manifest)
    return manifest


def compare_bundles(expected_folder, actual_folder):
    expected_folder, actual_folder = Path(expected_folder), Path(actual_folder)
    expected = json.loads((expected_folder / "manifest.json").read_text())
    actual = json.loads((actual_folder / "manifest.json").read_text())
    differences = []
    for key in (
        "bundle_version",
        "algorithm_version",
        "parameters",
        "input_data_ms_sha256",
        "library_sha256",
    ):
        if expected[key] != actual[key]:
            differences.append(f"manifest.{key} differs")
    for folder, manifest in ((expected_folder, expected), (actual_folder, actual)):
        if (
            hashlib.sha256((folder / "library.msp").read_bytes()).hexdigest()
            != manifest["library_sha256"]
        ):
            differences.append(f"{folder.name}/library.msp does not match its manifest hash")
    for name in ARRAY_NAMES:
        a = np.load(expected_folder / f"{name}.npy", allow_pickle=False)
        b = np.load(actual_folder / f"{name}.npy", allow_pickle=False)
        for folder, manifest, array in ((expected_folder, expected, a), (actual_folder, actual, b)):
            path = folder / f"{name}.npy"
            if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["arrays"][name]["sha256"]:
                differences.append(f"{folder.name}/{name} does not match its manifest hash")
            spec = manifest["arrays"][name]
            if (
                list(array.shape) != spec["shape"]
                or array.dtype.str != spec["dtype"]
                or spec["order"] != "C"
                or not array.flags.c_contiguous
            ):
                differences.append(f"{folder.name}/{name} does not match its manifest layout")
        if a.shape != b.shape or a.dtype != b.dtype:
            differences.append(f"{name}: shape or dtype differs")
        elif not (
            np.array_equal(a, b) if a.dtype.kind == "i" else np.allclose(a, b, rtol=1e-6, atol=1e-8)
        ):
            differences.append(f"{name}: values differ beyond tolerance")
    a = json.loads((expected_folder / "report.json").read_text())
    b = json.loads((actual_folder / "report.json").read_text())
    a["provenance"].pop("software", None)
    b["provenance"].pop("software", None)
    _compare_json(a, b, "report", differences)
    return {"equivalent": not differences, "differences": differences}


def _compare_json(a, b, path, differences):
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            differences.append(f"{path}: keys differ")
        for key in a.keys() & b.keys():
            _compare_json(a[key], b[key], f"{path}.{key}", differences)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            differences.append(f"{path}: lengths differ")
        else:
            for i, (left, right) in enumerate(zip(a, b)):
                _compare_json(left, right, f"{path}[{i}]", differences)
    elif isinstance(a, float) and isinstance(b, (float, int)):
        if not np.isclose(a, b, rtol=1e-6, atol=1e-8):
            differences.append(f"{path}: numeric value differs")
    elif a != b:
        differences.append(f"{path}: value differs")


def compare_reviews(expected_path, actual_path):
    from .models import ReviewReport

    reports = [
        ReviewReport.model_validate_json(Path(path).read_text()).model_dump(mode="json")
        for path in (expected_path, actual_path)
    ]
    for report in reports:
        report["analysis"]["provenance"].pop("software", None)
    differences = []
    _compare_json(*reports, "review", differences)
    return {"equivalent": not differences, "differences": differences}


def run_once(sample, library_path, bundle=None, engine="python", workflow="analysis"):
    timings = {}
    t = perf_counter()
    if bundle:
        run, library, params = load_bundle(bundle)
    else:
        run, library, params = read_run(sample), read_library(library_path), Parameters()
    timings["input_seconds"] = perf_counter() - t
    t = perf_counter()
    from .review import build_review

    process = build_review if workflow == "review" else analyze
    report = process(run, library, params, timings=timings, engine=engine)
    timings["analysis_seconds"] = perf_counter() - t
    t = perf_counter()
    encoded = report.model_dump_json().encode()
    timings["json_seconds"] = perf_counter() - t
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    base = report.analysis if workflow == "review" else report
    return {
        "timings": timings,
        "peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "report_sha256": hashlib.sha256(encoded).hexdigest(),
        "component_count": len(base.components),
        "provenance": base.provenance,
    }


def benchmark(sample, library_path, repeats=5, bundle=None, engine="python", workflow="analysis"):
    # Each end-to-end measurement uses a fresh process so ru_maxrss belongs to
    # that run. OS disk caches are not flushed; this is not a cold-disk benchmark.
    cold = []
    for _ in range(repeats):
        command = [
            sys.executable,
            "-m",
            "gcms.cli",
            "_bench-worker",
            "--sample",
            str(sample),
            "--library",
            str(library_path),
            "--engine",
            engine,
            "--workflow",
            workflow,
        ]
        if bundle:
            command.extend(["--bundle", str(bundle)])
        t = perf_counter()
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        item = json.loads(result.stdout)
        item["process_wall_seconds"] = perf_counter() - t
        cold.append(item)
    run, library, params = (
        load_bundle(bundle)
        if bundle
        else (read_run(sample), read_library(library_path), Parameters())
    )
    from .review import build_review

    process = build_review if workflow == "review" else analyze
    process(run, library, params, engine=engine)  # One unmeasured warm-up, input already decoded.
    warm = []
    for _ in range(repeats):
        timing = {}
        t = perf_counter()
        process(run, library, params, timings=timing, engine=engine)
        timing["analysis_wall_seconds"] = perf_counter() - t
        warm.append(timing)

    def stats(values):
        return {"median": float(np.median(values)), "min": min(values), "max": max(values)}

    return {
        "benchmark_version": "1.0",
        "engine": engine,
        "workflow": workflow,
        "shared_python_work": "input loading/validation, filter coefficients, report construction and JSON; "
        "review also shares profile scheduling, stability classification and plot-trace preparation",
        "input_mode": "canonical_bundle" if bundle else "raw_data_ms",
        "repeats": repeats,
        "warmups": 1,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "logical_cpus": os.cpu_count(),
            "numpy_build": np.show_config(mode="dicts"),
            "thread_environment": {
                k: os.environ.get(k)
                for k in (
                    "OPENBLAS_NUM_THREADS",
                    "OMP_NUM_THREADS",
                    "MKL_NUM_THREADS",
                    "VECLIB_MAXIMUM_THREADS",
                )
            },
        },
        "parameters": params.model_dump(),
        "provenance": cold[0]["provenance"],
        "fresh_process_wall_seconds": stats([i["process_wall_seconds"] for i in cold]),
        "fresh_process_peak_rss_bytes": stats([i["peak_rss_bytes"] for i in cold]),
        "warm_analysis_seconds": stats([i["analysis_wall_seconds"] for i in warm]),
        "deterministic_report_hashes": len({i["report_sha256"] for i in cold}) == 1,
        "fresh_runs": cold,
        "warm_runs": warm,
        "scope": "Fresh: interpreter/imports + input validation/read + analysis + JSON serialization. "
        "Warm: validated decoded arrays + processing/report model. No HTTP, HTML or report disk write. "
        "For workflow=review, analysis means all seven analyses, correspondence and local evidence. "
        "Disk caches are not flushed. RSS includes interpreter and native libraries.",
    }
