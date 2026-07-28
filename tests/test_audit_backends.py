import unittest

from scripts.audit_backends import summarize
from xalgo.fetch import BackendAttempt, PostData


class AuditBackendsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
