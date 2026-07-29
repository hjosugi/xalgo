import unittest

from xalgo.web import build_score_response


class WebScoreTests(unittest.TestCase):
    def test_manual_request_uses_shared_scoring_logic(self):
        response = build_score_response(
            {
                "source": "manual",
                "preset": "repo_demo",
                "post": {
                    "views": 1000,
                    "likes": 100,
                    "replies": 20,
                    "retweets": 10,
                    "quotes": 0,
                },
                "probabilities": {"dwell": 0.3},
                "author_position": 1,
            }
        )
        self.assertEqual(response["result"]["mode"], "rate")
        self.assertAlmostEqual(response["result"]["score"], 0.173)
        self.assertAlmostEqual(response["author_diversity"]["multiplier"], 0.92)

    def test_manual_counts_must_be_whole_numbers(self):
        with self.assertRaises(ValueError):
            build_score_response(
                {
                    "source": "manual",
                    "preset": "repo_demo",
                    "post": {"views": 100, "likes": 1.5},
                }
            )

    def test_probability_validation_is_preserved(self):
        with self.assertRaises(ValueError):
            build_score_response(
                {
                    "source": "manual",
                    "preset": "repo_demo",
                    "post": {"views": 100, "likes": 1},
                    "probabilities": {"dwell": 1.1},
                }
            )

    def test_unknown_source_is_rejected(self):
        with self.assertRaises(ValueError):
            build_score_response({"source": "file", "preset": "repo_demo"})


if __name__ == "__main__":
    unittest.main()
