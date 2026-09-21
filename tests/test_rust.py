"""Cross-language checks against the frozen Python behavior, including real data."""

import unittest

import numpy as np

from gcms.benchmark import _compare_json
from gcms.evaluation import synthetic_case
from gcms.io import DEFAULT_LIBRARY, DEFAULT_SAMPLE, read_library, read_run
from gcms.models import Parameters, ProcessingError
from gcms.pipeline import analyze
from gcms.rust_backend import native


class RustParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.core = native()
        except ProcessingError as exc:
            raise unittest.SkipTest(
                "Build the optional Rust extension to run parity checks"
            ) from exc

    def assert_equivalent(self, run, library, params=Parameters()):
        expected_arrays, actual_arrays = {}, {}
        expected = analyze(run, library, params, arrays=expected_arrays).model_dump()
        actual = analyze(run, library, params, arrays=actual_arrays, engine="rust").model_dump()
        expected["provenance"].pop("software")
        actual["provenance"].pop("software")
        differences = []
        _compare_json(expected, actual, "report", differences)
        self.assertEqual(differences, [])
        for name, expected_array in expected_arrays.items():
            actual_array = actual_arrays[name]
            self.assertEqual(expected_array.shape, actual_array.shape, name)
            if expected_array.dtype.kind == "i":
                np.testing.assert_array_equal(actual_array, expected_array, err_msg=name)
            else:
                np.testing.assert_allclose(
                    actual_array, expected_array, rtol=1e-6, atol=1e-8, err_msg=name
                )

    def test_signals_across_filter_windows_and_memory_layouts(self):
        for kind in ("isolated", "overlap", "blank"):
            for smoothing in (0, 0.3, 0.8, 1.6, 5):
                with self.subTest(kind=kind, smoothing=smoothing):
                    run, library, _ = synthetic_case(kind)
                    if smoothing == 1.6:
                        run.intensity = np.asfortranarray(run.intensity)
                    self.assert_equivalent(run, library, Parameters(smoothing_seconds=smoothing))

    def test_plateaus_ties_and_references_outside_mass_range(self):
        run, library, _ = synthetic_case()
        run.intensity.fill(30)
        for mass, height in ((43, 1000), (55, 700), (71, 400)):
            run.intensity[300:320, mass - 40] += height
            run.intensity[600:621, mass - 40] += height
        library.spectra[1] = library.spectra[0].copy()
        params = Parameters(smoothing_seconds=0, coapex_seconds=0)
        self.assert_equivalent(run, library, params)
        for peaks in library.spectra:
            peaks[:, 0] += 1000
        self.assert_equivalent(run, library, params)

    def test_short_acquisition_with_full_length_filter(self):
        run, library, _ = synthetic_case()
        run.time_seconds = run.time_seconds[:7]
        run.intensity = run.intensity[:7].copy()
        self.assert_equivalent(run, library, Parameters(smoothing_seconds=5))

    @unittest.skipUnless(
        DEFAULT_SAMPLE and DEFAULT_LIBRARY, "Set GCMS_SAMPLE and GCMS_LIBRARY for real-input parity"
    )
    def test_real_sample_and_conservative_thresholds(self):
        run, library = read_run(DEFAULT_SAMPLE), read_library(DEFAULT_LIBRARY)
        for params in (Parameters(), Parameters(noise_multiplier=12, min_component_fraction=0.002)):
            with self.subTest(params=params):
                self.assert_equivalent(run, library, params)

    def test_native_boundary_rejects_invalid_inputs(self):
        signal = np.ones((7, 2))
        with self.assertRaises(ValueError):
            self.core.preprocess(signal, [1, 1], 3)
        signal[0, 0] = np.nan
        with self.assertRaises(ValueError):
            self.core.preprocess(signal, [1], 3)
        with self.assertRaises(ValueError):
            self.core.detect(
                np.ones((7, 2)), np.arange(7.0), np.ones(1), [0.6, 30, 0.5, 8, 3, 0.01, 0.001]
            )


if __name__ == "__main__":
    unittest.main()
