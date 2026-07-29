import unittest

from scripts.simulate_author_diversity import simulate_case, simulate_grid


class AuthorDiversitySimulationTests(unittest.TestCase):
    def test_repeated_author_post_sinks_below_competitor(self):
        result = simulate_case(
            author_scores=[1.0, 0.99],
            competitor_scores=[0.95],
            decay=0.5,
            floor=0.0,
            top_k=2,
        )
        first, second = result["target_posts"]
        self.assertEqual(first["burst_rank"], 1)
        self.assertEqual(second["raw_rank"], 2)
        self.assertEqual(second["burst_rank"], 3)
        self.assertEqual(second["distributed_rank"], 1)
        self.assertAlmostEqual(second["multiplier"], 0.5)
        self.assertAlmostEqual(second["break_even_score_uplift"], 1.0)

    def test_grid_covers_cartesian_product(self):
        results = simulate_grid(
            author_scores=[1.0],
            competitor_scores=[0.9],
            decays=[0.5, 0.9],
            floors=[0.0, 0.2, 0.4],
            top_k=1,
        )
        self.assertEqual(len(results), 6)
        self.assertTrue(all(case["burst_top_k"] == 1 for case in results))

    def test_zero_multiplier_reports_unbounded_break_even(self):
        result = simulate_case(
            author_scores=[1.0, 0.9],
            competitor_scores=[0.8],
            decay=0.0,
            floor=0.0,
            top_k=2,
        )
        self.assertIsNone(result["target_posts"][1]["break_even_score_uplift"])
        self.assertTrue(result["has_unbounded_break_even_uplift"])


if __name__ == "__main__":
    unittest.main()
