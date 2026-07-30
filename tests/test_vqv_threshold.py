import tempfile
import unittest
from pathlib import Path

from scripts.analyze_vqv_threshold import (
    analyze_thresholds,
    load_observations,
    summarize_posts,
)


class VqvThresholdAnalysisTests(unittest.TestCase):
    def test_threshold_split_uses_strict_greater_than(self):
        posts = [
            {"post_id": "a", "video_duration_ms": 10_000, "views_per_hour": 10.0},
            {"post_id": "b", "video_duration_ms": 10_001, "views_per_hour": 30.0},
        ]
        report = analyze_thresholds(
            durations_ms=[],
            thresholds_ms=[10_000],
            vqv_probability=0.25,
            vqv_weight=2.0,
            posts=posts,
        )
        case = report["thresholds"][0]
        self.assertEqual(case["eligible_duration_count"], 1)
        self.assertFalse(case["duration_cases"][0]["eligible"])
        self.assertTrue(case["duration_cases"][1]["eligible"])
        self.assertEqual(case["duration_cases"][1]["vqv_contribution"], 0.5)
        self.assertEqual(
            case["observed_growth"]["mean_difference_views_per_hour"], 20.0
        )

    def test_snapshot_csv_is_summarized_per_post(self):
        csv_text = (
            "post_id,video_duration_ms,observed_at,views\n"
            "a,5000,2026-07-01T00:00:00Z,100\n"
            "a,5000,2026-07-01T02:00:00Z,140\n"
            "b,15000,2026-07-01T00:00:00+00:00,200\n"
            "b,15000,2026-07-01T04:00:00+00:00,320\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.csv"
            path.write_text(csv_text, encoding="utf-8")
            posts = summarize_posts(load_observations(path))

        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0]["views_delta"], 40)
        self.assertEqual(posts[0]["views_per_hour"], 20.0)
        self.assertEqual(posts[1]["views_per_hour"], 30.0)

    def test_snapshot_csv_rejects_credential_columns(self):
        csv_text = (
            "post_id,video_duration_ms,observed_at,views,access_token\n"
            "a,5000,2026-07-01T00:00:00Z,100,secret\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.csv"
            path.write_text(csv_text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "credential-like"):
                load_observations(path)


if __name__ == "__main__":
    unittest.main()
