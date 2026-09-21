"""Deterministic numerical stages; no HTTP, filesystem writes or plotting here.

The baseline reconstructs spectra from ions that peak together. It does not
claim complete separation of co-eluting compounds. See docs/science.md.
"""

from collections import Counter
from dataclasses import dataclass
from importlib.metadata import version
from time import perf_counter

import numpy as np
from scipy.ndimage import grey_opening
from scipy.signal import find_peaks, peak_widths, savgol_filter

from . import __version__
from .io import Library, Run
from .models import AnalysisReport, Candidate, Component, Parameters, ProcessingError, Spectrum


@dataclass
class Prepared:
    corrected: np.ndarray
    baseline_tic: np.ndarray
    noise: np.ndarray


@dataclass
class Feature:
    apex: int
    start: int
    end: int
    ions: np.ndarray
    area: float
    spectral_change: float


def window_scans(seconds: float, dt: float, length: int) -> int:
    """Nearest odd window, at least one, capped to the largest odd run length."""
    size = max(1, int(np.rint(seconds / dt)))
    size += size % 2 == 0
    return min(size, length if length % 2 else length - 1)


def preprocess(run: Run, params: Parameters, noise=None) -> Prepared:
    dt = float(np.median(np.diff(run.time_seconds)))
    smooth_n = window_scans(params.smoothing_seconds, dt, len(run.time_seconds))
    if smooth_n >= 3:
        smooth = savgol_filter(run.intensity, smooth_n, 2, axis=0, mode="interp")
        np.maximum(smooth, 0, out=smooth)
    else:
        smooth = run.intensity.copy()
    baseline_n = window_scans(params.baseline_seconds, dt, len(run.time_seconds))
    baseline = grey_opening(smooth, size=(baseline_n, 1), mode="nearest")
    smooth -= baseline
    np.maximum(smooth, 0, out=smooth)
    if noise is None:
        differences = np.diff(run.intensity, axis=0)
        differences -= np.median(differences, axis=0)
        # Gaussian-equivalent MAD estimate from successive differences. A one-count
        # floor keeps sparse/constant channels from having a zero detection threshold.
        noise = np.maximum(np.median(np.abs(differences), axis=0) / 0.9538725524, 1.0)
    return Prepared(smooth, baseline.sum(axis=1), noise)


def detect_components(run: Run, prepared: Prepared, params: Parameters):
    dt = float(np.median(np.diff(run.time_seconds)))
    y = prepared.corrected
    events = []
    count = 0
    for ion in range(y.shape[1]):
        indices, props = find_peaks(
            y[:, ion],
            # On nonnegative traces, prominence cannot exceed height. Apply the
            # same cheap rejection as Rust before the more expensive base search.
            height=params.noise_multiplier * prepared.noise[ion],
            prominence=params.noise_multiplier * prepared.noise[ion],
            width=(params.min_width_seconds / dt, params.max_width_seconds / dt),
        )
        if len(indices):
            _, _, left, right = peak_widths(
                y[:, ion],
                indices,
                rel_height=0.95,
                prominence_data=(props["prominences"], props["left_bases"], props["right_bases"]),
            )
            events.append(
                np.column_stack(
                    (
                        indices,
                        np.full(len(indices), ion),
                        y[indices, ion],
                        props["prominences"],
                        left,
                        right,
                    )
                )
            )
            count += len(indices)
        if count > 100_000:
            raise ProcessingError(
                "too_many_ion_peaks", "More than 100,000 ion peaks; increase noise_multiplier."
            )
    if not events:
        return [], np.zeros((0, y.shape[1]), dtype=np.float64)
    events = np.concatenate(events)
    events = events[np.lexsort((events[:, 1], events[:, 0]))]
    used = np.zeros(len(events), dtype=bool)
    scan_indices = events[:, 0].astype(int)
    order = np.argsort(-events[:, 3], kind="stable")
    radius = params.coapex_seconds / dt
    # Batch the searches: a float boundary otherwise casts the integer event array
    # again for every seed. The full sorted event list and interval rules are unchanged.
    lower = np.searchsorted(scan_indices, scan_indices - radius, side="left")
    upper = np.searchsorted(scan_indices, scan_indices + radius, side="right")
    minimum_height = params.min_component_fraction * float(y.sum(axis=1).max())
    features, spectra = [], []
    # ponytail: greedy co-apex grouping cannot separate unresolved co-elution;
    # add chromatographic profile fitting when validated mixtures demonstrate the need.
    for seed in order:
        if used[seed]:
            continue
        apex = scan_indices[seed]
        lo, hi = lower[seed], upper[seed]
        members = np.arange(lo, hi)[~used[lo:hi]]
        all_members = members.copy()
        members = members[
            events[members, 2] >= events[members, 2].max() * params.relative_ion_threshold
        ]
        # Keep the strongest event per ion inside the co-apex window.
        members = members[np.argsort(-events[members, 3], kind="stable")]
        _, first = np.unique(events[members, 1], return_index=True)
        members = members[first]
        if len(members) < params.min_ions:
            used[seed] = True
            continue
        used[all_members] = True
        ions = np.sort(events[members, 1].astype(int))
        spectrum = np.zeros(y.shape[1], dtype=np.float64)
        spectrum[ions] = y[max(0, apex - 1) : min(len(y), apex + 2), :][:, ions].mean(axis=0)
        if spectrum.sum() < minimum_height:
            continue
        start = max(0, min(apex - 1, int(np.floor(np.median(events[members, 4])))))
        end = min(len(y) - 1, max(apex + 1, int(np.ceil(np.median(events[members, 5])))))
        area = float(
            np.trapezoid(
                y[start : end + 1, :][:, ions].sum(axis=1), x=run.time_seconds[start : end + 1]
            )
        )
        left_scan = (start + apex) // 2
        right_scan = (apex + end + 1) // 2
        a, b = np.sqrt(y[left_scan]), np.sqrt(y[right_scan])
        denominator = np.linalg.norm(a) * np.linalg.norm(b)
        change = float(1 - np.clip(np.dot(a, b) / denominator, 0, 1)) if denominator else 1.0
        features.append(Feature(int(apex), start, end, ions, area, change))
        spectra.append(spectrum)
        if len(features) > 1000:
            raise ProcessingError(
                "too_many_components", "More than 1,000 components; increase noise_multiplier."
            )
    order = sorted(range(len(features)), key=lambda i: (features[i].apex, tuple(features[i].ions)))
    return [features[i] for i in order], np.asarray([spectra[i] for i in order]).reshape(
        -1, y.shape[1]
    )


def normalize_spectra(spectra: np.ndarray) -> np.ndarray:
    transformed = np.sqrt(spectra)
    norms = np.linalg.norm(transformed, axis=1, keepdims=True)
    return np.divide(transformed, norms, out=np.zeros_like(transformed), where=norms > 0)


def match_spectra(
    spectra: np.ndarray, reference: np.ndarray, *, reference_normalized=False
) -> np.ndarray:
    """Square-root cosine on the measured nominal-mass grid, with zero-filled ions."""
    if not reference_normalized:
        reference = normalize_spectra(reference)
    # BLAS can accumulate identical columns differently at matrix tile boundaries.
    # Score each exact reference vector once so stable ranking preserves true ties.
    unique, inverse = np.unique(reference, axis=0, return_inverse=True)
    return np.clip(normalize_spectra(spectra) @ unique.T, 0, 1)[:, inverse]


def spectrum_model(mz, intensity) -> Spectrum:
    valid = intensity > 0
    return Spectrum(mz=mz[valid].tolist(), intensity=intensity[valid].tolist())


def build_report(
    run: Run,
    library: Library,
    params: Parameters,
    prepared: Prepared,
    features: list[Feature],
    spectra,
    reference,
    fractions,
    scores,
) -> AnalysisReport:
    components = []
    total_area = sum(f.area for f in features)
    valid = np.flatnonzero(reference.sum(axis=1) > 0)
    for i, feature in enumerate(features):
        score = scores[i]
        ranked = valid[np.argsort(-score[valid], kind="stable")]
        warnings = []
        margin, close = None, 0
        status = "unassigned"
        if len(ranked):
            best = ranked[0]
            margin = float(score[best] - score[ranked[1]]) if len(ranked) > 1 else None
            close = int(np.count_nonzero(score[ranked] >= score[best] - params.ambiguity_margin))
            identity_keys = {
                ("cas", item.cas) if item.cas else ("name", item.name.casefold())
                for item in library.identities[best]
            }
            if len(identity_keys) > 1:
                warnings.append("conflicting_reference_identities")
            if close > 1:
                warnings.append("similar_candidate_scores")
            if fractions[best] < 0.5:
                warnings.append("limited_reference_mass_coverage")
            if score[best] >= params.match_threshold and fractions[best] >= 0.5:
                status = "ambiguous" if len(identity_keys) > 1 or close > 1 else "tentative"
            else:
                warnings.append("no_candidate_passes_screening")
            if close > params.top_k:
                warnings.append("additional_close_candidates_not_displayed")
        else:
            warnings.append("no_reference_in_acquired_mass_range")
        if feature.spectral_change > 0.1:
            warnings.append("possible_coelution_or_spectral_change")
        if feature.start == 0 or feature.end == len(run.time_seconds) - 1:
            warnings.append("integration_touches_acquisition_edge")
        candidates = [
            Candidate(
                group_id=f"group-{j + 1:04d}",
                score=float(score[j]),
                identities=library.identities[j],
                library_intensity_fraction_in_mass_range=float(fractions[j]),
                reference_spectrum=spectrum_model(run.mz, reference[j]),
            )
            for j in ranked[: params.top_k]
        ]
        components.append(
            Component(
                component_id=f"component-{i + 1:04d}",
                apex_scan=feature.apex,
                start_seconds=float(run.time_seconds[feature.start]),
                apex_seconds=float(run.time_seconds[feature.apex]),
                end_seconds=float(run.time_seconds[feature.end]),
                area=feature.area,
                area_percent=100 * feature.area / total_area if total_area else 0,
                apexing_ion_count=len(feature.ions),
                spectrum=spectrum_model(run.mz, spectra[i]),
                status=status,
                score_margin=margin,
                close_candidate_groups=close,
                spectral_change=feature.spectral_change,
                warnings=warnings,
                candidates=candidates,
            )
        )
    raw_tic = run.intensity.sum(axis=1)
    corrected_tic = prepared.corrected.sum(axis=1)
    # Preserve min/max extrema in each display bucket, plus every component apex.
    # Full arrays are available in the benchmark bundle; this is only a plot preview.
    keep = {0, len(raw_tic) - 1, *(f.apex for f in features)}
    for bucket in np.array_split(np.arange(len(raw_tic)), min(1500, len(raw_tic))):
        keep.update(
            (int(bucket[np.argmin(raw_tic[bucket])]), int(bucket[np.argmax(raw_tic[bucket])]))
        )
    indices = np.array(sorted(keep))
    dt = np.diff(run.time_seconds)
    return AnalysisReport(
        sample_name=run.name,
        provenance={
            "input_data_ms_sha256": run.source_sha256,
            "library_sha256": library.sha256,
            "software": {
                "mafer-gcms": __version__,
                **{p: version(p) for p in ("numpy", "scipy", "rainbow-api")},
            },
            "numeric_dtype": "float64",
            "mass_binning": "nearest integer, ties to even, summed intensities",
        },
        acquisition={
            "scan_count": len(run.time_seconds),
            "mass_channel_count": len(run.mz),
            "start_seconds": float(run.time_seconds[0]),
            "end_seconds": float(run.time_seconds[-1]),
            "median_scan_interval_seconds": float(np.median(dt)),
            "mz_min": float(run.mz[0]),
            "mz_max": float(run.mz[-1]),
            "metadata": run.metadata,
        },
        parameters=params,
        library=library.audit,
        summary={
            "component_count": len(components),
            "statuses": dict(Counter(c.status for c in components)),
            "component_ion_area_sum": total_area,
            "area_unit": "instrument intensity * second",
            "area_percent_denominator": "sum of reported component-ion areas; not concentration",
        },
        warnings=[
            "Screening candidates are not confirmed chemical identities or identification probabilities.",
            "Co-apex reconstruction is not complete deconvolution; overlapping or weak components may be missed.",
            "Areas use selected apexing ions and may overlap; percentages are not composition or concentration.",
            "Library RT/RI metadata is retained but not used for scoring; comparability is unverified.",
        ]
        + (["No components passed the detection criteria."] if not components else []),
        chromatogram={
            "time_seconds": run.time_seconds[indices].tolist(),
            "raw_tic": raw_tic[indices].tolist(),
            "baseline_tic": prepared.baseline_tic[indices].tolist(),
            "corrected_tic": corrected_tic[indices].tolist(),
            "preview": True,
            "full_scan_count": len(raw_tic),
        },
        components=components,
    )


def analyze(
    run: Run,
    library: Library,
    params: Parameters | None = None,
    *,
    timings: dict | None = None,
    arrays: dict | None = None,
    engine: str = "python",
    _prepared: Prepared | None = None,
    _noise: np.ndarray | None = None,
    _reference: tuple | None = None,
) -> AnalysisReport:
    """Optional collectors expose stage timings/arrays without altering results."""
    params = params or Parameters()
    run.validate()
    if engine not in ("python", "rust"):
        raise ValueError("engine must be python or rust")
    if engine == "rust":
        from . import rust_backend
    prepare = rust_backend.preprocess if engine == "rust" else preprocess
    detect = rust_backend.detect_components if engine == "rust" else detect_components
    timing = timings if timings is not None else {}
    t = perf_counter()
    # Review can reuse its own baseline when only detection settings change.
    if _prepared is not None:
        prepared = _prepared
    elif engine == "rust":
        prepared = prepare(run, params)
    else:
        prepared = prepare(run, params, noise=_noise)
    timing["preprocess_seconds"] = perf_counter() - t
    t = perf_counter()
    features, spectra = detect(run, prepared, params)
    timing["detect_extract_seconds"] = perf_counter() - t
    t = perf_counter()
    if engine == "rust":
        reference, fractions, scores = rust_backend.project_match(run, library, spectra)
    else:
        if _reference is None:
            reference, fractions = library.project(run.mz)
            normalized = normalize_spectra(reference)
        else:
            reference, fractions, normalized = _reference
        scores = match_spectra(spectra, normalized, reference_normalized=True)
    timing["project_match_seconds"] = perf_counter() - t
    t = perf_counter()
    report = build_report(
        run, library, params, prepared, features, spectra, reference, fractions, scores
    )
    if engine == "rust":
        report.provenance["software"]["gcms-rust"] = "0.1.0"
    timing["report_seconds"] = perf_counter() - t
    if arrays is not None:
        arrays.update(
            time_seconds=run.time_seconds,
            mz=run.mz,
            intensity=run.intensity,
            corrected=prepared.corrected,
            baseline_tic=prepared.baseline_tic,
            noise=prepared.noise,
            reference_intensity=reference,
            reference_mass_fraction=fractions,
            component_spectra=spectra,
            scores=scores,
            component_apex_scan=np.array([f.apex for f in features], dtype=np.int64),
            component_bounds_scan=np.array(
                [[f.start, f.end] for f in features], dtype=np.int64
            ).reshape(-1, 2),
            component_area=np.array([f.area for f in features]),
        )
        if engine == "python":
            arrays["reference_normalized"] = normalized
    return report
