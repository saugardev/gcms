"""Behavioral checks: known signals, trust boundaries, real input, port contract."""

import hashlib
import io
import json
import shutil
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from gcms.api import create_app
from gcms.benchmark import compare_bundles, export_bundle, load_bundle
from gcms.evaluation import detection_metrics, stress_evaluation, synthetic_case
from gcms.io import DEFAULT_LIBRARY, DEFAULT_SAMPLE, extract_sample, read_library, read_run
from gcms.models import Identity, Parameters, ProcessingError
from gcms.pipeline import analyze, match_spectra
from gcms.report import render_report


def make_zip(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return stream.getvalue()


class ApiConfigurationTests(unittest.TestCase):
    def test_external_library_is_required_and_sample_is_optional(self):
        with (
            patch("gcms.api.DEFAULT_LIBRARY", None),
            self.assertRaisesRegex(ProcessingError, "GCMS_LIBRARY"),
        ):
            with TestClient(create_app()):
                pass
        with tempfile.TemporaryDirectory() as tmp, patch("gcms.api.DEFAULT_SAMPLE", None):
            library_path = Path(tmp) / "library.msp"
            library_path.write_text("Name: test\nNum Peaks: 3\n43 100; 55 70; 71 40\n")
            with TestClient(create_app(library_path)) as client:
                home = client.get("/")
                self.assertIn("const sampleAvailable = false;", home.text)
                self.assertNotIn("__SAMPLE_AVAILABLE__", home.text)
                self.assertEqual(client.get("/health").status_code, 200)
                self.assertEqual(
                    client.get("/v1/sample").json()["error"]["code"], "sample_not_configured"
                )
                self.assertEqual(client.get("/v1/sample").status_code, 503)
                self.assertEqual(client.post("/v1/analyze").status_code, 415)
            with TestClient(create_app(library_path, Path("sample.D"))) as client:
                self.assertIn("const sampleAvailable = true;", client.get("/").text)


class SignalTests(unittest.TestCase):
    def test_time_assignment_maximizes_matches_without_claiming_ambiguous_identity(self):
        run, library, truth = synthetic_case()
        report = analyze(run, library)
        for p, apex in zip(report.components, (0.0, 0.6)):
            p.apex_seconds = apex
        for q, apex in zip(truth, (0.4, 1.3)):
            q["apex_seconds"] = apex
        metrics = detection_metrics(report, truth)
        self.assertEqual(
            metrics["matched"], 2
        )  # A nearest-pair-first greedy pass matches only one.
        self.assertEqual(metrics["uniquely_assessable_matches"], 0)
        self.assertTrue(
            all(
                m["relative_area_error"] is None and m["top_group_contains_expected_name"] is None
                for m in metrics["matches"]
            )
        )

    def test_stress_cases_retain_failures_and_missing_reference_behavior(self):
        result = stress_evaluation()
        self.assertEqual(result["case_count"], 48)
        for case in result["cases"]:
            metrics = case["metrics"]
            if case["scenario"].startswith("separation-0-ratio"):
                self.assertEqual((metrics["detected"], metrics["missed"]), (1, 1))
                self.assertEqual(metrics["uniquely_assessable_matches"], 0)
            elif case["scenario"] == "similar-wrong-reference":
                self.assertEqual(metrics["wrong_tentative_matches"], 1)
            elif case["scenario"] == "missing-reference":
                self.assertEqual(case["statuses"].get("unassigned"), 1)
            elif case["scenario"] == "noisy-blank":
                self.assertEqual(metrics["detected"], 0)

    def test_isolated_peaks_have_correct_positions_identity_and_area(self):
        run, library, truth = synthetic_case()
        report = analyze(run, library)
        metrics = detection_metrics(report, truth)
        self.assertEqual((metrics["precision"], metrics["recall"]), (1, 1))
        for item in metrics["matches"]:
            self.assertLessEqual(item["apex_error_seconds"], 0.2)
            self.assertLess(item["relative_area_error"], 0.05)
            self.assertTrue(item["top_group_contains_expected_name"])
        self.assertAlmostEqual(sum(p.area_percent for p in report.components), 100)

    def test_overlap_retains_two_components_and_blank_has_no_detections(self):
        for kind, expected in (("overlap", 2), ("blank", 0)):
            with self.subTest(kind=kind):
                run, library, truth = synthetic_case(kind)
                report = analyze(run, library)
                metrics = detection_metrics(report, truth)
                self.assertEqual(metrics["matched"], expected)
                self.assertEqual(metrics["false_detections"], 0)
                self.assertTrue(
                    all(m["top_group_contains_expected_name"] for m in metrics["matches"])
                )

    def test_duplicates_are_ambiguous_and_missing_reference_is_unassigned(self):
        run, library, _ = synthetic_case()
        library.identities[0].append(
            Identity(entry_id="conflict", name="Conflicting identity", cas="1-11-1")
        )
        report = analyze(run, library)
        self.assertEqual(report.components[0].status, "ambiguous")
        self.assertEqual(len(report.components[0].candidates[0].identities), 2)
        library.identities = library.identities[1:]
        library.spectra = library.spectra[1:]
        report = analyze(run, library)
        self.assertEqual(report.components[0].status, "unassigned")

    def test_matching_is_scale_invariant_and_handles_zero_spectra(self):
        q = np.array([[9.0, 4.0, 1.0], [0.0, 0.0, 0.0]])
        reference = np.array([[90.0, 40.0, 10.0], [1.0, 4.0, 9.0]])
        scores = match_spectra(q, reference)
        self.assertAlmostEqual(scores[0, 0], 1)
        np.testing.assert_allclose(scores, match_spectra(q * 100, reference * 7))
        np.testing.assert_array_equal(scores[1], [0, 0])

    def test_identical_reference_vectors_have_exactly_equal_scores(self):
        rng = np.random.default_rng(7)
        queries = rng.random((333, 281))
        reference = rng.random((812, 281))
        # These positions exercise different BLAS tiles on Linux. Roundoff must
        # not reverse stable library order for indistinguishable references.
        reference[810] = reference[541]
        scores = match_spectra(queries, reference)
        np.testing.assert_array_equal(scores[:, 541], scores[:, 810])
        np.testing.assert_allclose(
            scores[:, 541], match_spectra(queries, reference[541:542])[:, 0]
        )

    def test_sample_scaling_and_repeatability(self):
        run, library, _ = synthetic_case()
        report = analyze(run, library)
        self.assertEqual(report.model_dump_json(), analyze(run, library).model_dump_json())
        run.intensity *= 10
        scaled = analyze(run, library)
        self.assertEqual(
            [p.apex_scan for p in report.components], [p.apex_scan for p in scaled.components]
        )
        np.testing.assert_allclose(
            [p.area * 10 for p in report.components], [p.area for p in scaled.components]
        )

    def test_invalid_axes_values_and_parameters_fail(self):
        for mutation in ("nan", "negative", "times"):
            run, library, _ = synthetic_case()
            if mutation == "nan":
                run.intensity[0, 0] = np.nan
            elif mutation == "negative":
                run.intensity[0, 0] = -1
            else:
                run.time_seconds[10] = run.time_seconds[9]
            with self.assertRaises(ProcessingError):
                analyze(run, library)
        for params in (
            {"noise_multiplier": 0},
            {"baseline_seconds": 20},
            {"noise_multiplier": float("nan")},
        ):
            with self.assertRaises(ValueError):
                Parameters(**params)

    def test_html_escapes_uploaded_names_and_reference_labels(self):
        run, library, _ = synthetic_case()
        run.name = '<script>alert("sample")</script>'
        library.identities[0][0].name = '<img src=x onerror="alert(1)">'
        html = render_report(analyze(run, library))
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn('role="img"', html)


class InputTests(unittest.TestCase):
    @unittest.skipUnless(DEFAULT_LIBRARY, "Set GCMS_LIBRARY to the original reference library")
    def test_library_audit_matches_actual_reference_data(self):
        library = read_library(DEFAULT_LIBRARY)
        self.assertEqual(library.audit["entries"], 957)
        self.assertEqual(library.audit["exact_duplicate_groups"], 112)
        self.assertEqual(library.audit["duplicate_groups_with_different_names"], 79)
        self.assertEqual(library.audit["duplicate_groups_with_different_cas"], 51)

    def test_invalid_library_is_rejected_instead_of_silently_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.msp"
            for peaks in ("43 10; 55", "43 -10; 55 20", "43 10; 55 nan", "43 10"):
                path.write_text("Name: broken\nNum Peaks: 2\n" + peaks)
                with self.assertRaises(ProcessingError):
                    read_library(path)

    def test_unsafe_archives_and_multiple_samples_are_rejected(self):
        symlink = zipfile.ZipInfo("sample.D/data.ms")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases = [
            [("../outside", b"x"), ("sample.D/data.ms", b"x")],
            [("/absolute", b"x"), ("sample.D/data.ms", b"x")],
            [("sample.D\\data.ms", b"x")],
            [("x" * 254 + ".D/data.ms", b"x")],
            [("first.D/data.ms", b"x"), ("second.D/data.ms", b"x")],
            [("sample.D/data.ms", b"x"), ("SAMPLE.D/DATA.MS", b"y")],
            [(symlink, b"../../outside")],
        ]
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as tmp:
                archive = Path(tmp) / "upload.zip"
                archive.write_bytes(make_zip(entries))
                with self.assertRaises(ProcessingError):
                    extract_sample(archive, Path(tmp))

    @unittest.skipUnless(DEFAULT_SAMPLE, "Set GCMS_SAMPLE to the original acquisition")
    def test_truncated_data_is_rejected_before_vendor_decoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.ms"
            path.write_bytes((DEFAULT_SAMPLE / "data.ms").read_bytes()[:900])
            with patch("gcms.io.parse_ms") as decoder, self.assertRaises(ProcessingError):
                read_run(path)
            decoder.assert_not_called()


class PortContractTests(unittest.TestCase):
    def test_bundle_roundtrip_and_comparison_detect_a_changed_stage(self):
        run, library, _ = synthetic_case()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            msp = root / "source.msp"
            msp.write_text(
                "\n\n".join(
                    f"Name: {ids[0].name}\nNum Peaks: {len(peaks)}\n"
                    + "; ".join(f"{m} {i}" for m, i in peaks)
                    for ids, peaks in zip(library.identities, library.spectra)
                )
            )
            library = read_library(msp)
            expected, actual = root / "expected", root / "actual"
            export_bundle(run, library, msp, Parameters(), expected)
            restored, references, params = load_bundle(expected)
            np.testing.assert_array_equal(restored.intensity, run.intensity)
            self.assertEqual(analyze(restored, references, params), analyze(run, library))
            shutil.copytree(expected, actual)
            self.assertTrue(compare_bundles(expected, actual)["equivalent"])
            scores = np.load(actual / "scores.npy")
            scores[0, 0] -= 0.1
            np.save(actual / "scores.npy", scores)
            result = compare_bundles(expected, actual)
            self.assertFalse(result["equivalent"])
            self.assertTrue(any("manifest hash" in d for d in result["differences"]))
            manifest = json.loads((actual / "manifest.json").read_text())
            manifest["arrays"]["scores"]["sha256"] = hashlib.sha256(
                (actual / "scores.npy").read_bytes()
            ).hexdigest()
            (actual / "manifest.json").write_text(json.dumps(manifest))
            self.assertIn(
                "scores: values differ beyond tolerance",
                compare_bundles(expected, actual)["differences"],
            )


@unittest.skipUnless(
    DEFAULT_SAMPLE and DEFAULT_LIBRARY, "Set GCMS_SAMPLE and GCMS_LIBRARY for real-input API checks"
)
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client_context = TestClient(cls.app)
        cls.client = cls.client_context.__enter__()
        cls.sample_zip = make_zip(
            [("renamed.D/DATA.MS", (DEFAULT_SAMPLE / "data.ms").read_bytes())]
        )

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def test_real_sample_api_cli_pipeline_equivalence(self):
        response = self.client.post(
            "/v1/analyze", content=self.sample_zip, headers={"Content-Type": "application/zip"}
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        received = response.json()
        run = read_run(DEFAULT_SAMPLE)
        run.name = "renamed"
        expected = analyze(run, self.app.state.library).model_dump(mode="json")
        self.assertEqual(received, expected)
        self.assertGreater(received["summary"]["component_count"], 0)
        self.assertEqual(received["acquisition"]["scan_count"], 17749)
        self.assertTrue(
            all(0 <= c["score"] <= 1 for p in received["components"] for c in p["candidates"])
        )

    def test_html_upload_and_openapi(self):
        response = self.client.post(
            "/v1/analyze?output=html",
            content=self.sample_zip,
            headers={"Content-Type": "application/zip"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("Inspect spectral evidence", response.text)
        run = read_run(DEFAULT_SAMPLE)
        run.name = "renamed"
        self.assertEqual(response.text, render_report(analyze(run, self.app.state.library)))
        schema = self.client.get("/openapi.json").json()
        endpoint = schema["paths"]["/v1/analyze"]["post"]
        self.assertIn("application/zip", endpoint["requestBody"]["content"])
        self.assertIn("noise_multiplier", [p["name"] for p in endpoint["parameters"]])

    def test_dashboard_and_configured_sample_use_shared_analysis(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn('id="analysis-form"', home.text)
        self.assertIn("/v1/sample", home.text)
        run, library, _ = synthetic_case()
        with (
            patch("gcms.api.read_run", return_value=run),
            patch.object(self.app.state, "library", library),
        ):
            expected = analyze(run, library)
            self.assertEqual(self.client.get("/v1/sample").json(), expected.model_dump(mode="json"))
            html = self.client.get("/v1/sample?output=html")
            self.assertEqual(html.text, render_report(expected))
            self.assertIn('id="component-pagination"', html.text)
            self.assertEqual(
                self.client.get("/v1/sample?review=true").json()["schema_version"], "review-1.0"
            )
            with patch(
                "gcms.api.read_run", side_effect=ProcessingError("missing", "Sample missing")
            ):
                self.assertEqual(self.client.get("/v1/sample").status_code, 422)
            self.assertEqual(self.client.get("/v1/sample").status_code, 200)
        self.assertEqual(self.client.get("/v1/sample?engine=invalid").status_code, 422)
        self.app.state.slot.acquire()
        try:
            busy = self.client.get("/v1/sample")
            self.assertEqual(busy.status_code, 503)
            self.assertEqual(busy.headers["retry-after"], "2")
        finally:
            self.app.state.slot.release()

    def test_client_errors_busy_and_upload_limit(self):
        for url, headers, status, code in [
            ("/v1/analyze", {}, 415, "unsupported_media_type"),
            ("/v1/analyze", {"Content-Type": "application/zip"}, 422, "invalid_zip"),
            (
                "/v1/analyze?noise_multiplier=0",
                {"Content-Type": "application/zip"},
                422,
                "invalid_parameters",
            ),
            ("/v1/analyze?extra=1", {"Content-Type": "application/zip"}, 422, "invalid_parameters"),
        ]:
            response = self.client.post(url, content=b"bad", headers=headers)
            self.assertEqual(
                (response.status_code, response.json()["error"]["code"]), (status, code)
            )
        self.app.state.slot.acquire()
        try:
            response = self.client.post(
                "/v1/analyze", content=b"bad", headers={"Content-Type": "application/zip"}
            )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers["retry-after"], "2")
        finally:
            self.app.state.slot.release()
        with patch("gcms.api.MAX_UPLOAD_BYTES", 2):
            response = self.client.post(
                "/v1/analyze", content=b"bad", headers={"Content-Type": "application/zip"}
            )
            self.assertEqual(response.status_code, 413)
        self.assertEqual(self.client.get("/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
