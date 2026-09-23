"""Controlled synthetic checks and real-sample parameter sensitivity."""

import hashlib
import json
from collections import Counter

import numpy as np
from scipy.optimize import linear_sum_assignment

from .io import Library, Run
from .models import Identity, Parameters
from .pipeline import analyze


def synthetic_case(
    kind="isolated", *, separation_seconds=None, second_ratio=0.5, noise_std=0.5, seed=20260921
):
    """Known Gaussian components, shared ions, drifting background, seeded noise."""
    t = np.arange(0, 100, 0.1, dtype=np.float64)
    mz = np.arange(40, 101, dtype=np.float64)
    signatures = [
        np.array([[43, 100], [55, 70], [71, 40], [85, 20]], dtype=float),
        np.array([[57, 100], [69, 80], [71, 20], [99, 30]], dtype=float),
    ]
    centers = [30.0, 70.0] if kind != "overlap" else [45.0, 48.0]
    if separation_seconds is not None:
        centers = [45.0, 45.0 + separation_seconds]
    matrix = np.zeros((len(t), len(mz)))
    truth = []
    if kind != "blank":
        for i, (peaks, center) in enumerate(zip(signatures, centers)):
            profile = (100 if i == 0 else 100 * second_ratio) * np.exp(
                -0.5 * ((t - center) / 0.9) ** 2
            )
            matrix[:, peaks[:, 0].astype(int) - 40] += profile[:, None] * peaks[:, 1]
            truth.append(
                {
                    "name": f"synthetic-{i + 1}",
                    "apex_seconds": center,
                    "area": float(np.trapezoid(profile, x=t) * peaks[:, 1].sum()),
                }
            )
    matrix += (30 + 0.1 * t)[:, None]
    matrix += np.random.default_rng(seed).normal(0, noise_std, matrix.shape)
    np.maximum(matrix, 0, out=matrix)
    run = Run(
        t,
        mz,
        matrix,
        f"synthetic-{kind}",
        hashlib.sha256(matrix.tobytes()).hexdigest(),
        {"synthetic": True, "seed": seed},
    )
    identities = [
        [Identity(entry_id=f"entry-{i + 1:04d}", name=f"synthetic-{i + 1}")] for i in range(2)
    ]
    library = Library(
        identities,
        signatures,
        "synthetic-library",
        {
            "entries": 2,
            "spectrum_groups": 2,
            "exact_duplicate_groups": 0,
            "duplicate_groups_with_different_names": 0,
            "duplicate_groups_with_different_cas": 0,
        },
    )
    return run, library, truth


def detection_metrics(report, truth, tolerance_seconds=0.75):
    """Maximum-cardinality time matching; ambiguous pairs cannot validate identity/area."""
    distances = np.abs(
        np.asarray([p.apex_seconds for p in report.components])[:, None]
        - np.asarray([q["apex_seconds"] for q in truth])[None, :]
    )
    eligible = distances <= tolerance_seconds
    # One invalid edge costs more than all valid distances together: maximize
    # matched count first, then minimize time error without looking at identities.
    penalty = (min(distances.shape) + 1) * (tolerance_seconds + 1)
    found_indices, truth_indices = linear_sum_assignment(np.where(eligible, distances, penalty))
    matches = []
    for i, j in zip(found_indices, truth_indices):
        if eligible[i, j]:
            p, q = report.components[i], truth[j]
            ambiguous = eligible[i].sum() > 1 or eligible[:, j].sum() > 1
            top_names = [v.name for v in p.candidates[0].identities] if p.candidates else []
            matches.append(
                {
                    "component_id": p.component_id,
                    "expected_name": q["name"],
                    "apex_error_seconds": float(distances[i, j]),
                    "correspondence_ambiguous": bool(ambiguous),
                    "relative_area_error": None
                    if ambiguous
                    else abs(p.area - q["area"]) / q["area"],
                    "top_group_contains_expected_name": None
                    if ambiguous
                    else q["name"] in top_names,
                    "status": p.status,
                }
            )
    found, expected, correct = len(report.components), len(truth), len(matches)
    return {
        "expected": expected,
        "detected": found,
        "matched": correct,
        "false_detections": found - correct,
        "missed": expected - correct,
        "precision": correct / found if found else None,
        "recall": correct / expected if expected else None,
        "matches": matches,
        "matching_tolerance_seconds": tolerance_seconds,
        "uniquely_assessable_matches": sum(not m["correspondence_ambiguous"] for m in matches),
        "wrong_tentative_matches": sum(
            m["status"] == "tentative" and m["top_group_contains_expected_name"] is False
            for m in matches
        ),
    }


def stress_evaluation(*, engine="python"):
    """Fixed challenge cases, including failures; never tune processing settings here."""
    rows = []
    scenarios = [
        (
            f"separation-{separation:g}-ratio-{ratio:g}",
            {"separation_seconds": separation, "second_ratio": ratio, "noise_std": 5.0},
            "complete",
        )
        for separation in (0.0, 0.5, 1.5, 3.0)
        for ratio in (1.0, 0.1, 0.01)
    ] + [
        ("weak-noisy", {"second_ratio": 0.001, "noise_std": 25.0}, "complete"),
        ("noisy-blank", {"kind": "blank", "noise_std": 25.0}, "complete"),
        ("missing-reference", {}, "missing"),
        ("similar-wrong-reference", {}, "nearby_decoy"),
    ]
    for name, settings, reference_mode in scenarios:
        for seed in (17, 29, 43):
            run, library, truth = synthetic_case(**settings, seed=seed)
            if reference_mode == "missing":
                library.identities = library.identities[:1]
                library.spectra = library.spectra[:1]
            elif reference_mode == "nearby_decoy":
                # Synthetic different label with very similar fragment evidence.
                library.identities[1][0].name = "synthetic-decoy"
                library.spectra[1][:, 1] *= [0.9, 1.1, 0.9, 1.1]
            library.audit.update(
                entries=len(library.identities), spectrum_groups=len(library.spectra)
            )
            library.sha256 = hashlib.sha256(
                json.dumps(
                    {
                        "identities": [
                            [i.model_dump() for i in group] for group in library.identities
                        ],
                        "spectra": [v.tolist() for v in library.spectra],
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            report = analyze(run, library, Parameters(), engine=engine)
            rows.append(
                {
                    "scenario": name,
                    "settings": settings,
                    "seed": seed,
                    "reference_mode": reference_mode,
                    "input_array_sha256": run.source_sha256,
                    "synthetic_library_sha256": library.sha256,
                    "metrics": detection_metrics(report, truth),
                    "statuses": report.summary["statuses"],
                    "warning_counts": dict(
                        Counter(w for p in report.components for w in p.warnings)
                    ),
                }
            )
    return {
        "protocol": "synthetic-stress-1",
        "parameters": Parameters().model_dump(),
        "seeds": [17, 29, 43],
        "case_count": len(rows),
        "case_count_with_missed_components": sum(r["metrics"]["missed"] > 0 for r in rows),
        "case_count_with_extra_detections": sum(r["metrics"]["false_detections"] > 0 for r in rows),
        "case_count_with_wrong_tentative_match": sum(
            r["metrics"]["wrong_tentative_matches"] > 0 for r in rows
        ),
        "interpretation": "Constructed stress cases expose failure modes, not population accuracy. All cases and seeds are retained. Co-elution can make time-based identity and area attribution ambiguous (null). The nearby decoy deliberately demonstrates that spectral similarity cannot establish chemical identity.",
        "cases": rows,
    }


def evaluate(run: Run | None = None, library: Library | None = None, *, engine="python"):
    cases = {}
    for kind in ("isolated", "overlap", "blank"):
        sample, references, truth = synthetic_case(kind)
        report = analyze(sample, references, engine=engine)
        cases[kind] = detection_metrics(report, truth)
    result = {
        "evaluation_version": "2.0",
        "engine": engine,
        "software": report.provenance["software"],
        "synthetic_matching": "Maximum-cardinality time-only matching within 0.75 seconds, then minimum total time error. Competing compatible pairs have null identity/area metrics.",
        "synthetic": cases,
        "stress": stress_evaluation(engine=engine),
        "interpretation": "Controlled signal tests validate mechanics, not chemical labels or real-sample accuracy.",
        "real_sample_identification_accuracy": None,
        "reason_accuracy_unmeasured": "No independently verified identities supplied.",
    }
    if run is not None and library is not None:
        variants = [
            ("permissive", Parameters(noise_multiplier=6, min_component_fraction=0.0005)),
            ("default", Parameters()),
            ("conservative", Parameters(noise_multiplier=12, min_component_fraction=0.002)),
        ]
        reports = {name: analyze(run, library, params, engine=engine) for name, params in variants}
        baseline = reports["default"]
        sensitivity = []
        for name, params in variants:
            report = reports[name]
            distances = sorted(
                (abs(a.apex_seconds - b.apex_seconds), i, j)
                for i, a in enumerate(baseline.components)
                for j, b in enumerate(report.components)
            )
            used_a, used_b, unchanged = set(), set(), 0
            for distance, i, j in distances:
                if distance <= 0.75 and i not in used_a and j not in used_b:
                    used_a.add(i)
                    used_b.add(j)
                    a, b = baseline.components[i].candidates, report.components[j].candidates
                    unchanged += bool(a and b and a[0].group_id == b[0].group_id)
            sensitivity.append(
                {
                    "variant": name,
                    "parameters": params.model_dump(),
                    **report.summary,
                    "matched_default_components": len(used_a),
                    "default_component_retention_fraction": len(used_a)
                    / max(1, len(baseline.components)),
                    "unchanged_top_group_fraction_among_matched": unchanged / len(used_a)
                    if used_a
                    else None,
                    "matching_tolerance_seconds": 0.75,
                }
            )
        result["sensitivity"] = sensitivity
        result["input_data_ms_sha256"] = run.source_sha256
        result["library_sha256"] = library.sha256
    return result
