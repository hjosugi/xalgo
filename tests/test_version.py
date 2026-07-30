import unittest

import xalgo


class VersionTests(unittest.TestCase):
    def test_release_version(self):
        self.assertEqual(xalgo.__version__, "0.1.1")


if __name__ == "__main__":
    unittest.main()
