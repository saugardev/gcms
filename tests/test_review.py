"""Stability must preserve uncertainty, numerical evidence and engine equivalence."""

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from gcms.api import create_app
from gcms.benchmark import _compare_json, compare_reviews, write_json
from gcms.evaluation import synthetic_case
from gcms.io import DEFAULT_LIBRARY, DEFAULT_SAMPLE, read_library, read_run
from gcms.models import Parameters, ProcessingError
from gcms.pipeline import analyze
from gcms.report import render_report
from gcms.review import build_review, eligible_matches, observations, peak_trace, write_review_csv
from gcms.rust_backend import native


class ReviewTests(unittest.TestCase):
    def test_known_peaks_and_plot_integrals(self):
        run, library, _ = synthetic_case()
        review = build_review(run, library)
        self.assertEqual(review.summary["labels"], {"consistent": 2})
        self.assertEqual(len(set(review.review_packet)), 2)
        for p in review.analysis.components:
            a = review.annotations[p.component_id]
            self.assertEqual((a.matched_profiles, a.same_top_group_profiles), (6, 6))
            self.assertEqual(a.match_fraction, 1)
            trace = a.trace
            self.assertFalse(trace.preview)
            self.assertLessEqual(len(trace.ions), 5)
            t = np.asarray(trace.time_seconds)
            mask = (t >= p.start_seconds) & (t <= p.end_seconds)
            area = np.trapezoid(np.asarray(trace.component_ion_sum)[mask], x=t[mask])
            self.assertAlmostEqual(area, p.area)
            self.assertTrue({p.start_seconds, p.apex_seconds, p.end_seconds} <= set(t))

    def test_competing_missing_and_changed_matches_stay_distinct(self):
        run, library, _ = synthetic_case()
        base = analyze(run, library)
        other = base.model_copy(deep=True)
        other.components.append(other.components[0].model_copy(deep=True))
        rows, unmatched = observations(base, other, run.mz, "split", "python")
        self.assertEqual(
            (rows[0].outcome, rows[0].eligible_components, unmatched), ("ambiguous", 2, 2)
        )
        rows, _ = observations(other, base, run.mz, "merge", "python")
        self.assertEqual([r.outcome for r in rows], ["ambiguous", "matched", "ambiguous"])
        other = base.model_copy(deep=True)
        other.components[0].apex_seconds += 3
        other.components[1].candidates[0].group_id = "changed"
        rows, _ = observations(base, other, run.mz, "changed", "python")
        self.assertEqual(rows[0].outcome, "not_matched")
        self.assertIsNone(rows[0].area)
        self.assertEqual(rows[1].outcome, "matched")
        self.assertFalse(rows[1].same_top_group)

    def test_skipped_failed_and_blank_profiles_do_not_claim_consistency(self):
        run, library, _ = synthetic_case()
        review = build_review(
            run, library, Parameters(smoothing_seconds=0, coapex_seconds=0, noise_multiplier=3)
        )
        self.assertEqual(review.summary["completed_alternative_profiles"], 1)
        self.assertEqual(review.summary["labels"], {"inconclusive": 2})
        self.assertTrue(all(len(a.observations) == 6 for a in review.annotations.values()))
        self.assertIn("Outside allowed", review.variants[1].reason)
        self.assertIn("Duplicates", review.variants[3].reason)

        def fail_one(run, library, params, **kwargs):
            if params.noise_multiplier == 6:
                raise ProcessingError("test_failure", "Deliberate profile failure")
            return analyze(run, library, params, **kwargs)

        with patch("gcms.review.analyze", side_effect=fail_one):
            review = build_review(run, library)
        self.assertEqual(review.variants[1].state, "failed")
        self.assertEqual(review.summary["labels"], {"inconclusive": 2})
        self.assertTrue(all(a.evaluated_profiles == 5 for a in review.annotations.values()))
        run, library, _ = synthetic_case("blank")
        review = build_review(run, library)
        self.assertEqual((review.annotations, review.review_packet), ({}, []))
        self.assertIn(
            "No components passed", render_report(review.analysis, review=review, packet_only=True)
        )

    def test_bounded_preview_retains_apex_bounds_and_endpoints(self):
        run, library, _ = synthetic_case()
        arrays = {}
        report = analyze(run, library, arrays=arrays)
        p = report.components[0].model_copy(update={"start_seconds": 0.0, "end_seconds": 99.9})
        trace = peak_trace(
            run, arrays["corrected"], run.intensity.sum(axis=1), arrays["corrected"].sum(axis=1), p
        )
        self.assertTrue(trace.preview)
        self.assertLessEqual(len(trace.time_seconds), 400)
        self.assertTrue(
            {run.time_seconds[0], run.time_seconds[-1], p.apex_seconds} <= set(trace.time_seconds)
        )
        self.assertTrue(
            all(
                len(v) == len(trace.time_seconds)
                for v in (trace.raw_tic, trace.corrected_tic, trace.component_ion_sum)
            )
        )
        run.time_seconds, run.intensity = run.time_seconds[:7], run.intensity[:7]
        review = build_review(run, library)
        self.assertEqual(review.review_packet, [])

    def test_review_exports_escape_names_and_comparison_detects_changes(self):
        run, library, _ = synthetic_case()
        library.identities[0][0].name = '=1+1<script>alert("x")</script>'
        review = build_review(run, library)
        html = render_report(review.analysis, review=review, packet_only=True)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert", html)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_review_csv(root / "packet.csv", review)
            with (root / "packet.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertTrue(rows[0]["candidate_names"].startswith("'=1+1"))
            self.assertTrue(
                all(
                    r["review_status"] == "unreviewed"
                    and r["analyst_identity"] == r["reviewer"] == r["notes"] == ""
                    for r in rows
                )
            )
            expected, actual = root / "python.json", root / "rust.json"
            write_json(expected, review.model_dump(mode="json"))
            write_json(actual, review.model_dump(mode="json"))
            self.assertTrue(compare_reviews(expected, actual)["equivalent"])
            review.annotations[review.review_packet[0]].label = "sensitive"
            write_json(actual, review.model_dump(mode="json"))
            self.assertFalse(compare_reviews(expected, actual)["equivalent"])

    def test_api_review_transport_and_schema(self):
        run, library, _ = synthetic_case()
        app = create_app()
        with (
            patch("gcms.api.DEFAULT_LIBRARY", Path("synthetic.msp")),
            patch("gcms.api.read_library", return_value=library),
            TestClient(app) as client,
            patch("gcms.api.extract_sample"),
            patch("gcms.api.read_run", return_value=run),
        ):
            app.state.library = library
            expected = build_review(run, library)
            for output in ("json", "html"):
                response = client.post(
                    f"/v1/analyze?review=true&engine=python&output={output}",
                    content=b"mock archive",
                    headers={"Content-Type": "application/zip"},
                )
                self.assertEqual(response.status_code, 200, response.text[:200])
                if output == "json":
                    self.assertEqual(response.json(), expected.model_dump(mode="json"))
                else:
                    self.assertEqual(
                        response.text, render_report(expected.analysis, review=expected)
                    )
            self.assertEqual(client.post("/v1/analyze?engine=invalid").status_code, 422)
            schema = client.get("/openapi.json").json()["paths"]["/v1/analyze"]["post"]
            self.assertTrue({"engine", "review"} <= {p["name"] for p in schema["parameters"]})
            self.assertEqual(
                len(schema["responses"]["200"]["content"]["application/json"]["schema"]["anyOf"]), 2
            )


class ReviewRustTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.core = native()
        except ProcessingError as exc:
            raise unittest.SkipTest("Build the optional Rust extension for parity checks") from exc

    def test_correspondence_boundaries_empty_spectra_and_native_validation(self):
        at, bt = np.array([1.0, 2.0, 3.0]), np.array([1.75, 2.76, 3.0])
        a = np.array([[9.0, 4.0, 1.0], [9.0, 4.0, 1.0], [0.0, 0.0, 0.0]])
        b = a.copy()
        for times, spectra in ((bt, b), (np.zeros(0), np.zeros((0, 3)))):
            expected = eligible_matches(at, a, times, spectra)
            actual = eligible_matches(at, a, times, spectra, "rust")
            self.assertEqual(
                [[j for j, _ in row] for row in actual], [[j for j, _ in row] for row in expected]
            )
            np.testing.assert_allclose(
                [s for row in actual for _, s in row],
                [s for row in expected for _, s in row],
                rtol=1e-6,
                atol=1e-8,
            )
        self.assertEqual(eligible_matches(at, a, bt, b, "rust")[2], [])
        for invalid in (a[:, :2], a * np.nan, -a):
            with self.assertRaises(ValueError):
                self.core.correspondences(at, invalid, bt, b, 0.75, 0.8)

    def test_complete_reviews_agree(self):
        cases = [synthetic_case()[:2]]
        if DEFAULT_SAMPLE and DEFAULT_LIBRARY:
            cases.append((read_run(DEFAULT_SAMPLE), read_library(DEFAULT_LIBRARY)))
        for run, library in cases:
            expected = build_review(run, library).model_dump(mode="json")
            actual = build_review(run, library, engine="rust").model_dump(mode="json")
            for report in (expected, actual):
                report["analysis"]["provenance"].pop("software")
            differences = []
            _compare_json(expected, actual, "review", differences)
            self.assertEqual(differences[:20], [])


if __name__ == "__main__":
    unittest.main()
