import json
import tempfile
import unittest
from pathlib import Path

from scripts.analyze_backend_snapshots import (
    SnapshotError,
    aggregate_snapshots,
    load_snapshot,
)
from scripts.audit_backends import _receipt_payload, summarize
from xalgo.fetch import BackendAttempt, PostData


class AuditBackendsTests(unittest.TestCase):
    @staticmethod
    def _snapshot(started_at: str, *, reverse: bool = False) -> dict:
        records = []
        status_ids = [str(1_000 + index) for index in range(100)]
        if reverse:
            status_ids.reverse()
        for index, status_id in enumerate(status_ids):
            day = 28 + (index % 3)
            post = PostData(
                status_id=status_id,
                created_at=f"Wed Jul {day} 00:00:00 +0000 2026",
                likes=index,
                retweets=index // 2,
                replies=index // 3,
                views=1_000 + index,
                has_video=index % 2 == 0,
            )
            attempts = [
                BackendAttempt("fxtwitter", 100.0 + index, post=post),
                (
                    BackendAttempt("vxtwitter", 200.0 + index, post=post)
                    if index % 5
                    else BackendAttempt("vxtwitter", 250.0, error="HTTPError: 500")
                ),
                BackendAttempt(
                    "syndication",
                    150.0 + index,
                    post=PostData(
                        status_id=status_id,
                        likes=index,
                        replies=index // 3,
                        has_video=index % 2 == 0,
                    ),
                ),
            ]
            records.append({"input": status_id, "attempts": attempts})
        return _receipt_payload(
            records,
            summarize(records),
            started_at=started_at,
            finished_at=started_at,
            source={"kind": "test"},
        )

    def test_summary_measures_reliability_coverage_and_deltas(self):
        records = [
            {
                "input": "1",
                "attempts": [
                    BackendAttempt(
                        "alpha",
                        100.0,
                        post=PostData(status_id="1", likes=100, replies=5, views=1000),
                    ),
                    BackendAttempt(
                        "beta",
                        200.0,
                        post=PostData(status_id="1", likes=90, replies=5, views=None),
                    ),
                ],
            },
            {
                "input": "2",
                "attempts": [
                    BackendAttempt("alpha", 150.0, error="timeout"),
                    BackendAttempt(
                        "beta", 300.0, post=PostData(status_id="2", likes=10, views=200)
                    ),
                ],
            },
        ]
        result = summarize(records)
        self.assertEqual(result["backends"]["alpha"]["success_rate"], 0.5)
        self.assertEqual(result["backends"]["beta"]["success_rate"], 1.0)
        self.assertEqual(result["backends"]["alpha"]["field_coverage"]["views"], 1)
        comparison = result["pairwise_consistency"]["alpha__beta__likes"]
        self.assertAlmostEqual(comparison["mean_relative_delta"], 0.1)
        self.assertEqual(result["sample_based_recommended_order"][0], "beta")

    def test_receipt_excludes_post_text_author_and_urls(self):
        record = {
            "input": "123",
            "attempts": [
                BackendAttempt(
                    "alpha",
                    100.0,
                    post=PostData(
                        status_id="123",
                        url="https://example.invalid",
                        text="not retained",
                        author="not-retained",
                        likes=5,
                        views=10,
                    ),
                ),
                BackendAttempt("beta", 200.0, error="HTTPError: secret-looking URL"),
            ],
        }

        receipt = _receipt_payload(
            [record],
            summarize([record]),
            started_at="2026-07-30T00:00:00+00:00",
            finished_at="2026-07-30T00:00:01+00:00",
        )

        post = receipt["records"][0]["attempts"][0]["post"]
        self.assertNotIn("text", post)
        self.assertNotIn("author", post)
        self.assertNotIn("url", post)
        self.assertEqual(
            receipt["records"][0]["attempts"][1]["error_class"], "HTTPError"
        )
        self.assertIn("credentials are excluded", receipt["privacy"])

    def test_three_hourly_snapshots_meet_completion_gate(self):
        snapshots = [
            self._snapshot("2026-07-30T00:00:00+00:00"),
            self._snapshot("2026-07-30T08:00:00+00:00"),
            self._snapshot("2026-07-30T16:00:00+00:00"),
        ]

        report = aggregate_snapshots(snapshots)

        self.assertTrue(report["completion_criteria"]["met"])
        self.assertEqual(report["snapshots"]["count"], 3)
        self.assertEqual(len(report["snapshots"]["distinct_utc_hours"]), 3)
        self.assertEqual(report["backends"]["vxtwitter"]["success_rate"], 0.8)
        self.assertEqual(
            report["recommendation"]["aggregate_order"],
            ["fxtwitter", "syndication", "vxtwitter"],
        )
        self.assertEqual(report["recommendation"]["timeout"]["recommended_seconds"], 5)
        self.assertEqual(
            report["recommendation"]["timeout"]["timeout_failure_count"], 0
        )

    def test_mismatched_cohorts_are_rejected(self):
        with self.assertRaisesRegex(SnapshotError, "same ordered cohort"):
            aggregate_snapshots(
                [
                    self._snapshot("2026-07-30T00:00:00+00:00"),
                    self._snapshot("2026-07-30T08:00:00+00:00", reverse=True),
                ]
            )

    def test_timeout_failure_prevents_timeout_reduction(self):
        snapshots = [
            self._snapshot("2026-07-30T00:00:00+00:00"),
            self._snapshot("2026-07-30T08:00:00+00:00"),
            self._snapshot("2026-07-30T16:00:00+00:00"),
        ]
        attempt = snapshots[0]["records"][0]["attempts"][0]
        attempt.update(
            {
                "elapsed_ms": 12_000.0,
                "ok": False,
                "error_class": "ReadTimeout",
                "post": None,
            }
        )

        report = aggregate_snapshots(snapshots)

        timeout = report["recommendation"]["timeout"]
        self.assertEqual(timeout["timeout_failure_count"], 1)
        self.assertEqual(timeout["recommended_seconds"], 12)
        self.assertEqual(timeout["decision"], "retain 12s timeout")

    def test_snapshot_loader_detects_tampered_cohort_hash(self):
        snapshot = self._snapshot("2026-07-30T00:00:00+00:00")
        snapshot["cohort"]["ordered_status_ids_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaisesRegex(SnapshotError, "cohort hash"):
                load_snapshot(path)


if __name__ == "__main__":
    unittest.main()
