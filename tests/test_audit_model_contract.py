import io
import zipfile
import unittest

from scripts import audit_model_contract as audit

OFFSET_SOURCE = """
if w.total_sum == 0.0 {
    combined_score.max(0.0)
} else if combined_score < 0.0 {
    (combined_score + w.negative_sum) / w.total_sum * NEGATIVE_SCORES_OFFSET
} else {
    combined_score + NEGATIVE_SCORES_OFFSET
}
"""


class AuditModelContractTests(unittest.TestCase):
    def test_reads_selected_member_from_zip_ranges(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("model/config.json", '{"emb_size": 128}')
            archive.writestr("ignored.bin", b"x" * 100)
        payload = stream.getvalue()

        def read_range(start, end):
            return payload[start : end + 1]

        members, _ = audit.read_zip_directory(read_range, len(payload))
        content, _ = audit.read_zip_member(read_range, members["model/config.json"])
        self.assertEqual(content, b'{"emb_size": 128}')

    def test_parses_readme_claim_conflict(self):
        root = "mini Phoenix model (256-dim embeddings, 4 attention heads, 2 transformer layers)"
        phoenix = "mini version of the Phoenix model (128-dim, 4-layer transformer)"
        claims = audit.parse_readme_claims(root, phoenix)
        self.assertEqual(claims["root_readme"], {"emb_size": 256, "num_layers": 2})
        self.assertEqual(claims["phoenix_readme"], {"emb_size": 128, "num_layers": 4})

    def test_maps_pipeline_indices_to_output_heads(self):
        runners = (
            'ACTIONS: list[str] = ["favorite_score", "reply_score", "repost_score"]'
        )
        pipeline = "IDX_FAV = 1\nIDX_REPLY = 2\n"
        result = audit.parse_action_contract(runners, pipeline)
        mappings = {
            item["constant"]: item for item in result["pipeline_index_mappings"]
        }
        self.assertEqual(mappings["IDX_FAV"]["actual_head_at_index"], "reply_score")
        self.assertFalse(mappings["IDX_FAV"]["matches"])

    def test_structural_diff_identifies_exact_contract_path(self):
        expected = {"architecture": {"layers": 4}, "actions": ["fav", "reply"]}
        actual = {"architecture": {"layers": 6}, "actions": ["fav", "repost"]}
        differences = audit.diff_values(expected, actual)
        self.assertEqual(
            [item["path"] for item in differences],
            ["$.actions[1]", "$.architecture.layers"],
        )

    def test_structural_diff_accepts_unchanged_contract(self):
        contract = {"oid": "abc", "shape": [128, 19], "matches": False}
        self.assertEqual(audit.diff_values(contract, contract), [])

    def test_parses_current_home_mixer_defaults(self):
        source = """
param!(FavoriteWeight, f64, "favorite", 0.5);
param!(
    ReportWeight,
    f64,
    "report",
    -234.0
);
param!(MinVideoDurationMs, i32, "duration", 10_000);
param!(EnableAuthorDiversity, bool, "diversity", true);
"""
        defaults = audit.parse_param_defaults(source)
        self.assertEqual(defaults["FavoriteWeight"], 0.5)
        self.assertEqual(defaults["ReportWeight"], -234.0)
        self.assertEqual(defaults["MinVideoDurationMs"], 10_000)
        self.assertTrue(defaults["EnableAuthorDiversity"])

    def test_parses_current_model_profiles_with_base_dict(self):
        source = """
def _base():
    return {"history_seq_len": 1022, "candidate_seq_len": 64, "emb_size": 2560}

MODEL_CFGS = {
    "nano": _make_cfg({**_base(), "emb_size": 512, "num_layers": 4}),
}
"""
        profiles = audit.parse_model_profiles(source, ("nano",))
        self.assertEqual(
            profiles["nano"],
            {
                "history_seq_len": 1022,
                "candidate_seq_len": 64,
                "num_layers": 4,
                "emb_size": 512,
            },
        )

    def test_parses_rust_integer_constant_expression(self):
        source = "pub const MAX_POST_AGE: u64 = 48 * 60 * 60;"
        self.assertEqual(
            audit.parse_rust_constant(source, "MAX_POST_AGE", "u64"),
            172_800,
        )

    def test_parses_current_scoring_contract(self):
        source = """
let positive_sum = favorite + reply + if enable_multiplicative_post_unexplored {
    0.0
} else {
    post_unexplored
};
let negative_sum = -(not_interested + report);
if w.total_sum == 0.0 {
    combined_score.max(0.0)
} else if combined_score < 0.0 {
    (combined_score + w.negative_sum) / w.total_sum * NEGATIVE_SCORES_OFFSET
} else {
    combined_score + NEGATIVE_SCORES_OFFSET
}
"""
        contract = audit.parse_scoring_contract(source)
        self.assertEqual(
            contract["positive_normalization_actions"],
            ["favorite", "reply", "post_unexplored"],
        )
        self.assertEqual(
            contract["negative_normalization_actions"],
            ["not_interested", "report"],
        )
        self.assertTrue(contract["negative_branch_normalizes"])
        self.assertEqual(contract["term_split"], "by_action_class")
        self.assertFalse(contract["weight_perturbation_supported"])

    def test_parses_september_scoring_contract(self):
        # Since 2026-09-18 the sums live in ``recompute_sums`` (the negative
        # one assigned to ``self``) and weights can be perturbed.  The
        # sign-based term split predates that and is recorded as well.
        source = """
fn recompute_sums(&mut self) {
    let positive_sum = self.favorite
        + self.reply
        + if self.enable_multiplicative_post_unexplored {
            0.0
        } else {
            self.post_unexplored
        };
    self.negative_sum = -(self.not_interested + self.report);
    self.total_sum = positive_sum + self.negative_sum;
}
pub(crate) fn perturbed(mut self, query: &ScoredPostsQuery) -> Self {
    self
}
for t in terms {
    if t >= 0.0 {
        pos += t;
    } else {
        neg -= t;
    }
}
if w.total_sum == 0.0 {
    combined_score.max(0.0)
} else if combined_score < 0.0 {
    (combined_score + w.negative_sum) / w.total_sum * NEGATIVE_SCORES_OFFSET
} else {
    combined_score + NEGATIVE_SCORES_OFFSET
}
"""
        contract = audit.parse_scoring_contract(source)
        self.assertEqual(
            contract["positive_normalization_actions"],
            ["favorite", "reply", "post_unexplored"],
        )
        self.assertEqual(
            contract["negative_normalization_actions"],
            ["not_interested", "report"],
        )
        self.assertTrue(
            contract["multiplicative_post_unexplored_excluded_from_positive_sum"]
        )
        self.assertEqual(contract["term_split"], "by_sign")
        self.assertTrue(contract["weight_perturbation_supported"])

    def test_optional_settings_default_to_none_on_older_refs(self):
        source = """
param!(FavoriteWeight, f64, "favorite", 0.5);
"""
        defaults = audit.parse_param_defaults(source)
        self.assertIsNone(defaults.get("MultiplierPreOffset"))
        self.assertEqual(
            set(audit.OPTIONAL_SETTING_PARAMS.values()),
            {
                "multiplier_pre_offset",
                "weight_perturbation_sigma",
                "cdwell_on_impr",
                "new_user_age_threshold_secs",
                "cached_posts_reuse_weighted_score",
            },
        )

    def test_promoted_setting_prefers_param_over_legacy_constant(self):
        # 3aa0fa336c moved NEW_USER_OON_WEIGHT_FACTOR from config.rs into a
        # feature-switch param with the same 0.00001 default.
        constants = "pub const NEW_USER_OON_WEIGHT_FACTOR: f64 = 0.00001;"
        self.assertEqual(
            audit.promoted_settings({}, constants),
            {"new_user_oon_weight_factor": 0.00001},
        )
        defaults = audit.parse_param_defaults(
            "param!(\n    NewUserOonWeightFactor,\n    f64,\n"
            '    "rust_home_mixer_new_user_oon_weight_factor",\n    0.5\n);'
        )
        self.assertEqual(
            audit.promoted_settings(defaults, constants),
            {"new_user_oon_weight_factor": 0.5},
        )
        self.assertEqual(
            audit.promoted_settings({}, "pub const OTHER: f64 = 1.0;"),
            {"new_user_oon_weight_factor": None},
        )

    def test_optional_constant_is_none_when_absent(self):
        self.assertIsNone(
            audit.parse_optional_rust_constant(
                "pub const OTHER: usize = 1;", "NEW_USER_MIN_FOLLOWING", "usize"
            )
        )
        self.assertEqual(
            audit.parse_optional_rust_constant(
                "pub const NEW_USER_MIN_FOLLOWING: usize = 5;",
                "NEW_USER_MIN_FOLLOWING",
                "usize",
            ),
            5,
        )

    def test_records_pre_offset_net_from_weighted_parts(self):
        source = (
            OFFSET_SOURCE
            + """
let positive_sum = favorite;
let negative_sum = -(report);
if query.params.get(MultiplierPreOffset) {
    let net = pos - neg;
}
"""
        )
        contract = audit.parse_scoring_contract(source)
        self.assertEqual(contract["pre_offset_net"], "weighted_parts")
        self.assertIsNone(contract["unoffset_inverts_offset"])

    def test_records_pre_offset_net_from_unoffset_weighted_score(self):
        # Since 1b3fec20bc the pre-offset branch inverts the offset of the
        # (possibly cached) weighted score instead of keeping (pos, neg).
        source = (
            OFFSET_SOURCE
            + """
let positive_sum = favorite;
let negative_sum = -(report);
pub(crate) fn unoffset_score(weighted_score: f64, w: &ScoringWeights) -> f64 {
    if w.total_sum == 0.0 {
        weighted_score
    } else if weighted_score < NEGATIVE_SCORES_OFFSET {
        weighted_score / NEGATIVE_SCORES_OFFSET * w.total_sum - w.negative_sum
    } else {
        weighted_score - NEGATIVE_SCORES_OFFSET
    }
}
if query.params.get(MultiplierPreOffset) {
    let net = Self::unoffset_score(weighted, &weights);
}
"""
        )
        contract = audit.parse_scoring_contract(source)
        self.assertEqual(contract["pre_offset_net"], "unoffset_weighted_score")
        self.assertTrue(contract["unoffset_inverts_offset"])

    def test_flags_unoffset_that_does_not_invert_offset(self):
        source = (
            OFFSET_SOURCE
            + """
let positive_sum = favorite;
let negative_sum = -(report);
pub(crate) fn unoffset_score(weighted_score: f64, w: &ScoringWeights) -> f64 {
    weighted_score
}
"""
        )
        contract = audit.parse_scoring_contract(source)
        self.assertIsNone(contract["pre_offset_net"])
        self.assertFalse(contract["unoffset_inverts_offset"])


if __name__ == "__main__":
    unittest.main()
