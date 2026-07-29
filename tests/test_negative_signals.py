import unittest

from scripts.analyze_negative_signals import analyze_sensitivity
from xalgo.fetch import PostData
from xalgo.score import normalization_sums, offset_score, score_post


class NegativeSignalTests(unittest.TestCase):
    def test_offset_matches_upstream_branches(self):
        weights = {"favorite": 1.0, "not_interested": -1.0}
        self.assertEqual(normalization_sums(weights), (1.0, 1.0, 2.0))
        self.assertAlmostEqual(offset_score(0.2, weights, 0.1), 0.3)
        self.assertAlmostEqual(offset_score(-0.2, weights, 0.1), 0.04)
        self.assertEqual(offset_score(-0.2, {}, 0.1), 0.0)

    def test_rate_score_can_apply_negative_offset(self):
        post = PostData(status_id="1", likes=0, views=10)
        result = score_post(
            post,
            {"favorite": 1.0, "not_interested": -1.0},
            "test",
            {"not_interested": 0.2},
            negative_scores_offset=0.1,
        )
        self.assertAlmostEqual(result.breakdown["not_interested"], -0.2)
        self.assertAlmostEqual(result.score, 0.04)

    def test_sensitivity_reports_each_negative_action(self):
        weights = {
            "favorite": 1.0,
            "not_interested": -1.0,
            "block_author": -1.0,
            "mute_author": -1.0,
            "report": -1.0,
            "not_dwelled": -1.0,
        }
        report = analyze_sensitivity(weights, 0.1, [0.0, 0.1], 0.2)
        self.assertEqual(len(report["scenarios"]), 5)
        self.assertAlmostEqual(
            report["all_negative_equal_probability"]["zero_crossing_probability"],
            0.02,
        )


if __name__ == "__main__":
    unittest.main()
