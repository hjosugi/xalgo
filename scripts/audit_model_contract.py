#!/usr/bin/env python3
"""Audit both generations of the public Phoenix model contract.

The May 2026 demo generation is inspected through its README claims, selected
members of the Git LFS artifact, and ``run_pipeline.py`` action indices.  The
August 2026 source generation removed those files, so it is inspected through
the checked-in Phoenix configs and Home Mixer scoring defaults instead.

Legacy ZIP inspection still reads only the central directory and selected
small JSON members with HTTP Range requests.  This uses GitHub/Git LFS, not
the X API.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests


REPO = "xai-org/x-algorithm"
DEFAULT_REF = "main"
LEGACY_DEFAULT_REF = "0bfc2795d308f90032544322747caacd535f75ae"
ARTIFACT_PATH = "phoenix/artifacts/oss-phoenix-artifacts.zip"
RAW_ROOT = "https://raw.githubusercontent.com"
LFS_BATCH_URL = f"https://github.com/{REPO}.git/info/lfs/objects/batch"
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = ROOT / "state" / "model_contract_baseline.json"
JSON_MEMBERS = (
    "oss-phoenix-artifacts/retrieval/config.json",
    "oss-phoenix-artifacts/ranker/config.json",
    "oss-phoenix-artifacts/example_sequence.json",
)
SOURCE_PATHS = {
    "params": "home-mixer/params/param.rs",
    "constants": "home-mixer/params/config.rs",
    "ranking_scorer": "home-mixer/scorers/ranking_scorer.rs",
    "ranking_config": "phoenix/xrex/configs/xrecsys.py",
    "retrieval_config": "phoenix/xrex/configs/xrecsys_two_tower.py",
}
WEIGHT_PARAMS = {
    "FavoriteWeight": "favorite",
    "ReplyWeight": "reply",
    "RetweetWeight": "retweet",
    "PhotoExpandWeight": "photo_expand",
    "VideoOpenWeight": "video_open",
    "ClickWeight": "click",
    "OpenLinkWeight": "open_link",
    "ProfileClickWeight": "profile_click",
    "VqvWeight": "vqv",
    "ShareWeight": "share",
    "ShareViaDmWeight": "share_via_dm",
    "ShareViaCopyLinkWeight": "share_via_copy_link",
    "DwellWeight": "dwell",
    "QuoteWeight": "quote",
    "QuotedClickWeight": "quoted_click",
    "QuotedVqvWeight": "quoted_vqv",
    "ContDwellTimeWeight": "cont_dwell_time",
    "ContClickDwellTimeWeight": "cont_click_dwell_time",
    "ContActiveSecs5mResidualNormWeight": "cont_active_secs_5m_residual_norm",
    "FollowAuthorWeight": "follow_author",
    "PostUnexploredWeight": "post_unexplored",
    "NotInterestedWeight": "not_interested",
    "BlockAuthorWeight": "block_author",
    "MuteAuthorWeight": "mute_author",
    "ReportWeight": "report",
    "NotDwelledWeight": "not_dwelled",
}
SETTING_PARAMS = {
    "EnableAuthorDiversity": "author_diversity_enabled",
    "AuthorDiversityDecay": "author_diversity_decay",
    "AuthorDiversityFloor": "author_diversity_floor",
    "OonWeightFactor": "oon_weight_factor",
    "TopicOonWeightFactor": "topic_oon_weight_factor",
    "MinVideoDurationMs": "min_video_duration_ms",
    "EnableQuotedVqvDurationCheck": "quoted_vqv_duration_check",
    "BidirectionalFollowReplyWeightBoost": "bidirectional_follow_reply_weight_boost",
    "BidirectionalFollowDwellWeightBoost": "bidirectional_follow_dwell_weight_boost",
    "EnableMultiplicativePostUnexplored": "multiplicative_post_unexplored",
    "MultiplicativePostUnexploredAlpha": "multiplicative_post_unexplored_alpha",
    "PostUnexploredWeightInNetworkOnly": "post_unexplored_in_network_only",
}
MODEL_FIELDS = (
    "history_seq_len",
    "candidate_seq_len",
    "num_layers",
    "emb_size",
    "emb_table_width",
    "query_heads",
    "kv_heads",
    "sid_num_levels",
    "sid_codebook_size",
    "use_seqpack",
    "max_posts",
)


@dataclass(frozen=True)
class ZipMember:
    compression: int
    compressed_size: int
    uncompressed_size: int
    local_offset: int


class AuditError(RuntimeError):
    """Raised when a remote model contract cannot be inspected safely."""


def fetch_text(session: requests.Session, ref: str, path: str) -> str:
    url = f"{RAW_ROOT}/{REPO}/{ref}/{path}"
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def fetch_optional_text(session: requests.Session, ref: str, path: str) -> str | None:
    """Fetch text while treating an absent generation-specific file as a signal."""
    url = f"{RAW_ROOT}/{REPO}/{ref}/{path}"
    response = session.get(url, timeout=30)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.text


def _parse_primitive(type_name: str, raw_value: str) -> object:
    value = raw_value.strip().replace("_", "")
    if type_name == "bool":
        if value not in {"true", "false"}:
            raise AuditError(f"unsupported boolean default: {raw_value}")
        return value == "true"
    if type_name in {"i32", "u32", "u64", "usize"}:
        tree = ast.parse(value, mode="eval")

        def integer(node: ast.AST) -> int:
            if isinstance(node, ast.Expression):
                return integer(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, int):
                return node.value
            if isinstance(node, ast.BinOp) and isinstance(
                node.op, (ast.Add, ast.Sub, ast.Mult)
            ):
                left = integer(node.left)
                right = integer(node.right)
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                return left * right
            raise AuditError(f"unsupported integer expression: {raw_value}")

        return integer(tree)
    if type_name == "f64":
        return float(value)
    raise AuditError(f"unsupported parameter type: {type_name}")


def parse_param_defaults(source: str) -> dict[str, object]:
    """Parse primitive ``param!`` defaults without compiling upstream Rust."""
    pattern = re.compile(
        r'param!\(\s*(\w+),\s*(f64|i32|u32|u64|usize|bool),\s*"[^"]+",'
        r"\s*([^\s,)]+)\s*\);",
        re.DOTALL,
    )
    return {
        name: _parse_primitive(type_name, raw_value)
        for name, type_name, raw_value in pattern.findall(source)
    }


def parse_rust_constant(source: str, name: str, type_name: str) -> object:
    match = re.search(
        rf"pub const {re.escape(name)}:\s*{re.escape(type_name)}\s*=\s*([^;]+);",
        source,
    )
    if not match:
        raise AuditError(f"could not parse Rust constant {name}")
    return _parse_primitive(type_name, match.group(1))


def _scalar_ast_value(node: ast.AST) -> object | None:
    if isinstance(node, ast.Constant) and isinstance(
        node.value, (bool, int, float, str)
    ):
        return node.value
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, (int, float))
    ):
        return -node.operand.value
    return None


def _call_name(node: ast.Call) -> str | None:
    return node.func.id if isinstance(node.func, ast.Name) else None


def _resolve_scalar_dict(
    node: ast.AST,
    named: dict[str, dict[str, object]],
    factories: dict[str, dict[str, object]],
) -> dict[str, object]:
    if isinstance(node, ast.Name):
        return dict(named.get(node.id, {}))
    if isinstance(node, ast.Call):
        name = _call_name(node)
        return dict(factories.get(name or "", {}))
    if not isinstance(node, ast.Dict):
        return {}
    result: dict[str, object] = {}
    for key_node, value_node in zip(node.keys, node.values):
        if key_node is None:
            result.update(_resolve_scalar_dict(value_node, named, factories))
            continue
        key = _scalar_ast_value(key_node)
        value = _scalar_ast_value(value_node)
        if isinstance(key, str) and value is not None:
            result[key] = value
    return result


def parse_model_profiles(
    source: str, selected_names: tuple[str, ...]
) -> dict[str, dict[str, object]]:
    """Extract stable scalar fields from selected upstream ``MODEL_CFGS`` entries."""
    tree = ast.parse(source)
    named: dict[str, dict[str, object]] = {}
    factories: dict[str, dict[str, object]] = {}

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            for statement in node.body:
                if isinstance(statement, ast.Return) and statement.value is not None:
                    values = _resolve_scalar_dict(statement.value, named, factories)
                    if values:
                        factories[node.name] = values
                    break
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id != "MODEL_CFGS"
        ):
            values = _resolve_scalar_dict(node.value, named, factories)
            if values:
                named[node.targets[0].id] = values

    model_node: ast.Dict | None = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "MODEL_CFGS"
            for target in node.targets
        ) and isinstance(node.value, ast.Dict):
            model_node = node.value
            break
    if model_node is None:
        raise AuditError("could not parse upstream MODEL_CFGS")

    profiles: dict[str, dict[str, object]] = {}
    for key_node, value_node in zip(model_node.keys, model_node.values):
        name = _scalar_ast_value(key_node) if key_node is not None else None
        if name not in selected_names or not isinstance(value_node, ast.Call):
            continue
        if not value_node.args:
            continue
        values = _resolve_scalar_dict(value_node.args[0], named, factories)
        profiles[str(name)] = {
            field: values[field] for field in MODEL_FIELDS if field in values
        }

    missing = sorted(set(selected_names) - set(profiles))
    if missing:
        raise AuditError(f"could not parse model profiles: {', '.join(missing)}")
    return profiles


def parse_lfs_pointer(text: str) -> tuple[str, int]:
    oid_match = re.search(r"^oid sha256:([0-9a-f]{64})$", text, re.MULTILINE)
    size_match = re.search(r"^size (\d+)$", text, re.MULTILINE)
    if not oid_match or not size_match:
        raise AuditError("artifact path did not return a Git LFS pointer")
    return oid_match.group(1), int(size_match.group(1))


def resolve_lfs_download(session: requests.Session, oid: str, size: int) -> str:
    response = session.post(
        LFS_BATCH_URL,
        headers={
            "Accept": "application/vnd.git-lfs+json",
            "Content-Type": "application/vnd.git-lfs+json",
        },
        json={
            "operation": "download",
            "transfers": ["basic"],
            "objects": [{"oid": oid, "size": size}],
        },
        timeout=30,
    )
    response.raise_for_status()
    obj = response.json()["objects"][0]
    if "error" in obj:
        raise AuditError(f"Git LFS error: {obj['error']}")
    return obj["actions"]["download"]["href"]


def make_range_reader(
    session: requests.Session, url: str, total_size: int
) -> Callable[[int, int], bytes]:
    def read(start: int, end: int) -> bytes:
        if start < 0 or end < start or end >= total_size:
            raise AuditError(f"invalid byte range {start}-{end} for {total_size}")
        response = session.get(
            url,
            headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"},
            timeout=60,
        )
        if response.status_code != 206:
            raise AuditError(
                f"server ignored safe Range request ({response.status_code}); aborting "
                "instead of downloading the full artifact"
            )
        expected = end - start + 1
        if len(response.content) != expected:
            raise AuditError(
                f"short/oversized range response: expected {expected}, got {len(response.content)}"
            )
        return response.content

    return read


def read_zip_directory(
    read_range: Callable[[int, int], bytes], total_size: int
) -> tuple[dict[str, ZipMember], int]:
    tail_size = min(total_size, 65_557)
    tail_start = total_size - tail_size
    tail = read_range(tail_start, total_size - 1)
    eocd_at = tail.rfind(b"PK\x05\x06")
    if eocd_at < 0 or eocd_at + 22 > len(tail):
        raise AuditError("ZIP end-of-central-directory record not found")
    eocd = struct.unpack_from("<4s4H2IH", tail, eocd_at)
    entry_count, directory_size, directory_offset = eocd[4], eocd[5], eocd[6]
    directory = read_range(directory_offset, directory_offset + directory_size - 1)

    members: dict[str, ZipMember] = {}
    cursor = 0
    for _ in range(entry_count):
        if directory[cursor : cursor + 4] != b"PK\x01\x02":
            raise AuditError("invalid ZIP central-directory entry")
        values = struct.unpack_from("<4s6H3I5H2I", directory, cursor)
        compression = values[4]
        compressed_size = values[8]
        uncompressed_size = values[9]
        name_len, extra_len, comment_len = values[10], values[11], values[12]
        local_offset = values[16]
        name_start = cursor + 46
        name = directory[name_start : name_start + name_len].decode("utf-8")
        members[name] = ZipMember(
            compression=compression,
            compressed_size=compressed_size,
            uncompressed_size=uncompressed_size,
            local_offset=local_offset,
        )
        cursor = name_start + name_len + extra_len + comment_len
    return members, tail_size + directory_size


def read_zip_member(
    read_range: Callable[[int, int], bytes], member: ZipMember
) -> tuple[bytes, int]:
    header = read_range(member.local_offset, member.local_offset + 29)
    if header[:4] != b"PK\x03\x04":
        raise AuditError("invalid ZIP local-file header")
    values = struct.unpack("<4s5H3I2H", header)
    name_len, extra_len = values[9], values[10]
    data_start = member.local_offset + 30 + name_len + extra_len
    compressed = read_range(data_start, data_start + member.compressed_size - 1)
    if member.compression == 0:
        data = compressed
    elif member.compression == 8:
        data = zlib.decompress(compressed, -zlib.MAX_WBITS)
    else:
        raise AuditError(f"unsupported ZIP compression method {member.compression}")
    if len(data) != member.uncompressed_size:
        raise AuditError("decompressed ZIP member has the wrong size")
    return data, 30 + member.compressed_size


def inspect_artifact(
    session: requests.Session, ref: str
) -> tuple[dict[str, object], dict[str, object]]:
    pointer = fetch_text(session, ref, ARTIFACT_PATH)
    oid, total_size = parse_lfs_pointer(pointer)
    url = resolve_lfs_download(session, oid, total_size)
    read_range = make_range_reader(session, url, total_size)
    members, transferred = read_zip_directory(read_range, total_size)

    selected: dict[str, object] = {}
    for name in JSON_MEMBERS:
        if name not in members:
            raise AuditError(f"missing artifact member: {name}")
        raw, member_bytes = read_zip_member(read_range, members[name])
        transferred += member_bytes
        selected[
            name.rsplit("/", 2)[-2] if "/config.json" in name else "example_sequence"
        ] = json.loads(raw)
    meta = {
        "lfs_oid": oid,
        "archive_size_bytes": total_size,
        "range_bytes_requested_approximately": transferred,
        "zip_entry_count": len(members),
    }
    return selected, meta


def parse_readme_claims(
    root_readme: str, phoenix_readme: str
) -> dict[str, dict[str, int]]:
    root = re.search(
        r"mini Phoenix model \((\d+)-dim embeddings, \d+ attention heads, (\d+) transformer layers\)",
        root_readme,
    )
    phoenix = re.search(
        r"mini version of the Phoenix model \((\d+)-dim, (\d+)-layer transformer\)",
        phoenix_readme,
    )
    if not root or not phoenix:
        raise AuditError("could not parse architecture claims from upstream READMEs")
    return {
        "root_readme": {
            "emb_size": int(root.group(1)),
            "num_layers": int(root.group(2)),
        },
        "phoenix_readme": {
            "emb_size": int(phoenix.group(1)),
            "num_layers": int(phoenix.group(2)),
        },
    }


def parse_action_contract(
    runners_source: str, pipeline_source: str
) -> dict[str, object]:
    tree = ast.parse(runners_source)
    actions: list[str] | None = None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "ACTIONS" and node.value is not None:
                actions = ast.literal_eval(node.value)
                break
    if actions is None:
        raise AuditError("could not parse runners.py ACTIONS")

    constants = {
        name: int(value)
        for name, value in re.findall(
            r"^(IDX_[A-Z]+)\s*=\s*(\d+)", pipeline_source, re.MULTILINE
        )
    }
    declared_semantics = {
        "IDX_FAV": "favorite_score",
        "IDX_REPLY": "reply_score",
        "IDX_QUOTE": "quote_score",
        "IDX_RT": "repost_score",
        "IDX_DWELL": "dwell_score",
        "IDX_VQV": "vqv_score",
    }
    mappings = []
    for constant, expected in declared_semantics.items():
        index = constants.get(constant)
        actual = actions[index] if index is not None and index < len(actions) else None
        mappings.append(
            {
                "constant": constant,
                "index": index,
                "expected_head": expected,
                "actual_head_at_index": actual,
                "matches": actual == expected,
            }
        )
    return {"actions": actions, "pipeline_index_mappings": mappings}


def build_legacy_report(
    session: requests.Session,
    ref: str,
    root_readme: str,
    phoenix_readme: str,
) -> dict[str, object]:
    runners = fetch_text(session, ref, "phoenix/runners.py")
    pipeline = fetch_text(session, ref, "phoenix/run_pipeline.py")
    claims = parse_readme_claims(root_readme, phoenix_readme)
    action_contract = parse_action_contract(runners, pipeline)
    artifact, artifact_meta = inspect_artifact(session, ref)
    ranker = artifact["ranker"]
    retrieval = artifact["retrieval"]
    artifact_architecture = {
        key: ranker[key]
        for key in (
            "emb_size",
            "num_layers",
            "num_heads",
            "key_size",
            "history_seq_len",
            "candidate_seq_len",
            "num_actions",
        )
    }
    return {
        "repository": REPO,
        "ref": ref,
        "generation": "legacy_demo_2026_05",
        "readme_claims": claims,
        "artifact_architecture": artifact_architecture,
        "retrieval_ranker_configs_match": all(
            retrieval.get(key) == ranker.get(key) for key in artifact_architecture
        ),
        "readme_matches_artifact": {
            name: all(values[key] == artifact_architecture[key] for key in values)
            for name, values in claims.items()
        },
        "action_contract": action_contract,
        "artifact": artifact_meta,
        "example_history_items": len(artifact["example_sequence"].get("history", [])),
    }


def _parse_python_int(source: str, name: str) -> int:
    match = re.search(rf"^{re.escape(name)}\s*=\s*(\d+)", source, re.MULTILINE)
    if not match:
        raise AuditError(f"could not parse Python constant {name}")
    return int(match.group(1))


def parse_scoring_contract(source: str) -> dict[str, object]:
    """Extract the normalization operands and offset branches from Rust source."""

    actions = set(WEIGHT_PARAMS.values())

    def operands(name: str) -> list[str]:
        match = re.search(rf"let {re.escape(name)}\s*=\s*(.*?);", source, re.DOTALL)
        if not match:
            raise AuditError(f"could not parse scoring expression {name}")
        found: list[str] = []
        for token in re.findall(r"\b[a-z][a-z0-9_]*\b", match.group(1)):
            if token in actions and token not in found:
                found.append(token)
        return found

    compact = re.sub(r"\s+", "", source)
    required_offset_fragments = {
        "zero_total_clamps_nonnegative": (
            "ifw.total_sum==0.0{combined_score.max(0.0)}"
        ),
        "negative_branch_is_strict": "elseifcombined_score<0.0",
        "negative_branch_normalizes": (
            "(combined_score+w.negative_sum)/w.total_sum*NEGATIVE_SCORES_OFFSET"
        ),
        "nonnegative_branch_adds_offset": (
            "else{combined_score+NEGATIVE_SCORES_OFFSET}"
        ),
    }
    missing = [
        name
        for name, fragment in required_offset_fragments.items()
        if fragment not in compact
    ]
    if missing:
        raise AuditError(f"could not verify scoring branches: {', '.join(missing)}")

    return {
        "positive_normalization_actions": operands("positive_sum"),
        "negative_normalization_actions": operands("negative_sum"),
        "multiplicative_post_unexplored_excluded_from_positive_sum": (
            "ifenable_multiplicative_post_unexplored{0.0}else{post_unexplored}"
            in compact
        ),
        **{name: True for name in required_offset_fragments},
    }


def build_source_report(
    session: requests.Session,
    ref: str,
    sources: dict[str, str],
) -> dict[str, object]:
    del session
    defaults = parse_param_defaults(sources["params"])
    required = set(WEIGHT_PARAMS) | set(SETTING_PARAMS)
    missing = sorted(required - set(defaults))
    if missing:
        raise AuditError(f"missing public Home Mixer defaults: {', '.join(missing)}")

    action_type_count = _parse_python_int(
        sources["ranking_config"], "ACTION_TYPE_MAP_LEN"
    )
    output_alignment = _parse_python_int(sources["ranking_config"], "OUTPUT_VOCAB_K")
    continuous_action_count = _parse_python_int(
        sources["ranking_config"], "CONTINUOUS_ACTION_TYPE_MAP_LEN"
    )
    output_vocab_size = (
        (action_type_count + output_alignment - 1) // output_alignment
    ) * output_alignment

    return {
        "repository": REPO,
        "ref": ref,
        "generation": "source_2026_08",
        "ranking_weights": {
            action: defaults[param] for param, action in WEIGHT_PARAMS.items()
        },
        "ranking_settings": {
            setting: defaults[param] for param, setting in SETTING_PARAMS.items()
        },
        "scoring_constants": {
            "negative_scores_offset": parse_rust_constant(
                sources["constants"], "NEGATIVE_SCORES_OFFSET", "f64"
            ),
            "max_post_age_seconds": parse_rust_constant(
                sources["constants"], "MAX_POST_AGE", "u64"
            ),
            "top_k_candidates": parse_rust_constant(
                sources["constants"], "TOP_K_CANDIDATES_TO_SELECT", "usize"
            ),
        },
        "scoring_contract": parse_scoring_contract(sources["ranking_scorer"]),
        "model_profiles": {
            **parse_model_profiles(
                sources["ranking_config"],
                ("xrecsys_seqpack", "home_direct_packed_nano"),
            ),
            **parse_model_profiles(
                sources["retrieval_config"],
                ("xrecsys_two_tower", "xrecsys_two_tower_nano"),
            ),
        },
        "action_space": {
            "defined_discrete_actions": action_type_count,
            "padded_output_vocab_size": output_vocab_size,
            "continuous_action_slots": continuous_action_count,
        },
        "legacy_demo_contract": {
            "status": "superseded",
            "artifact_path_present": False,
            "run_pipeline_present": False,
            "runners_action_list_present": False,
        },
        "source_files": list(SOURCE_PATHS.values()),
    }


def build_report(session: requests.Session, ref: str) -> dict[str, object]:
    root_readme = fetch_text(session, ref, "README.md")
    phoenix_readme = fetch_text(session, ref, "phoenix/README.md")
    params = fetch_optional_text(session, ref, SOURCE_PATHS["params"])
    if params is None:
        return build_legacy_report(
            session, ref, root_readme=root_readme, phoenix_readme=phoenix_readme
        )

    sources = {"params": params}
    for name, path in SOURCE_PATHS.items():
        if name == "params":
            continue
        sources[name] = fetch_text(session, ref, path)
    return build_source_report(session, ref, sources)


def contract_snapshot(report: dict[str, object]) -> dict[str, object]:
    """Return the stable, serving-relevant part of a live audit report."""
    if report.get("generation") == "source_2026_08":
        return {
            key: report[key]
            for key in (
                "generation",
                "ranking_weights",
                "ranking_settings",
                "scoring_constants",
                "scoring_contract",
                "model_profiles",
                "action_space",
                "legacy_demo_contract",
            )
        }
    artifact = report["artifact"]
    return {
        "generation": report.get("generation", "legacy_demo_2026_05"),
        "readme_claims": report["readme_claims"],
        "artifact_architecture": report["artifact_architecture"],
        "retrieval_ranker_configs_match": report["retrieval_ranker_configs_match"],
        "readme_matches_artifact": report["readme_matches_artifact"],
        "action_contract": report["action_contract"],
        "artifact_identity": {
            "lfs_oid": artifact["lfs_oid"],
            "archive_size_bytes": artifact["archive_size_bytes"],
            "zip_entry_count": artifact["zip_entry_count"],
        },
        "example_history_items": report["example_history_items"],
    }


def diff_values(
    expected: object, actual: object, path: str = "$"
) -> list[dict[str, object]]:
    """Build a compact, deterministic structural diff for JSON-compatible values."""
    if type(expected) is not type(actual):
        return [{"path": path, "expected": expected, "actual": actual}]
    if isinstance(expected, dict):
        differences: list[dict[str, object]] = []
        for key in sorted(set(expected) | set(actual)):
            key_path = f"{path}.{key}"
            if key not in expected:
                differences.append(
                    {"path": key_path, "expected": None, "actual": actual[key]}
                )
            elif key not in actual:
                differences.append(
                    {"path": key_path, "expected": expected[key], "actual": None}
                )
            else:
                differences.extend(diff_values(expected[key], actual[key], key_path))
        return differences
    if isinstance(expected, list):
        differences = []
        for index in range(max(len(expected), len(actual))):
            item_path = f"{path}[{index}]"
            if index >= len(expected):
                differences.append(
                    {"path": item_path, "expected": None, "actual": actual[index]}
                )
            elif index >= len(actual):
                differences.append(
                    {"path": item_path, "expected": expected[index], "actual": None}
                )
            else:
                differences.extend(
                    diff_values(expected[index], actual[index], item_path)
                )
        return differences
    return (
        []
        if expected == actual
        else [{"path": path, "expected": expected, "actual": actual}]
    )


def compare_with_baseline(
    report: dict[str, object], baseline_path: Path
) -> dict[str, object]:
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AuditError(f"baseline file not found: {baseline_path}") from exc
    if baseline.get("schema_version") not in {1, 2} or not isinstance(
        baseline.get("contract"), dict
    ):
        raise AuditError(f"unsupported model-contract baseline: {baseline_path}")
    differences = diff_values(baseline["contract"], contract_snapshot(report))
    try:
        shown_path = str(baseline_path.relative_to(ROOT))
    except ValueError:
        shown_path = str(baseline_path)
    return {
        "status": "changed" if differences else "unchanged",
        "baseline_path": shown_path,
        "baseline_source_ref": baseline.get("source_ref"),
        "difference_count": len(differences),
        "differences": differences,
    }


def render_text(report: dict[str, object]) -> str:
    if report.get("generation") == "source_2026_08":
        profiles = report["model_profiles"]
        weights = report["ranking_weights"]
        settings = report["ranking_settings"]
        lines = [
            f"upstream: {report['repository']}@{report['ref']}",
            "generation: August 2026 source release",
            (
                "ranking defaults: "
                f"favorite={weights['favorite']}, reply={weights['reply']}, "
                f"retweet={weights['retweet']}, report={weights['report']}"
            ),
            (
                "gates: "
                f"VQV>{settings['min_video_duration_ms']}ms, "
                f"author diversity={settings['author_diversity_decay']}/"
                f"{settings['author_diversity_floor']}, "
                f"OON={settings['oon_weight_factor']}"
            ),
        ]
        for name, profile in profiles.items():
            lines.append(
                f"{name}: D={profile.get('emb_size')}, "
                f"layers={profile.get('num_layers')}, "
                f"heads={profile.get('query_heads')}/{profile.get('kv_heads')}, "
                f"history={profile.get('history_seq_len')}, "
                f"candidates={profile.get('candidate_seq_len')}"
            )
        comparison = report.get("baseline_comparison")
        if comparison:
            lines.append(
                f"baseline: {comparison['status'].upper()} "
                f"({comparison['difference_count']} differences vs "
                f"{comparison['baseline_source_ref']})"
            )
            for difference in comparison["differences"][:20]:
                lines.append(
                    f"  {difference['path']}: {difference['expected']!r} -> "
                    f"{difference['actual']!r}"
                )
        return "\n".join(lines)

    artifact = report["artifact_architecture"]
    lines = [
        f"upstream: {report['repository']}@{report['ref']}",
        (
            "artifact: "
            f"D={artifact['emb_size']}, layers={artifact['num_layers']}, "
            f"heads={artifact['num_heads']}, history={artifact['history_seq_len']}, "
            f"candidates={artifact['candidate_seq_len']}, actions={artifact['num_actions']}"
        ),
    ]
    for name, values in report["readme_claims"].items():
        state = "MATCH" if report["readme_matches_artifact"][name] else "MISMATCH"
        lines.append(f"{name}: {values} -> {state}")
    lines.append("run_pipeline.py index -> runners.py output head:")
    for item in report["action_contract"]["pipeline_index_mappings"]:
        state = "MATCH" if item["matches"] else "MISMATCH"
        lines.append(
            f"  {item['constant']}={item['index']}: expected {item['expected_head']}, "
            f"actual {item['actual_head_at_index']} -> {state}"
        )
    meta = report["artifact"]
    lines.append(
        f"artifact bytes: archive={meta['archive_size_bytes']:,}, "
        f"range-read≈{meta['range_bytes_requested_approximately']:,}"
    )
    comparison = report.get("baseline_comparison")
    if comparison:
        lines.append(
            f"baseline: {comparison['status'].upper()} "
            f"({comparison['difference_count']} differences vs "
            f"{comparison['baseline_source_ref']})"
        )
        for difference in comparison["differences"][:20]:
            lines.append(
                f"  {difference['path']}: {difference['expected']!r} -> "
                f"{difference['actual']!r}"
            )
    return "\n".join(lines)


def has_mismatch(report: dict[str, object]) -> bool:
    if report.get("generation") == "source_2026_08":
        return False
    return not all(report["readme_matches_artifact"].values()) or not all(
        item["matches"] for item in report["action_contract"]["pipeline_index_mappings"]
    )


def has_drift(report: dict[str, object]) -> bool:
    comparison = report.get("baseline_comparison")
    return bool(comparison and comparison["status"] == "changed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref", default=DEFAULT_REF, help="upstream commit, tag, or branch"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON"
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help=f"known-contract baseline (default: {DEFAULT_BASELINE.relative_to(ROOT)})",
    )
    parser.add_argument(
        "--no-baseline",
        action="store_true",
        help="skip known-vs-new contract comparison",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when an upstream mismatch is found",
    )
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="exit 1 only for changes from baseline",
    )
    args = parser.parse_args()
    try:
        with requests.Session() as session:
            report = build_report(session, args.ref)
        if not args.no_baseline:
            report["baseline_comparison"] = compare_with_baseline(report, args.baseline)
    except (AuditError, KeyError, ValueError, requests.RequestException) as exc:
        print(f"audit failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json
        else render_text(report)
    )
    failed = (args.strict and has_mismatch(report)) or (
        args.fail_on_drift and has_drift(report)
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
