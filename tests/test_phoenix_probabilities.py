import hashlib
import json
import unittest
from pathlib import Path

from scripts.analyze_phoenix_probabilities import (
    ProbabilityExportError,
    analyze_probability_export,
    analyze_proxy_payload,
    describe_values,
)


class PhoenixProbabilityAnalysisTests(unittest.TestCase):
    def test_committed_instrumentation_matches_receipt_hash(self):
        root = Path(__file__).resolve().parent.parent
        patch = root / "experiments/phoenix/export_probabilities.patch"
        baseline = json.loads(
            (root / "state/phoenix_inference_baseline.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            hashlib.sha256(patch.read_bytes()).hexdigest(),
            baseline["instrumentation"]["patch_sha256"],
        )
        self.assertEqual(baseline["output"]["candidate_count"], 200)
        self.assertEqual(baseline["output"]["output_column_count"], 19)
        self.assertEqual(baseline["output"]["identical_export_runs"], 2)

    def test_probability_export_is_summarized_by_column(self):
        payload = {
            "schema_version": 1,
            "num_actions": 2,
            "candidates": [
                {
                    "post_id": 1,
                    "author_id": 10,
                    "retrieval_score": 0.9,
                    "probabilities_by_column": [0.0, 0.01],
                },
                {
                    "post_id": 2,
                    "author_id": 20,
                    "retrieval_score": 0.8,
                    "probabilities_by_column": [1.0, 0.05],
                },
            ],
        }

        report = analyze_probability_export(payload, input_sha256="abc")

        self.assertEqual(report["candidate_count"], 2)
        self.assertEqual(report["output_column_count"], 2)
        self.assertEqual(report["input_sha256"], "abc")
        self.assertEqual(report["retrieval_score"], {"min": 0.8, "max": 0.9})
        self.assertEqual(report["columns"][0]["median"], 0.5)
        self.assertEqual(
            report["columns"][0]["histogram_counts"], [1, 0, 0, 0, 0, 0, 0, 1]
        )
        self.assertEqual(
            report["columns"][1]["histogram_counts"], [0, 0, 1, 1, 0, 0, 0, 0]
        )

    def test_probability_export_rejects_duplicate_and_out_of_range_values(self):
        duplicate = {
            "schema_version": 1,
            "num_actions": 1,
            "candidates": [
                {
                    "post_id": 1,
                    "retrieval_score": 0.9,
                    "probabilities_by_column": [0.1],
                },
                {
                    "post_id": 1,
                    "retrieval_score": 0.8,
                    "probabilities_by_column": [0.2],
                },
            ],
        }
        with self.assertRaisesRegex(ProbabilityExportError, "duplicate post_id"):
            analyze_probability_export(duplicate)

        duplicate["candidates"][1]["post_id"] = 2
        duplicate["candidates"][1]["probabilities_by_column"] = [1.1]
        with self.assertRaisesRegex(ProbabilityExportError, "outside"):
            analyze_probability_export(duplicate)

    def test_proxy_payload_aggregates_only_public_count_rates(self):
        payload = {
            "fetched_at": "2026-07-30T00:00:00+00:00",
            "sample_source": "example",
            "rows": [
                {
                    "result": {
                        "p_hat": {
                            "favorite": 0.1,
                            "reply": 0.01,
                            "retweet": 0.001,
                        }
                    }
                },
                {
                    "result": {
                        "p_hat": {
                            "favorite": 0.3,
                            "reply": 0.03,
                            "retweet": 0.003,
                        }
                    }
                },
            ],
        }

        report = analyze_proxy_payload(payload)

        self.assertEqual(report["row_count"], 2)
        self.assertAlmostEqual(report["rates"]["favorite"]["mean"], 0.2)
        self.assertAlmostEqual(report["rates"]["reply"]["median"], 0.02)
        self.assertIn("not matched", report["comparability"])

    def test_empty_summary_is_rejected(self):
        with self.assertRaisesRegex(ProbabilityExportError, "empty"):
            describe_values([])


if __name__ == "__main__":
    unittest.main()
