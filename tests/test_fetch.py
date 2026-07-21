import unittest
from unittest.mock import Mock, patch

from xalgo.fetch import _from_vxtwitter, _syndication_token, extract_status_id


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

    @patch("xalgo.fetch.requests.get")
    def test_vxtwitter_uses_status_only_route_to_avoid_stale_username_cache(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "tweetURL": "https://twitter.com/example/status/123",
            "text": "hello",
            "user_screen_name": "example",
            "likes": 10,
            "retweets": 2,
            "replies": 1,
            "views": None,
        }
        get.return_value = response

        post = _from_vxtwitter("123")

        self.assertEqual(get.call_args.args[0], "https://api.vxtwitter.com/status/123")
        self.assertEqual(post.likes, 10)


if __name__ == "__main__":
    unittest.main()
