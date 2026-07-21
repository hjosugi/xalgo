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
        runners = 'ACTIONS: list[str] = ["favorite_score", "reply_score", "repost_score"]'
        pipeline = "IDX_FAV = 1\nIDX_REPLY = 2\n"
        result = audit.parse_action_contract(runners, pipeline)
        mappings = {item["constant"]: item for item in result["pipeline_index_mappings"]}
        self.assertEqual(mappings["IDX_FAV"]["actual_head_at_index"], "reply_score")
        self.assertFalse(mappings["IDX_FAV"]["matches"])


if __name__ == "__main__":
    unittest.main()
