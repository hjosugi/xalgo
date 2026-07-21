import unittest
from unittest.mock import patch

import requests

from scripts import track_upstream


class TrackUpstreamTests(unittest.TestCase):
    def test_algorithm_file_classification_and_signal_lines(self):
        files = [
            {
                "filename": "home-mixer/scorers/ranking_scorer.rs",
                "status": "modified",
                "patch": "@@\n-old_weight = 1\n+new_weight = 2\n",
            },
            {"filename": "CODE_OF_CONDUCT.md", "status": "modified", "patch": "+hello"},
        ]
        result = track_upstream._analyze_files(files)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["path"], files[0]["filename"])
        self.assertEqual(len(result[0]["signal_lines"]), 2)
        self.assertTrue(track_upstream._is_algorithm_path("README.md"))
        self.assertTrue(track_upstream._is_algorithm_path("phoenix/README.md"))
        self.assertTrue(
            track_upstream._is_algorithm_path(
                "phoenix/artifacts/oss-phoenix-artifacts.zip"
            )
        )

    @patch.object(track_upstream, "_get")
    def test_merged_pr_files_are_inspected(self, get):
        get.side_effect = [
            [
                {
                    "number": 12,
                    "title": "Tune ranker",
                    "merged_at": "2026-07-20T00:00:00Z",
                    "html_url": "https://github.com/xai-org/x-algorithm/pull/12",
                }
            ],
            [
                {
                    "filename": "phoenix/recsys_model.py",
                    "status": "modified",
                    "patch": "+attention_mask = mask",
                }
            ],
        ]
        pulls, status = track_upstream.merged_prs("2026-07-19T00:00:00Z")
        self.assertEqual(status, "available")
        self.assertEqual(
            pulls[0]["algorithm_files"][0]["path"], "phoenix/recsys_model.py"
        )

    @patch.object(track_upstream, "_get")
    def test_pr_api_404_falls_back_without_failure(self, get):
        response = requests.Response()
        response.status_code = 404
        get.side_effect = requests.HTTPError(response=response)
        pulls, status = track_upstream.merged_prs("2026-07-19T00:00:00Z")
        self.assertEqual(pulls, [])
        self.assertIn("404", status)


if __name__ == "__main__":
    unittest.main()
