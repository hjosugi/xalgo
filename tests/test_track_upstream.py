import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from scripts import track_upstream

ROOT = Path(__file__).resolve().parent.parent


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
        self.assertEqual(
            track_upstream._classify_path("grox/classifiers/content/spam.py"),
            "policy",
        )
        self.assertEqual(
            track_upstream._classify_path("grox/data_loaders/kafka_loader.py"),
            "unrelated",
        )
        self.assertEqual(
            track_upstream._classify_path("home-mixer/params/param.rs"),
            "ranking",
        )
        self.assertEqual(
            track_upstream._classify_path("phoenix/xrex/models/recsys_model.py"),
            "ranking",
        )
        self.assertEqual(
            track_upstream._classify_path("visibility-filtering/src/lib.rs"),
            "policy",
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

    def test_reviewed_corpus_has_no_classification_regression(self):
        result = track_upstream.evaluate_corpus(
            ROOT / "state" / "upstream_tracking_corpus.json"
        )
        self.assertEqual(result["cases"], 33)
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["category_accuracy"], 1.0)
        self.assertEqual(result["errors"], [])

    def test_python_ast_diff_tracks_weights_actions_and_formula(self):
        before = """
FAVORITE_WEIGHT = 1.0
ACTIONS = ["favorite"]
score_cache: dict[str, float]
def score_candidate(value):
    return value * FAVORITE_WEIGHT
"""
        after = """
FAVORITE_WEIGHT = 2.0
REPLY_WEIGHT = 0.5
ACTIONS = ["favorite", "reply"]
score_cache: dict[str, float]
def score_candidate(value):
    return value * FAVORITE_WEIGHT + REPLY_WEIGHT
"""
        changes = track_upstream.diff_source_structure(
            "phoenix/ranker.py", before, after
        )
        self.assertIn("assignments", changes)
        self.assertIn("reply", changes["actions"]["added"])
        self.assertTrue(changes["formulas"]["added"])

    def test_rust_structure_diff_tracks_constants_and_action_fields(self):
        before = """
const FAVORITE_WEIGHT: f64 = 1.0;
struct ScoringWeights {
    favorite: f64,
}
fn compute_score() -> f64 { FAVORITE_WEIGHT }
"""
        after = """
const FAVORITE_WEIGHT: f64 = 2.0;
const REPLY_WEIGHT: f64 = 0.5;
struct ScoringWeights {
    favorite: f64,
    reply: f64,
}
fn compute_score() -> f64 { FAVORITE_WEIGHT + REPLY_WEIGHT }
"""
        changes = track_upstream.diff_source_structure(
            "home-mixer/scorers/ranking_scorer.rs", before, after
        )
        self.assertIn("assignments", changes)
        self.assertIn("reply", changes["actions"]["added"])
        self.assertTrue(changes["formulas"]["added"])

    def test_rust_function_arguments_are_not_reported_as_struct_fields(self):
        source = """
fn filter(
    candidates: &[PostCandidate],
) -> Vec<Result<PostCandidate, String>> {
    candidates.to_vec()
}
"""
        structure = track_upstream.extract_source_structure("filter.rs", source)
        self.assertEqual(structure["fields"], set())
        self.assertNotIn(
            ") -> Vec<Result<PostCandidate, String>> {",
            structure["formulas"],
        )

    def test_merge_commit_is_not_reported_twice_as_pr(self):
        sha = "a" * 40
        commits = [{"full_sha": sha}]
        pull_requests = [
            {"number": 1, "merge_commit_sha": sha},
            {"number": 2, "merge_commit_sha": "b" * 40},
        ]
        kept, duplicates = track_upstream._deduplicate_pull_requests(
            commits, pull_requests
        )
        self.assertEqual([item["number"] for item in kept], [2])
        self.assertEqual([item["number"] for item in duplicates], [1])


if __name__ == "__main__":
    unittest.main()
