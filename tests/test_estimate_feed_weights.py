import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts import estimate_feed_weights as estimation


def dataset(prefix: str, authors: str) -> estimation.RankDataset:
    feature_rows = (
        (1, 0.90, 0.10),
        (2, 0.50, 0.00),
        (3, 0.80, 0.30),
        (4, 0.30, 0.00),
        (5, 0.40, 0.20),
        (6, 0.10, 0.10),
    )
    rows = tuple(
        estimation.RankRow(
            snapshot_id=f"{prefix}-snapshot",
            viewer_hash=f"sha256:{prefix}-viewer",
            requested_at="2026-08-26T00:00:00+00:00",
            position=position,
            post_id=f"{prefix}-post-{position}",
            author_hash=f"sha256:{authors}-{position}",
            features=(favorite, report),
        )
        for position, favorite, report in feature_rows
    )
    return estimation.RankDataset(
        path=Path(f"{prefix}.csv"),
        sha256=prefix * 8,
        feature_names=("p_favorite", "p_report"),
        rows=rows,
    )


class FeedWeightEstimationTests(unittest.TestCase):
    def test_example_cli_produces_author_disjoint_receipt(self):
        root = Path(__file__).resolve().parents[1]
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = estimation.main(
                [
                    str(root / "examples" / "weight_estimation.train.example.csv"),
                    "--test-csv",
                    str(root / "examples" / "weight_estimation.test.example.csv"),
                    "--min-train-rows",
                    "6",
                    "--min-test-rows",
                    "6",
                    "--json",
                ]
            )
        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["evaluation_mode"], "author_disjoint_held_out")
        self.assertEqual(report["author_disjoint"]["overlapping_authors"], 0)
        self.assertEqual(report["author_disjoint"]["overlapping_posts"], 0)

    def test_pairwise_fit_recovers_direction_and_ranking(self):
        train = dataset("train", "train-author")
        pairs = estimation.pairwise_differences(train)
        coefficients, optimizer = estimation.fit_pairwise_logistic(pairs)
        metrics = estimation.evaluate_coefficients(train, coefficients)
        self.assertGreater(coefficients[0], 0.0)
        self.assertLess(coefficients[1], 0.0)
        self.assertGreaterEqual(optimizer["pairwise_accuracy"], 0.9)
        self.assertGreaterEqual(metrics["mean_spearman"], 0.9)

    def test_author_disjoint_validation_accepts_separate_hashes(self):
        evidence = estimation.validate_author_disjoint(
            dataset("train", "train-author"),
            dataset("test", "test-author"),
        )
        self.assertEqual(evidence["overlapping_authors"], 0)
        self.assertEqual(evidence["train_unique_authors"], 6)
        self.assertEqual(evidence["test_unique_authors"], 6)

    def test_author_disjoint_validation_rejects_overlap(self):
        with self.assertRaisesRegex(estimation.SnapshotError, "overlap"):
            estimation.validate_author_disjoint(
                dataset("train", "same-author"),
                dataset("test", "same-author"),
            )

    def test_loader_rejects_unhashed_author_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=sorted(estimation.REQUIRED_COLUMNS | {"p_favorite"}),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "snapshot_id": "s1",
                        "viewer_hash": "sha256:" + "a" * 64,
                        "requested_at": "2026-08-26T00:00:00+00:00",
                        "position": 1,
                        "post_id": "1",
                        "author_hash": "raw-handle",
                        "p_favorite": 0.5,
                    }
                )
            with self.assertRaisesRegex(estimation.SnapshotError, "author_hash"):
                estimation.load_dataset(path, 3)

    def test_tied_predictions_are_json_safe(self):
        report = estimation.evaluate_coefficients(
            dataset("test", "authors"), [0.0, 0.0]
        )
        self.assertIsNone(report["mean_spearman"])
        self.assertIsNone(report["mean_kendall_tau_b"])
        json.dumps(report, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
