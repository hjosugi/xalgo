import io
import zipfile
import unittest

from scripts import audit_model_contract as audit


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
            {"multiplier_pre_offset", "weight_perturbation_sigma", "cdwell_on_impr"},
        )


if __name__ == "__main__":
    unittest.main()
