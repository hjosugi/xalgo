import json
import tempfile
import unittest
from pathlib import Path

from scripts.analyze_vqv_threshold import (
    _write_json,
    analyze_thresholds,
    load_backend_observations,
    load_observations,
    summarize_posts,
)
from scripts.audit_backends import _receipt_payload, summarize
from xalgo.fetch import BackendAttempt, PostData


class VqvThresholdAnalysisTests(unittest.TestCase):
    @staticmethod
    def _backend_receipt(started_at: str, video_views: int) -> dict:
        records = [
            {
                "input": "1001",
                "attempts": [
                    BackendAttempt(
                        "fxtwitter",
                        10.0,
                        post=PostData(
                            status_id="1001",
                            views=video_views,
                            has_video=True,
                            video_duration_ms=15_000,
                        ),
                    )
                ],
            },
            {
                "input": "1002",
                "attempts": [
                    BackendAttempt(
                        "fxtwitter",
                        12.0,
                        post=PostData(
                            status_id="1002",
                            views=500,
                            has_video=False,
                        ),
                    )
                ],
            },
        ]
        return _receipt_payload(
            records,
            summarize(records),
            started_at=started_at,
            finished_at=started_at,
            source={"kind": "test"},
        )

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

    def test_backend_receipts_feed_repeated_video_observations(self):
        receipts = [
            self._backend_receipt("2026-07-30T00:00:00+00:00", 100),
            self._backend_receipt("2026-07-30T02:00:00+00:00", 140),
        ]
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for index, receipt in enumerate(receipts):
                path = Path(directory) / f"snapshot-{index}.json"
                path.write_text(json.dumps(receipt), encoding="utf-8")
                paths.append(path)
            observations, metadata = load_backend_observations(paths, "fxtwitter")
            posts = summarize_posts(observations)

        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["post_id"], "1001")
        self.assertEqual(posts[0]["views_per_hour"], 20.0)
        self.assertEqual(metadata["receipt_count"], 2)
        self.assertEqual(metadata["post_count"], 1)
        self.assertEqual(metadata["observation_count"], 2)
        self.assertEqual(
            metadata["receipts"][0]["counts"]["usable_video_observations"], 1
        )

    def test_backend_receipts_require_two_snapshots(self):
        with self.assertRaisesRegex(ValueError, "at least two"):
            load_backend_observations([Path("one.json")], "fxtwitter")

    def test_json_output_refuses_unrequested_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "analysis.json"
            _write_json(path, {"result": 1}, force=False)
            with self.assertRaisesRegex(FileExistsError, "--force"):
                _write_json(path, {"result": 2}, force=False)
            self.assertEqual(json.loads(path.read_text()), {"result": 1})


if __name__ == "__main__":
    unittest.main()
