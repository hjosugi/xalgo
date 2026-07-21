import unittest

from xalgo.fetch import _syndication_token, extract_status_id


class FetchTests(unittest.TestCase):
    def test_extracts_supported_urls_and_bare_id(self):
        status_id = "2079205509727478218"
        self.assertEqual(extract_status_id(status_id), status_id)
        self.assertEqual(
            extract_status_id(f"https://x.com/example/status/{status_id}?s=20"),
            status_id,
        )
        self.assertEqual(
            extract_status_id(f"https://twitter.com/example/statuses/{status_id}"),
            status_id,
        )

    def test_rejects_non_post_url(self):
        with self.assertRaises(ValueError):
            extract_status_id("https://x.com/example")

    def test_syndication_token_is_stable(self):
        self.assertEqual(_syndication_token("2079205509727478218"), "51g")


if __name__ == "__main__":
    unittest.main()
