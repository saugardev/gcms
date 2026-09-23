"""CLI commands use exactly the same pipeline as the HTTP API."""

import argparse
import json
import os
import sys
from pathlib import Path

# Set before NumPy/SciPy import. Explicit caller choices take precedence.
for _variable in (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ.setdefault(_variable, "1")


def main():
    from .benchmark import (
        benchmark,
        compare_bundles,
        compare_reviews,
        export_bundle,
        load_bundle,
        run_once,
        write_json,
    )
    from .evaluation import evaluate
    from .io import DEFAULT_LIBRARY, DEFAULT_SAMPLE, read_library, read_run
    from .models import Parameters, ProcessingError
    from .pipeline import analyze
    from .report import render_report
    from .review import build_review, write_review_csv

    parser = argparse.ArgumentParser(description="GC-MS screening and Rust-port benchmark baseline")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("analyze", "review", "export-bundle", "benchmark", "evaluate", "_bench-worker"):
        p = commands.add_parser(name)
        p.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
        p.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
        p.add_argument("--engine", choices=("python", "rust"), default="python")
        if name in ("benchmark", "_bench-worker"):
            p.add_argument("--workflow", choices=("analysis", "review"), default="analysis")
        if name in ("analyze", "review", "benchmark", "_bench-worker"):
            p.add_argument(
                "--bundle", type=Path, help="Use canonical arrays from an exported bundle"
            )
        if name in ("analyze", "review", "export-bundle"):
            p.add_argument("--params", type=Path, help="JSON object of processing settings")
        if name == "analyze":
            p.add_argument("--out", type=Path, default=Path("artifacts/sample"))
        elif name == "review":
            p.add_argument("--out", type=Path, default=Path("artifacts/review"))
        elif name == "export-bundle":
            p.add_argument("--out", type=Path, default=Path("artifacts/baseline"))
        elif name == "benchmark":
            p.add_argument("--out", type=Path, default=Path("artifacts/benchmark.json"))
            p.add_argument("--repeats", type=int, default=5, choices=range(1, 51))
        elif name == "evaluate":
            p.add_argument("--out", type=Path, default=Path("artifacts/evaluation.json"))
    for name in ("compare", "compare-reviews"):
        p = commands.add_parser(name)
        p.add_argument("expected", type=Path)
        p.add_argument("actual", type=Path)
    args = parser.parse_args()
    try:
        if args.command in ("compare", "compare-reviews"):
            compare = compare_reviews if args.command == "compare-reviews" else compare_bundles
            result = compare(args.expected, args.actual)
            print(json.dumps(result, indent=2))
            return 0 if result["equivalent"] else 1
        if args.command == "evaluate" and args.sample is None and args.library is None:
            result = evaluate(engine=args.engine)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            write_json(args.out, result)
            print(json.dumps(result, indent=2))
            return 0
        if not getattr(args, "bundle", None) and (args.sample is None or args.library is None):
            raise ProcessingError(
                "inputs_required",
                "Provide --sample and --library, or set GCMS_SAMPLE and GCMS_LIBRARY. No acquisition or library is bundled.",
            )
        if args.command == "_bench-worker":
            print(
                json.dumps(
                    run_once(args.sample, args.library, args.bundle, args.engine, args.workflow),
                    allow_nan=False,
                )
            )
            return 0
        args.out.parent.mkdir(parents=True, exist_ok=True)
        if args.command == "benchmark":
            result = benchmark(
                args.sample, args.library, args.repeats, args.bundle, args.engine, args.workflow
            )
            write_json(args.out, result)
            print(
                json.dumps(
                    {
                        k: result[k]
                        for k in (
                            "engine",
                            "workflow",
                            "fresh_process_wall_seconds",
                            "warm_analysis_seconds",
                            "fresh_process_peak_rss_bytes",
                            "deterministic_report_hashes",
                        )
                    },
                    indent=2,
                )
            )
            return 0
        if getattr(args, "bundle", None):
            run, library, params = load_bundle(args.bundle)
        else:
            run, library, params = read_run(args.sample), read_library(args.library), Parameters()
        if getattr(args, "params", None):
            params = Parameters.model_validate_json(args.params.read_text())
        if args.command == "analyze":
            timings = {}
            report = analyze(run, library, params, timings=timings, engine=args.engine)
            write_json(args.out.with_suffix(".json"), report.model_dump(mode="json"))
            args.out.with_suffix(".html").write_text(render_report(report))
            print(
                json.dumps(
                    {
                        "summary": report.summary,
                        "timings": timings,
                        "json": str(args.out.with_suffix(".json")),
                        "html": str(args.out.with_suffix(".html")),
                    },
                    indent=2,
                )
            )
        elif args.command == "review":
            timings = {}
            review = build_review(run, library, params, engine=args.engine, timings=timings)
            write_json(args.out.with_suffix(".json"), review.model_dump(mode="json"))
            args.out.with_suffix(".html").write_text(render_report(review.analysis, review=review))
            packet = args.out.with_name(args.out.name + "-packet")
            packet.with_suffix(".html").write_text(
                render_report(review.analysis, review=review, packet_only=True)
            )
            write_review_csv(packet.with_suffix(".csv"), review)
            print(
                json.dumps(
                    {
                        "summary": review.summary,
                        "timings": timings,
                        "report": str(args.out.with_suffix(".html")),
                        "packet": str(packet.with_suffix(".html")),
                    },
                    indent=2,
                )
            )
        elif args.command == "export-bundle":
            export_bundle(run, library, args.library, params, args.out, engine=args.engine)
            print(f"Exported canonical inputs and expected stage outputs to {args.out}")
        elif args.command == "evaluate":
            result = evaluate(run, library, engine=args.engine)
            write_json(args.out, result)
            print(json.dumps(result, indent=2))
        return 0
    except (ProcessingError, ValueError, OSError, KeyError) as exc:
        print(
            json.dumps(
                {"error": {"code": getattr(exc, "code", "invalid_input"), "message": str(exc)}}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
