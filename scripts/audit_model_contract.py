#!/usr/bin/env python3
"""Audit the public Phoenix model contract without downloading its 2.9 GB ZIP.

The audit compares three independently published surfaces:

1. architecture claims in the root and Phoenix READMEs;
2. the configuration embedded in the Git LFS artifact ZIP; and
3. action-head indices used by ``run_pipeline.py`` versus ``runners.ACTIONS``.

Only the ZIP central directory and selected small JSON members are fetched with
HTTP Range requests.  This uses GitHub/Git LFS, not the X API.
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
DEFAULT_REF = "0bfc2795d308f90032544322747caacd535f75ae"
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
        selected[name.rsplit("/", 2)[-2] if "/config.json" in name else "example_sequence"] = (
            json.loads(raw)
        )
    meta = {
        "lfs_oid": oid,
        "archive_size_bytes": total_size,
        "range_bytes_requested_approximately": transferred,
        "zip_entry_count": len(members),
    }
    return selected, meta


def parse_readme_claims(root_readme: str, phoenix_readme: str) -> dict[str, dict[str, int]]:
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
        "root_readme": {"emb_size": int(root.group(1)), "num_layers": int(root.group(2))},
        "phoenix_readme": {
            "emb_size": int(phoenix.group(1)),
            "num_layers": int(phoenix.group(2)),
        },
    }


def parse_action_contract(runners_source: str, pipeline_source: str) -> dict[str, object]:
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
        for name, value in re.findall(r"^(IDX_[A-Z]+)\s*=\s*(\d+)", pipeline_source, re.MULTILINE)
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


def build_report(session: requests.Session, ref: str) -> dict[str, object]:
    root_readme = fetch_text(session, ref, "README.md")
    phoenix_readme = fetch_text(session, ref, "phoenix/README.md")
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


def contract_snapshot(report: dict[str, object]) -> dict[str, object]:
    """Return the stable, serving-relevant part of a live audit report."""
    artifact = report["artifact"]
    return {
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


def diff_values(expected: object, actual: object, path: str = "$") -> list[dict[str, object]]:
    """Build a compact, deterministic structural diff for JSON-compatible values."""
    if type(expected) is not type(actual):
        return [{"path": path, "expected": expected, "actual": actual}]
    if isinstance(expected, dict):
        differences: list[dict[str, object]] = []
        for key in sorted(set(expected) | set(actual)):
            key_path = f"{path}.{key}"
            if key not in expected:
                differences.append({"path": key_path, "expected": None, "actual": actual[key]})
            elif key not in actual:
                differences.append({"path": key_path, "expected": expected[key], "actual": None})
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
                differences.extend(diff_values(expected[index], actual[index], item_path))
        return differences
    return [] if expected == actual else [{"path": path, "expected": expected, "actual": actual}]


def compare_with_baseline(
    report: dict[str, object], baseline_path: Path
) -> dict[str, object]:
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AuditError(f"baseline file not found: {baseline_path}") from exc
    if baseline.get("schema_version") != 1 or not isinstance(baseline.get("contract"), dict):
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
    return not all(report["readme_matches_artifact"].values()) or not all(
        item["matches"] for item in report["action_contract"]["pipeline_index_mappings"]
    )


def has_drift(report: dict[str, object]) -> bool:
    comparison = report.get("baseline_comparison")
    return bool(comparison and comparison["status"] == "changed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default=DEFAULT_REF, help="upstream commit, tag, or branch")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help=f"known-contract baseline (default: {DEFAULT_BASELINE.relative_to(ROOT)})",
    )
    parser.add_argument(
        "--no-baseline", action="store_true", help="skip known-vs-new contract comparison"
    )
    parser.add_argument(
        "--strict", action="store_true", help="exit 1 when an upstream mismatch is found"
    )
    parser.add_argument(
        "--fail-on-drift", action="store_true", help="exit 1 only for changes from baseline"
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
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_text(report))
    failed = (args.strict and has_mismatch(report)) or (args.fail_on_drift and has_drift(report))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
