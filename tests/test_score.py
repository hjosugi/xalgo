import math
import unittest

from xalgo.fetch import PostData
from xalgo.score import author_diversity_multiplier, score_post


class ScoreTests(unittest.TestCase):
    def test_rate_mode_uses_public_counts_over_views(self):
        post = PostData(status_id="1", likes=100, replies=20, retweets=10, views=1000)
        result = score_post(
            post,
            {"favorite": 1.0, "reply": 0.5, "retweet": 0.3, "dwell": 0.2},
            "test",
        )
        self.assertEqual(result.mode, "rate")
        self.assertAlmostEqual(result.score, 0.113)
        self.assertIn("dwell", result.warnings[0])

    def test_raw_mode_is_log_scaled(self):
        post = PostData(status_id="1", likes=9, replies=3, views=None)
        result = score_post(post, {"favorite": 2.0, "reply": 1.0}, "test")
        self.assertEqual(result.mode, "raw")
        self.assertAlmostEqual(result.score, 2 * math.log1p(9) + math.log1p(3))

    def test_injected_probability_is_validated(self):
        post = PostData(status_id="1", likes=1, views=10)
        with self.assertRaises(ValueError):
            score_post(post, {"favorite": 1.0, "dwell": 0.2}, "test", {"dwell": 1.1})
        with self.assertRaises(KeyError):
            score_post(post, {"favorite": 1.0}, "test", {"dwell": 0.2})

    def test_author_diversity_formula(self):
        self.assertEqual(author_diversity_multiplier(0, 0.9, 0.2), 1.0)
        self.assertAlmostEqual(author_diversity_multiplier(1, 0.9, 0.2), 0.92)
        with self.assertRaises(ValueError):
            author_diversity_multiplier(-1, 0.9, 0.2)

    def test_historical_and_demo_presets_are_labeled(self):
        post = PostData(status_id="1", likes=1, views=10)
        demo = score_post(post, {"favorite": 1.0}, "repo_demo")
        legacy = score_post(post, {"favorite": 0.5}, "legacy_2023")
        self.assertTrue(any("not a verified Phoenix score" in item for item in demo.warnings))
        self.assertTrue(any("2023-04-05" in item for item in legacy.warnings))


if __name__ == "__main__":
    unittest.main()
