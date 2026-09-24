import json
import math
import unittest
from pathlib import Path

from xalgo.fetch import PostData
from xalgo.score import (
    author_diversity_multiplier,
    load_weights,
    normalization_sums,
    offset_score,
    preset_settings,
    score_post,
    unoffset_score,
    vqv_weight_eligibility,
)


class ScoreTests(unittest.TestCase):
    def test_public_september_defaults_are_the_default_preset(self):
        weights_path = Path(__file__).resolve().parents[1] / "weights.json"
        name, weights, cfg = load_weights(weights_path)
        settings = preset_settings(cfg, name)
        self.assertEqual(name, "upstream_2026_09")
        self.assertEqual(weights["reply"], 5.0)
        self.assertEqual(weights["report"], -234.0)
        # The three defaults that moved between the August and September source.
        self.assertEqual(weights["vqv"], 0.0)
        self.assertEqual(weights["dwell"], 0.05)
        self.assertEqual(weights["video_open"], 0.07)
        self.assertEqual(settings["vqv_min_duration_ms"], 10_000)
        self.assertEqual(settings["negative_scores_offset"], 0.001)
        self.assertEqual(
            settings["author_diversity"],
            {
                "enabled": True,
                "decay": 0.5,
                "floor": 0.25,
            },
        )

    def test_default_preset_matches_recorded_model_contract(self):
        # The default preset is the recorded upstream contract: same source
        # ref, same 26 weights and the same public OON / new-user settings.
        root = Path(__file__).resolve().parents[1]
        name, weights, cfg = load_weights(root / "weights.json")
        settings = preset_settings(cfg, name)
        baseline = json.loads(
            (root / "state" / "model_contract_baseline.json").read_text(
                encoding="utf-8"
            )
        )
        contract = baseline["contract"]
        self.assertEqual(settings["source_ref"], baseline["source_ref"])
        self.assertEqual(weights, contract["ranking_weights"])
        for key in (
            "oon_weight_factor",
            "topic_oon_weight_factor",
            "new_user_oon_weight_factor",
            "new_user_age_threshold_secs",
        ):
            self.assertEqual(settings[key], contract["ranking_settings"][key], key)
        self.assertEqual(
            settings["negative_scores_offset"],
            contract["scoring_constants"]["negative_scores_offset"],
        )

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

    def test_current_normalization_includes_new_source_heads(self):
        positive, negative, total = normalization_sums(
            {
                "video_open": 0.05,
                "open_link": 0.2,
                "post_unexplored": 0.02,
                "report": -234.0,
            }
        )
        self.assertAlmostEqual(positive, 0.27)
        self.assertEqual(negative, 234.0)
        self.assertAlmostEqual(total, 234.27)

    def test_unoffset_inverts_offset_for_public_defaults(self):
        # Upstream 1b3fec20bc derives the MultiplierPreOffset net score from
        # the offset weighted score; with the public weights the round trip
        # must return the original net score on both sides of zero.
        weights_path = Path(__file__).resolve().parents[1] / "weights.json"
        name, weights, cfg = load_weights(weights_path)
        offset = preset_settings(cfg, name)["negative_scores_offset"]
        for net in (-250.0, -3.5, -1e-9, 0.0, 1e-9, 0.42, 12.0):
            weighted = offset_score(net, weights, offset)
            self.assertAlmostEqual(
                unoffset_score(weighted, weights, offset), net, places=9
            )

    def test_unoffset_branches_on_the_offset_not_on_zero(self):
        weights = {"favorite": 1.0, "report": -3.0}
        # total_sum = 4, negative_sum = 3: offset maps [-3, 0) onto [0, 0.001).
        self.assertAlmostEqual(unoffset_score(0.0, weights, 0.001), -3.0)
        self.assertAlmostEqual(unoffset_score(0.0005, weights, 0.001), -1.0)
        self.assertAlmostEqual(unoffset_score(0.001, weights, 0.001), 0.0)
        self.assertAlmostEqual(unoffset_score(0.501, weights, 0.001), 0.5)

    def test_unoffset_is_identity_when_total_sum_is_zero(self):
        weights = {"favorite": 0.0, "report": 0.0}
        self.assertEqual(unoffset_score(0.7, weights, 0.001), 0.7)
        self.assertEqual(offset_score(-2.0, weights, 0.001), 0.0)
        self.assertEqual(
            unoffset_score(offset_score(-2.0, weights, 0.001), weights, 0.001), 0.0
        )

    def test_unoffset_rejects_non_positive_offset(self):
        with self.assertRaises(ValueError):
            unoffset_score(0.5, {"favorite": 1.0}, 0.0)
        with self.assertRaises(ValueError):
            unoffset_score(math.nan, {"favorite": 1.0}, 0.001)

    def test_vqv_duration_gate_is_strict(self):
        self.assertEqual(vqv_weight_eligibility(None, 10_000, 2.0), 0.0)
        self.assertEqual(vqv_weight_eligibility(10_000, 10_000, 2.0), 0.0)
        self.assertEqual(vqv_weight_eligibility(10_001, 10_000, 2.0), 2.0)
        with self.assertRaises(ValueError):
            vqv_weight_eligibility(10_000, -1, 2.0)

    def test_vqv_probability_respects_hypothetical_duration_gate(self):
        weights = {"favorite": 1.0, "vqv": 2.0}
        boundary = score_post(
            PostData(
                status_id="1",
                likes=0,
                views=100,
                has_video=True,
                video_duration_ms=10_000,
            ),
            weights,
            "test",
            {"vqv": 0.25},
            vqv_min_duration_ms=10_000,
        )
        eligible = score_post(
            PostData(
                status_id="2",
                likes=0,
                views=100,
                has_video=True,
                video_duration_ms=10_001,
            ),
            weights,
            "test",
            {"vqv": 0.25},
            vqv_min_duration_ms=10_000,
        )
        self.assertNotIn("vqv", boundary.p_hat)
        self.assertAlmostEqual(boundary.score, 0.0)
        self.assertAlmostEqual(eligible.p_hat["vqv"], 0.25)
        self.assertAlmostEqual(eligible.score, 0.5)
        self.assertTrue(any("hypothetical" in item for item in eligible.warnings))

    def test_historical_and_demo_presets_are_labeled(self):
        post = PostData(status_id="1", likes=1, views=10)
        demo = score_post(post, {"favorite": 1.0}, "repo_demo")
        legacy = score_post(post, {"favorite": 0.5}, "legacy_2023")
        self.assertTrue(
            any("not a verified Phoenix score" in item for item in demo.warnings)
        )
        self.assertTrue(any("2023-04-05" in item for item in legacy.warnings))

    def test_public_preset_is_labeled_as_defaults_not_live_configuration(self):
        post = PostData(status_id="1", likes=10, views=100)
        for preset in ("upstream_2026_09", "upstream_2026_08"):
            result = score_post(
                post,
                {"favorite": 0.5},
                preset,
                negative_scores_offset=0.001,
            )
            self.assertAlmostEqual(result.score, 0.051)
            self.assertTrue(
                any("live request configuration" in item for item in result.warnings)
            )

    def test_august_preset_is_retained_with_its_own_defaults(self):
        weights_path = Path(__file__).resolve().parents[1] / "weights.json"
        name, weights, cfg = load_weights(weights_path, "upstream_2026_08")
        self.assertEqual(name, "upstream_2026_08")
        self.assertEqual(weights["vqv"], 0.05)
        self.assertEqual(weights["dwell"], 0.0)
        self.assertEqual(weights["video_open"], 0.05)
        self.assertEqual(
            preset_settings(cfg, name)["source_ref"],
            "d011592a1c8c4bfb23781ff15577a68dc08bdde1",
        )


if __name__ == "__main__":
    unittest.main()
