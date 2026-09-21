"""Build the submission and verify a fresh extracted copy. Requires Python 3.12, uv, Rust."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path


def main():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=project / "artifacts/submission-check")
    parser.add_argument(
        "--sample",
        type=Path,
        default=os.getenv("GCMS_SAMPLE"),
        help="Optional original acquisition for real-input checks",
    )
    parser.add_argument(
        "--library",
        type=Path,
        default=os.getenv("GCMS_LIBRARY"),
        help="Optional original MSP library for real-input checks",
    )
    args = parser.parse_args()
    if bool(args.sample) != bool(args.library):
        parser.error("Supply both --sample and --library, or neither for synthetic checks.")
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    evidence = {
        "status": "failed",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "commands": [],
        "external_data_checks": bool(args.sample),
    }
    env = os.environ.copy()
    for key in (
        "VIRTUAL_ENV",
        "PYTHONPATH",
        "PYTHONHOME",
        "UV_PROJECT_ENVIRONMENT",
        "UV_PROJECT",
        "UV_WORKING_DIRECTORY",
        "PYO3_PYTHON",
        "CARGO_TARGET_DIR",
        "CARGO_BUILD_TARGET",
        "GCMS_SAMPLE",
        "GCMS_LIBRARY",
    ):
        env.pop(key, None)
    if args.sample:
        env["GCMS_SAMPLE"] = str(args.sample.resolve(strict=True))
        env["GCMS_LIBRARY"] = str(args.library.resolve(strict=True))
    for key in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        env[key] = "1"
    env["UV_NO_CACHE"] = "1"

    def run(command, cwd):
        print("Running: " + " ".join(map(str, command)), flush=True)
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=600,
        )
        log = result.stdout.replace(str(cwd), "$PROJECT").replace(str(project), "$SOURCE")
        index = len(evidence["commands"]) + 1
        (output / f"step-{index:02d}.log").write_text(log)
        evidence["commands"].append(
            {
                "argv": [
                    str(v).replace(str(cwd), "$PROJECT").replace(str(project), "$SOURCE")
                    for v in command
                ],
                "exit_code": result.returncode,
                "log": f"step-{index:02d}.log",
            }
        )
        if result.returncode:
            raise RuntimeError(log[-4000:])
        return log

    try:
        evidence["uv"] = run(["uv", "--version"], project).strip()
        run(["uv", "build", "--out-dir", str(output)], project)
        version = tomllib.loads((project / "pyproject.toml").read_text())["project"]["version"]
        archive = output / f"mafer_gcms-{version}.tar.gz"
        evidence["archive"] = archive.name
        evidence["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        with (
            tempfile.TemporaryDirectory(prefix="gcms-submission-") as tmp,
            tarfile.open(archive) as source,
        ):
            files = [member for member in source.getmembers() if member.isfile()]
            forbidden = {
                "GCMS_Tech_Challenge",
                ".local",
                ".git",
                ".venv",
                "target",
                "artifacts",
                ".DS_Store",
                "__pycache__",
            }
            for member in source.getmembers():
                if forbidden.intersection(Path(member.name).parts) or not (
                    member.isfile() or member.isdir()
                ):
                    raise RuntimeError(f"Unexpected submission member: {member.name}")
            evidence["file_sha256"] = {
                str(Path(m.name).relative_to(Path(m.name).parts[0])): hashlib.sha256(
                    source.extractfile(m).read()
                ).hexdigest()
                for m in files
            }
            required = {
                "LICENSE",
                "README.md",
                "docs/README.md",
                "docs/api.md",
                "docs/science.md",
                "docs/benchmarks.md",
                "docs/validation.md",
                "gcms/README.md",
                "gcms/python/gcms/__init__.py",
                "gcms/rust/src/lib.rs",
            }
            missing = required - evidence["file_sha256"].keys()
            if missing:
                raise RuntimeError(f"Missing submission documentation: {sorted(missing)}")
            source.extractall(tmp, filter="data")
            clean = Path(tmp) / f"mafer_gcms-{version}"
            run(["uv", "sync", "--locked"], clean)
            python = str(clean / ".venv/bin/python")
            evidence["python"] = run([python, "--version"], clean).strip()
            # Import through the fresh environment, without cwd or caller PYTHONPATH.
            run(
                [
                    python,
                    "-I",
                    "-c",
                    "import gcms, pathlib; assert pathlib.Path(gcms.__file__).resolve().is_relative_to(pathlib.Path.cwd()); print(gcms.__file__)",
                ],
                clean,
            )
            evidence["rustc"] = run(["rustc", "--version"], clean).strip()
            env["PYO3_PYTHON"] = python
            run(
                [
                    "cargo",
                    "build",
                    "--release",
                    "--locked",
                    "--manifest-path",
                    "gcms/rust/Cargo.toml",
                ],
                clean,
            )
            run([python, "-c", "from gcms.rust_backend import native; native()"], clean)
            test_log = run([python, "-m", "unittest", "discover", "-s", "tests", "-v"], clean)
            if (args.sample and "skipped=" in test_log) or "Ran 0 tests" in test_log:
                raise RuntimeError("Configured submission checks must run without skips")
            evidence["tests"] = test_log[test_log.rfind("Ran ") :].strip()
            run([str(clean / ".venv/bin/ruff"), "check", "gcms", "tests", "scripts"], clean)
            for engine in ("python", "rust"):
                run(
                    [
                        str(clean / ".venv/bin/gcms"),
                        "evaluate",
                        "--engine",
                        engine,
                        "--out",
                        f"artifacts/evaluation-{engine}.json",
                    ],
                    clean,
                )
                shutil.copyfile(
                    clean / f"artifacts/evaluation-{engine}.json",
                    output / f"evaluation-{engine}.json",
                )
            if args.sample:
                run(
                    [str(clean / ".venv/bin/gcms"), "analyze", "--out", "artifacts/recomputed"],
                    clean,
                )
            comparison = run(
                [
                    python,
                    "-c",
                    """
import json
import os
from pathlib import Path
from gcms.benchmark import _compare_json
def read(name):
    return json.loads(Path(name).read_text())
differences = []
baseline_equivalent = None
if os.getenv('GCMS_SAMPLE'):
    a, b = read('examples/sample.json'), read('artifacts/recomputed.json')
    for report in (a, b):
        report['provenance'].pop('software', None)
    _compare_json(a, b, 'original_baseline', differences)
    baseline_equivalent = not differences
a, b = read('artifacts/evaluation-python.json'), read('artifacts/evaluation-rust.json')
c = read('examples/evaluation.json')
if not os.getenv('GCMS_SAMPLE'):
    for key in ('sensitivity', 'input_data_ms_sha256', 'library_sha256'):
        c.pop(key, None)
for report in (a, b, c):
    report.pop('software'); report.pop('engine')
_compare_json(a, b, 'evaluation', differences)
_compare_json(a, c, 'saved_evaluation', differences)
assert not differences, differences[:20]
print(json.dumps({'baseline_equivalent': baseline_equivalent, 'evaluation_engines_equivalent': True, 'stress': {k:v for k,v in a['stress'].items() if k not in ('cases','interpretation','parameters')}}))
""",
                ],
                clean,
            )
            evidence["results"] = json.loads(comparison)
            evidence["status"] = "passed"
            evidence["limits"] = (
                "Fresh virtual environment and fresh Rust compilation on this host. uv package cache disabled; managed Python/toolchains and Cargo registry cache may be reused. This is not a second OS test or scientific ground truth."
            )
    except Exception as exc:
        evidence["error"] = str(exc)
        raise
    finally:
        (output / "verification.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"Verified submission: {archive}\nEvidence: {output / 'verification.json'}")


if __name__ == "__main__":
    main()
