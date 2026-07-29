#!/usr/bin/env python3
"""Evaluate proxy-score ordering against anonymized For You feed snapshots.

This script never logs in to X and does not accept cookies or API tokens.  It
compares rankings only within each user-supplied snapshot.  The result is an
observational agreement report, not a causal test of the production algorithm.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_COLUMNS = {
    "snapshot_id",
    "viewer_hash",
    "requested_at",
    "position",
    "post_id",
    "proxy_score",
}
OPTIONAL_STRATA = ("in_network", "media_type", "view_bucket")
FORBIDDEN_COLUMN_PARTS = ("cookie", "token", "password", "email", "authorization")
FORBIDDEN_COLUMN_NAMES = {
    "viewer_id",
    "viewer_username",
    "viewer_handle",
    "screen_name",
    "author_id",
    "author_username",
    "author_handle",
}


class SnapshotError(ValueError):
    """Raised when a feed-snapshot dataset is unsafe or invalid."""


@dataclass(frozen=True)
class FeedRow:
    snapshot_id: str
    viewer_hash: str
    requested_at: str
    position: int
    post_id: str
    proxy_score: float
    in_network: str = "unknown"
    media_type: str = "unknown"
    view_bucket: str = "unknown"
    author_hash: str = ""


def rankdata(values: list[float]) -> list[float]:
    """Return ascending average ranks, including deterministic tie handling."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        average = ((start + 1) + end) / 2
        for cursor in range(start, end):
            ranks[order[cursor]] = average
        start = end
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3 or len(xs) != len(ys):
        return float("nan")
    rx, ry = rankdata(xs), rankdata(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    numerator = sum((x - mx) * (y - my) for x, y in zip(rx, ry))
    denominator = math.sqrt(
        sum((x - mx) ** 2 for x in rx) * sum((y - my) ** 2 for y in ry)
    )
    return numerator / denominator if denominator else float("nan")


def kendall_tau_b(xs: list[float], ys: list[float]) -> float:
    """Kendall tau-b with ties in either ranking."""
    if len(xs) < 2 or len(xs) != len(ys):
        return float("nan")
    concordant = discordant = ties_x = ties_y = 0
    for left in range(len(xs)):
        for right in range(left + 1, len(xs)):
            dx = (xs[left] > xs[right]) - (xs[left] < xs[right])
            dy = (ys[left] > ys[right]) - (ys[left] < ys[right])
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                ties_x += 1
            elif dy == 0:
                ties_y += 1
            elif dx == dy:
                concordant += 1
            else:
                discordant += 1
    denominator = math.sqrt(
        (concordant + discordant + ties_x) * (concordant + discordant + ties_y)
    )
    return (concordant - discordant) / denominator if denominator else float("nan")


def _parse_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotError(f"invalid requested_at timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise SnapshotError(f"requested_at must include a timezone: {value}")
    return parsed.isoformat()


def _clean_stratum(value: str | None) -> str:
    cleaned = (value or "unknown").strip().lower()
    return cleaned or "unknown"


def load_rows(path: Path) -> list[FeedRow]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            raise SnapshotError(f"missing required columns: {', '.join(missing)}")
        unsafe = sorted(
            column
            for column in columns
            if column.lower() in FORBIDDEN_COLUMN_NAMES
            or any(part in column.lower() for part in FORBIDDEN_COLUMN_PARTS)
        )
        if unsafe:
            raise SnapshotError(
                "sensitive columns are forbidden; remove before analysis: "
                + ", ".join(unsafe)
            )
        rows = []
        for line_number, raw in enumerate(reader, 2):
            try:
                position = int(raw["position"])
                score = float(raw["proxy_score"])
            except (TypeError, ValueError) as exc:
                raise SnapshotError(f"invalid number at CSV line {line_number}") from exc
            if position < 1:
                raise SnapshotError(f"position must be >= 1 at CSV line {line_number}")
            if not math.isfinite(score):
                raise SnapshotError(f"proxy_score must be finite at CSV line {line_number}")
            for name in ("snapshot_id", "viewer_hash", "post_id"):
                if not (raw.get(name) or "").strip():
                    raise SnapshotError(f"{name} is empty at CSV line {line_number}")
            rows.append(
                FeedRow(
                    snapshot_id=raw["snapshot_id"].strip(),
                    viewer_hash=raw["viewer_hash"].strip(),
                    requested_at=_parse_timestamp(raw["requested_at"].strip()),
                    position=position,
                    post_id=raw["post_id"].strip(),
                    proxy_score=score,
                    in_network=_clean_stratum(raw.get("in_network")),
                    media_type=_clean_stratum(raw.get("media_type")),
                    view_bucket=_clean_stratum(raw.get("view_bucket")),
                    author_hash=(raw.get("author_hash") or "").strip(),
                )
            )
    if not rows:
        raise SnapshotError("snapshot CSV has no data rows")
    return rows


def validate_snapshot(rows: list[FeedRow]) -> None:
    if len(rows) < 3:
        raise SnapshotError(f"snapshot {rows[0].snapshot_id} needs at least 3 posts")
    if len({row.viewer_hash for row in rows}) != 1:
        raise SnapshotError(f"snapshot {rows[0].snapshot_id} mixes viewer hashes")
    if len({row.requested_at for row in rows}) != 1:
        raise SnapshotError(f"snapshot {rows[0].snapshot_id} mixes request timestamps")
    positions = [row.position for row in rows]
    post_ids = [row.post_id for row in rows]
    if len(set(positions)) != len(positions):
        raise SnapshotError(f"snapshot {rows[0].snapshot_id} has duplicate positions")
    if len(set(post_ids)) != len(post_ids):
        raise SnapshotError(f"snapshot {rows[0].snapshot_id} has duplicate post IDs")


def _dcg(order: list[FeedRow], relevance: dict[str, float], k: int) -> float:
    return sum(
        relevance[row.post_id] / math.log2(rank + 1)
        for rank, row in enumerate(order[:k], 1)
    )


def snapshot_metrics(rows: list[FeedRow], ks: list[int]) -> dict[str, object]:
    validate_snapshot(rows)
    observed = sorted(rows, key=lambda row: row.position)
    predicted = sorted(rows, key=lambda row: (-row.proxy_score, row.post_id))
    predicted_ranks = rankdata([-row.proxy_score for row in rows])
    observed_ranks = rankdata([float(row.position) for row in rows])
    relevance = {
        row.post_id: 1.0 / math.log2(rank + 1) for rank, row in enumerate(observed, 1)
    }
    metrics: dict[str, float] = {
        "spearman": spearman(predicted_ranks, observed_ranks),
        "kendall_tau_b": kendall_tau_b(predicted_ranks, observed_ranks),
    }
    for requested_k in ks:
        k = min(requested_k, len(rows))
        observed_top = {row.post_id for row in observed[:k]}
        predicted_top = {row.post_id for row in predicted[:k]}
        ideal_dcg = _dcg(observed, relevance, k)
        metrics[f"ndcg@{requested_k}"] = _dcg(predicted, relevance, k) / ideal_dcg
        metrics[f"top_k_overlap@{requested_k}"] = len(observed_top & predicted_top) / k
    return {
        "snapshot_id": rows[0].snapshot_id,
        "viewer_hash": rows[0].viewer_hash,
        "requested_at": rows[0].requested_at,
        "n": len(rows),
        "metrics": metrics,
        "observed_order": [row.post_id for row in observed],
        "predicted_order": [row.post_id for row in predicted],
    }


def _mean_metrics(groups: list[dict[str, object]]) -> dict[str, float]:
    names = sorted({name for group in groups for name in group["metrics"]})
    means = {}
    for name in names:
        values = [
            value
            for group in groups
            if math.isfinite(value := group["metrics"].get(name, float("nan")))
        ]
        means[name] = statistics.fmean(values) if values else float("nan")
    return means


def stratified_metrics(rows: list[FeedRow], ks: list[int]) -> dict[str, object]:
    output = {}
    by_snapshot: dict[str, list[FeedRow]] = defaultdict(list)
    for row in rows:
        by_snapshot[row.snapshot_id].append(row)
    for field in OPTIONAL_STRATA:
        cells: dict[str, list[dict[str, object]]] = defaultdict(list)
        for snapshot_rows in by_snapshot.values():
            by_value: dict[str, list[FeedRow]] = defaultdict(list)
            for row in snapshot_rows:
                by_value[getattr(row, field)].append(row)
            for value, subset in by_value.items():
                if len(subset) >= 3:
                    cells[value].append(snapshot_metrics(subset, ks))
        output[field] = {
            value: {
                "snapshot_groups": len(groups),
                "rows": sum(group["n"] for group in groups),
                "mean_metrics": _mean_metrics(groups),
            }
            for value, groups in sorted(cells.items())
        }
    return output


def build_report(path: Path, ks: list[int]) -> dict[str, object]:
    rows = load_rows(path)
    by_snapshot: dict[str, list[FeedRow]] = defaultdict(list)
    for row in rows:
        by_snapshot[row.snapshot_id].append(row)
    snapshots = [
        snapshot_metrics(snapshot_rows, ks)
        for _, snapshot_rows in sorted(by_snapshot.items())
    ]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "rows": len(rows),
            "snapshots": len(snapshots),
        },
        "tool": {
            "path": "scripts/evaluate_feed_snapshot.py",
            "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "schema_version": 1,
        },
        "k_values": ks,
        "mean_metrics": _mean_metrics(snapshots),
        "snapshots": snapshots,
        "strata": stratified_metrics(rows, ks),
        "limitations": [
            "Only displayed candidates are observed; unexposed posts are missing.",
            "Position, exposure, selection, and personalization biases are not removed.",
            "Agreement is observational and does not establish a causal ranking effect.",
            "The proxy score is not an internal Phoenix probability or production score.",
        ],
    }


def render_text(report: dict[str, object]) -> str:
    lines = [
        f"snapshots={report['input']['snapshots']} rows={report['input']['rows']}",
        f"input_sha256={report['input']['sha256']}",
        "mean metrics:",
    ]
    lines.extend(
        f"  {name}: {value:+.4f}" for name, value in report["mean_metrics"].items()
    )
    for snapshot in report["snapshots"]:
        lines.append(f"snapshot {snapshot['snapshot_id']} (n={snapshot['n']}):")
        lines.extend(
            f"  {name}: {value:+.4f}" for name, value in snapshot["metrics"].items()
        )
    lines.append("limitations: observational agreement only; no causal claim")
    return "\n".join(lines)


def parse_ks(value: str) -> list[int]:
    try:
        ks = sorted({int(item) for item in value.split(",")})
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--k must be comma-separated integers") from exc
    if not ks or any(k < 1 for k in ks):
        raise argparse.ArgumentTypeError("all --k values must be >= 1")
    return ks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--k", type=parse_ks, default=[5, 10], help="for example 5,10,20")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = build_report(args.csv_path, args.k)
    except (OSError, SnapshotError) as exc:
        print(f"evaluation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
