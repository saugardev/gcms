"""Per-component sensitivity and local evidence, using either numerical engine."""

import csv
from collections import Counter
from time import perf_counter

import numpy as np

from .models import (
    ComponentReview,
    IonTrace,
    Parameters,
    PeakTrace,
    ProcessingError,
    ProfileObservation,
    ReviewReport,
    ReviewVariant,
)
from .pipeline import analyze, match_spectra

MATCH_SECONDS = 0.75
MATCH_SIMILARITY = 0.8


def profile_settings(params):
    """Fixed perturbations of the supplied baseline; no tuning against identity labels."""
    return [
        (
            "permissive",
            {
                "noise_multiplier": params.noise_multiplier * 0.75,
                "min_component_fraction": params.min_component_fraction * 0.5,
            },
        ),
        (
            "conservative",
            {
                "noise_multiplier": params.noise_multiplier * 1.5,
                "min_component_fraction": params.min_component_fraction * 2,
            },
        ),
        ("less_smoothing", {"smoothing_seconds": params.smoothing_seconds * 0.5}),
        ("more_smoothing", {"smoothing_seconds": params.smoothing_seconds * 1.5}),
        ("narrow_grouping", {"coapex_seconds": params.coapex_seconds * 0.5}),
        ("wide_grouping", {"coapex_seconds": params.coapex_seconds * 1.5}),
    ]


def component_arrays(report, mz):
    spectra = np.zeros((len(report.components), len(mz)))
    for i, p in enumerate(report.components):
        indices = np.rint(np.asarray(p.spectrum.mz) - mz[0]).astype(int)
        spectra[i, indices] = p.spectrum.intensity
    return np.asarray([p.apex_seconds for p in report.components]), spectra


def eligible_matches(base_times, base_spectra, times, spectra, engine="python"):
    """Return all RT/spectrum-compatible edges; ambiguity is preserved by the caller."""
    if engine == "rust":
        from .rust_backend import native

        return native().correspondences(
            base_times, base_spectra, times, spectra, MATCH_SECONDS, MATCH_SIMILARITY
        )
    scores = match_spectra(base_spectra, spectra)
    valid = (np.abs(base_times[:, None] - times[None, :]) <= MATCH_SECONDS) & (
        scores >= MATCH_SIMILARITY
    )
    return [
        [(int(j), float(scores[i, j])) for j in np.flatnonzero(row)] for i, row in enumerate(valid)
    ]


def observations(baseline, other, mz, name, engine):
    edges = eligible_matches(*component_arrays(baseline, mz), *component_arrays(other, mz), engine)
    incoming = Counter(j for row in edges for j, _ in row)
    result, used = [], set()
    for p, row in zip(baseline.components, edges):
        if not row:
            result.append(ProfileObservation(profile=name, outcome="not_matched"))
        elif len(row) != 1 or incoming[row[0][0]] != 1:
            result.append(
                ProfileObservation(profile=name, outcome="ambiguous", eligible_components=len(row))
            )
        else:
            j, similarity = row[0]
            q = other.components[j]
            used.add(j)
            best = q.candidates[0] if q.candidates else None
            same = p.candidates[0].group_id == best.group_id if p.candidates and best else None
            result.append(
                ProfileObservation(
                    profile=name,
                    outcome="matched",
                    eligible_components=1,
                    component_id=q.component_id,
                    apex_seconds=q.apex_seconds,
                    spectral_similarity=similarity,
                    top_group_id=best.group_id if best else None,
                    top_names=list(dict.fromkeys(v.name for v in best.identities)) if best else [],
                    same_top_group=same,
                    identification_status=q.status,
                    area=q.area,
                )
            )
    return result, len(other.components) - len(used)


def peak_trace(run, corrected, raw_tic, corrected_tic, component):
    t = run.time_seconds
    padding = max(2.0, (component.end_seconds - component.start_seconds) * 0.5)
    lo = max(0, int(np.searchsorted(t, component.start_seconds - padding)) - 1)
    hi = min(len(t), int(np.searchsorted(t, component.end_seconds + padding, side="right")) + 1)
    ions = np.rint(np.asarray(component.spectrum.mz) - run.mz[0]).astype(int)
    local = corrected[lo:hi]
    selected_sum = local[:, ions].sum(axis=1)
    top = np.argsort(-np.asarray(component.spectrum.intensity), kind="stable")[:5]
    top_ions = ions[top]
    keep = {
        0,
        hi - lo - 1,
        component.apex_scan - lo,
        int(np.searchsorted(t, component.start_seconds)) - lo,
        int(np.searchsorted(t, component.end_seconds)) - lo,
    }
    if hi - lo <= 400:
        indices = np.arange(hi - lo)
    else:
        # ponytail: bounded plot preview; full numerical arrays remain available in bundles.
        for bucket in np.array_split(np.arange(hi - lo), 24):
            for trace in (
                raw_tic[lo:hi],
                corrected_tic[lo:hi],
                selected_sum,
                *(local[:, ion] for ion in top_ions),
            ):
                keep.update(
                    (int(bucket[np.argmin(trace[bucket])]), int(bucket[np.argmax(trace[bucket])]))
                )
        indices = np.asarray(sorted(keep))
    return PeakTrace(
        time_seconds=t[lo + indices].tolist(),
        raw_tic=raw_tic[lo + indices].tolist(),
        corrected_tic=corrected_tic[lo + indices].tolist(),
        component_ion_sum=selected_sum[indices].tolist(),
        ions=[
            IonTrace(mz=float(run.mz[ion]), intensity=local[indices, ion].tolist())
            for ion in top_ions
        ],
        preview=len(indices) < hi - lo,
        full_window_scan_count=hi - lo,
    )


def select_packet(report, annotations, limit=12):
    ranked = sorted(report.components, key=lambda p: (-p.area, p.component_id))
    groups = [
        (
            "consistent tentative example",
            lambda p: p.status == "tentative" and annotations[p.component_id].label == "consistent",
        ),
        ("ambiguous library identity", lambda p: p.status == "ambiguous"),
        (
            "sensitive to processing settings",
            lambda p: annotations[p.component_id].label == "sensitive",
        ),
        (
            "inconclusive correspondence",
            lambda p: annotations[p.component_id].label == "inconclusive",
        ),
        ("unassigned example", lambda p: p.status == "unassigned"),
    ]
    chosen = []
    for reason, predicate in groups:
        for p in [p for p in ranked if p.component_id not in chosen and predicate(p)][:2]:
            if len(chosen) < limit:
                chosen.append(p.component_id)
                annotations[p.component_id].selection_reasons.append(reason)
    for p in ranked:
        if len(chosen) >= limit:
            break
        if p.component_id not in chosen:
            chosen.append(p.component_id)
            annotations[p.component_id].selection_reasons.append("large reported area")
    return chosen


def build_review(run, library, params=None, *, engine="python", timings=None):
    params = params or Parameters()
    timings = timings if timings is not None else {}
    arrays = {}
    start = perf_counter()
    baseline = analyze(run, library, params, engine=engine, arrays=arrays)
    timings["baseline_seconds"] = perf_counter() - start
    records = {p.component_id: [] for p in baseline.components}
    variants = [
        ReviewVariant(
            name="baseline",
            parameters=params.model_dump(),
            state="completed",
            component_count=len(baseline.components),
            statuses=baseline.summary["statuses"],
        )
    ]
    seen = {params.model_dump_json()}
    start = perf_counter()
    matching_time = 0.0
    for name, updates in profile_settings(params):
        settings = params.model_dump() | updates
        try:
            proposed = Parameters.model_validate(settings)
        except ValueError:
            variants.append(
                ReviewVariant(
                    name=name,
                    parameters=settings,
                    state="skipped",
                    reason="Outside allowed parameter bounds",
                )
            )
            for rows in records.values():
                rows.append(ProfileObservation(profile=name, outcome="not_evaluated"))
            continue
        key = proposed.model_dump_json()
        if key in seen:
            variants.append(
                ReviewVariant(
                    name=name,
                    parameters=settings,
                    state="skipped",
                    reason="Duplicates another profile",
                )
            )
            for rows in records.values():
                rows.append(ProfileObservation(profile=name, outcome="not_evaluated"))
            continue
        seen.add(key)
        try:
            other = analyze(run, library, proposed, engine=engine)
        except (ProcessingError, ValueError) as exc:
            variants.append(
                ReviewVariant(name=name, parameters=settings, state="failed", reason=str(exc))
            )
            for rows in records.values():
                rows.append(ProfileObservation(profile=name, outcome="not_evaluated"))
            continue
        matched_at = perf_counter()
        rows, unmatched = observations(baseline, other, run.mz, name, engine)
        matching_time += perf_counter() - matched_at
        for p, row in zip(baseline.components, rows):
            records[p.component_id].append(row)
        variants.append(
            ReviewVariant(
                name=name,
                parameters=settings,
                state="completed",
                component_count=len(other.components),
                statuses=other.summary["statuses"],
                unmatched_variant_components=unmatched,
            )
        )
    timings["variant_analysis_seconds"] = perf_counter() - start - matching_time
    timings["correspondence_seconds"] = matching_time
    start = perf_counter()
    raw_tic = run.intensity.sum(axis=1)
    corrected_tic = arrays["corrected"].sum(axis=1)
    annotations = {}
    complete = all(v.state == "completed" for v in variants)
    for p in baseline.components:
        rows = records[p.component_id]
        evaluated = [r for r in rows if r.outcome != "not_evaluated"]
        matched = [r for r in rows if r.outcome == "matched"]
        same = sum(r.same_top_group is True for r in matched)
        known_change = any(
            r.outcome == "not_matched" or r.same_top_group is False for r in evaluated
        )
        consistent = complete and len(evaluated) == 6 and len(matched) == same == len(evaluated)
        label = "sensitive" if known_change else "consistent" if consistent else "inconclusive"
        ratios = [r.area / p.area for r in matched] if p.area > 0 else []
        annotations[p.component_id] = ComponentReview(
            label=label,
            evaluated_profiles=len(evaluated),
            matched_profiles=len(matched),
            same_top_group_profiles=same,
            match_fraction=len(matched) / len(evaluated) if evaluated else None,
            max_apex_shift_seconds=max(
                (abs(r.apex_seconds - p.apex_seconds) for r in matched), default=None
            ),
            min_area_ratio=min(ratios, default=None),
            max_area_ratio=max(ratios, default=None),
            observations=rows,
            trace=peak_trace(run, arrays["corrected"], raw_tic, corrected_tic, p),
        )
    packet = select_packet(baseline, annotations)
    timings["evidence_seconds"] = perf_counter() - start
    return ReviewReport(
        analysis=baseline,
        variants=variants,
        annotations=annotations,
        review_packet=packet,
        method={
            "version": "stability-1",
            "time_tolerance_seconds": MATCH_SECONDS,
            "minimum_spectral_similarity": MATCH_SIMILARITY,
            "planned_alternative_profiles": 6,
            "matching": "Reciprocally unique RT/spectrum-compatible components; competing matches remain ambiguous.",
            "denominator": "Completed alternative profiles, excluding baseline. Ambiguous correspondence is not a confirmed match.",
            "consistent": "All six alternative profiles complete, uniquely match, and retain the same nonempty top reference group.",
        },
        summary={
            "labels": dict(Counter(a.label for a in annotations.values())),
            "completed_alternative_profiles": sum(v.state == "completed" for v in variants[1:]),
            "selected_for_review": len(packet),
        },
        warnings=[
            "Stability under these settings is not identification probability or chemical correctness.",
            "Correspondence thresholds are heuristic; nearby splits/merges can remain ambiguous.",
            "Only baseline detections receive annotations; additional variant detections are counted separately.",
            "The review packet is a purposive selection, not a representative accuracy test. All entries are unreviewed.",
        ],
    )


def write_review_csv(path, review):
    selected = set(review.review_packet)

    def safe(value):
        return (
            "'" + value
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@"))
            else value
        )

    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "component_id",
                "apex_minutes",
                "candidate_names",
                "identification_status",
                "stability",
                "matched_profiles",
                "evaluated_profiles",
                "selection_reason",
                "review_status",
                "analyst_identity",
                "reviewer",
                "notes",
            ]
        )
        for p in review.analysis.components:
            if p.component_id in selected:
                a = review.annotations[p.component_id]
                names = (
                    " / ".join(i.name for i in p.candidates[0].identities) if p.candidates else ""
                )
                writer.writerow(
                    map(
                        safe,
                        [
                            p.component_id,
                            p.apex_seconds / 60,
                            names,
                            p.status,
                            a.label,
                            a.matched_profiles,
                            a.evaluated_profiles,
                            "; ".join(a.selection_reasons),
                            "unreviewed",
                            "",
                            "",
                            "",
                        ],
                    )
                )
