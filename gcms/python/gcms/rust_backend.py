"""Optional Rust numerical kernels; the existing reader and report remain shared."""

import importlib.machinery
import importlib.util
import sys
from functools import cache
from pathlib import Path

import numpy as np
from scipy.signal import savgol_coeffs

from .models import ProcessingError
from .pipeline import Feature, Prepared, window_scans


@cache
def native():
    suffix = "dylib" if sys.platform == "darwin" else "so"
    path = (
        Path(__file__).resolve().parents[2]
        / "rust"
        / "target"
        / "release"
        / f"lib_gcms_rust.{suffix}"
    )
    if not path.exists():
        raise ProcessingError(
            "rust_not_built",
            "Build first: PYO3_PYTHON=$(pwd)/.venv/bin/python cargo build --release --locked --manifest-path gcms/rust/Cargo.toml",
        )
    loader = importlib.machinery.ExtensionFileLoader("_gcms_rust", str(path))
    spec = importlib.util.spec_from_loader("_gcms_rust", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def preprocess(run, params):
    dt = float(np.median(np.diff(run.time_seconds)))
    smooth_n = window_scans(params.smoothing_seconds, dt, len(run.time_seconds))
    baseline_n = window_scans(params.baseline_seconds, dt, len(run.time_seconds))
    # Shared coefficient generation avoids comparing different least-squares solvers.
    # Rust applies the filter, fits endpoints, removes background and estimates noise.
    coefficients = savgol_coeffs(smooth_n, 2).tolist() if smooth_n >= 3 else [1.0]
    return Prepared(*native().preprocess(run.intensity, coefficients, baseline_n))


def detect_components(run, prepared, params):
    settings = [
        params.min_width_seconds,
        params.max_width_seconds,
        params.coapex_seconds,
        params.noise_multiplier,
        params.min_ions,
        params.relative_ion_threshold,
        params.min_component_fraction,
    ]
    features, spectra = native().detect(
        prepared.corrected, run.time_seconds, prepared.noise, settings
    )
    return [
        Feature(apex, start, end, np.asarray(ions, dtype=np.int64), area, change)
        for apex, start, end, ions, area, change in features
    ], spectra


def project_match(run, library, spectra):
    return native().project_match(run.mz, spectra, library.spectra)
