import math
import unittest

from scripts.validate_popular import spearman


class ValidationTests(unittest.TestCase):
    def test_spearman_handles_ties_with_average_ranks(self):
        self.assertAlmostEqual(spearman([1, 1, 2], [1, 2, 3]), math.sqrt(3) / 2)

    def test_spearman_rejects_too_small_or_mismatched_samples(self):
        self.assertTrue(math.isnan(spearman([1, 2], [1, 2])))
        self.assertTrue(math.isnan(spearman([1, 2, 3], [1, 2])))


if __name__ == "__main__":
    unittest.main()
