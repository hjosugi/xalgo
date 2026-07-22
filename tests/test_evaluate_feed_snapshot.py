import csv
import tempfile
import unittest
from pathlib import Path

from scripts import evaluate_feed_snapshot as evaluation


def row(position, post_id, score):
    return evaluation.FeedRow(
        snapshot_id="s1",
        viewer_hash="sha256:test",
        requested_at="2026-07-22T00:00:00+00:00",
        position=position,
        post_id=post_id,
        proxy_score=score,
    )


class FeedSnapshotEvaluationTests(unittest.TestCase):
    def test_perfect_and_reverse_rankings(self):
        perfect = [row(1, "a", 3), row(2, "b", 2), row(3, "c", 1)]
        reverse = [row(1, "a", 1), row(2, "b", 2), row(3, "c", 3)]
        good = evaluation.snapshot_metrics(perfect, [2])
        bad = evaluation.snapshot_metrics(reverse, [2])
        self.assertAlmostEqual(good["metrics"]["spearman"], 1.0)
        self.assertAlmostEqual(good["metrics"]["kendall_tau_b"], 1.0)
        self.assertAlmostEqual(good["metrics"]["ndcg@2"], 1.0)
        self.assertAlmostEqual(bad["metrics"]["spearman"], -1.0)
        self.assertAlmostEqual(bad["metrics"]["kendall_tau_b"], -1.0)

    def test_score_ties_are_supported(self):
        rows = [row(1, "a", 1), row(2, "b", 1), row(3, "c", 0)]
        metrics = evaluation.snapshot_metrics(rows, [10])["metrics"]
        self.assertTrue(math_is_finite(metrics["kendall_tau_b"]))
        self.assertEqual(metrics["top_k_overlap@10"], 1.0)

    def test_sensitive_columns_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=sorted(evaluation.REQUIRED_COLUMNS | {"auth_token"}),
                )
                writer.writeheader()
            with self.assertRaises(evaluation.SnapshotError):
                evaluation.load_rows(path)


def math_is_finite(value):
    return value == value and abs(value) != float("inf")


if __name__ == "__main__":
    unittest.main()
