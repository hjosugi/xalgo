#!/usr/bin/env python3
"""Sweep hypothetical VQV duration thresholds over videos or snapshot data.

The pinned upstream scorer applies ``VQV_WEIGHT`` only when
``video_duration_ms > MIN_VIDEO_DURATION_MS``.  The threshold and production
weight are unpublished, so this tool reports reproducible what-if eligibility
and observational view-growth splits without claiming to recover either value.

Snapshot CSV columns:
    post_id,video_duration_ms,observed_at,views

Each post must appear at least twice.  Credential-like columns are rejected.
Repeated privacy-minimized backend-audit receipts can be used instead of CSV.
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
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.analyze_backend_snapshots import (
    SnapshotError,
    aggregate_snapshots,
    load_snapshot,
)
from xalgo.score import vqv_weight_eligibility

DEFAULT_DURATIONS_MS = (2_000, 5_000, 10_000, 30_000, 60_000)
DEFAULT_THRESHOLDS_MS = (0, 2_000, 5_000, 10_000, 30_000, 60_000)
REQUIRED_COLUMNS = {"post_id", "video_duration_ms", "observed_at", "views"}
CREDENTIAL_COLUMN_PARTS = {
    "authorization",
    "cookie",
    "credential",
    "password",
    "session",
    "token",
}


@dataclass(frozen=True)
class Observation:
    post_id: str
    video_duration_ms: int
    observed_at: datetime
    views: int


def _parse_datetime(raw: str) -> datetime:
    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid observed_at timestamp: {raw!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError("observed_at timestamps must include a UTC offset or Z")
    return parsed


def _parse_non_negative_int(raw: str, field: str, row_number: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"row {row_number}: {field} must be an integer") from exc
    if value < 0:
        raise ValueError(f"row {row_number}: {field} must be non-negative")
    return value


def load_observations(path: Path) -> list[Observation]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("snapshot CSV has no header")
        field_map = {name.strip().lower(): name for name in reader.fieldnames}
        normalized = set(field_map)
        sensitive = sorted(
            name
            for name in normalized
            if any(part in name for part in CREDENTIAL_COLUMN_PARTS)
        )
        if sensitive:
            raise ValueError(
                "credential-like columns are forbidden: " + ", ".join(sensitive)
            )
        missing = sorted(REQUIRED_COLUMNS - normalized)
        if missing:
            raise ValueError("snapshot CSV is missing columns: " + ", ".join(missing))

        rows = []
        for row_number, row in enumerate(reader, start=2):
            post_id = (row.get(field_map["post_id"]) or "").strip()
            if not post_id:
                raise ValueError(f"row {row_number}: post_id must not be empty")
            rows.append(
                Observation(
                    post_id=post_id,
                    video_duration_ms=_parse_non_negative_int(
                        row.get(field_map["video_duration_ms"], ""),
                        "video_duration_ms",
                        row_number,
                    ),
                    observed_at=_parse_datetime(row.get(field_map["observed_at"], "")),
                    views=_parse_non_negative_int(
                        row.get(field_map["views"], ""), "views", row_number
                    ),
                )
            )
    if not rows:
        raise ValueError("snapshot CSV has no data rows")
    return rows


def load_backend_observations(
    paths: Iterable[Path], backend: str
) -> tuple[list[Observation], dict]:
    """Extract repeated public video observations from backend-audit receipts."""
    receipt_paths = list(paths)
    if len(receipt_paths) < 2:
        raise ValueError("at least two backend audit receipts are required")
    if not backend.strip():
        raise ValueError("backend must not be empty")

    snapshots = [load_snapshot(path) for path in receipt_paths]
    aggregate_snapshots(snapshots)
    snapshots.sort(key=lambda snapshot: _parse_datetime(snapshot["started_at"]))

    observations = []
    per_receipt = []
    for snapshot in snapshots:
        observed_at = _parse_datetime(snapshot["started_at"])
        receipt_counts = defaultdict(int)
        backend_present = False
        for record in snapshot["records"]:
            attempt = next(
                (item for item in record["attempts"] if item["backend"] == backend),
                None,
            )
            if attempt is None:
                receipt_counts["backend_attempt_missing"] += 1
                continue
            backend_present = True
            if not attempt["ok"]:
                receipt_counts["backend_failed"] += 1
                continue
            post = attempt["post"]
            if post.get("has_video") is not True:
                receipt_counts["not_video"] += 1
                continue
            duration = post.get("video_duration_ms")
            views = post.get("views")
            if duration is None:
                receipt_counts["missing_video_duration_ms"] += 1
                continue
            if views is None:
                receipt_counts["missing_views"] += 1
                continue
            if (
                isinstance(duration, bool)
                or not isinstance(duration, int)
                or duration < 0
            ):
                raise ValueError(
                    f"{snapshot['_receipt']['path']}: "
                    f"{record['status_id']} has invalid video_duration_ms"
                )
            if isinstance(views, bool) or not isinstance(views, int) or views < 0:
                raise ValueError(
                    f"{snapshot['_receipt']['path']}: "
                    f"{record['status_id']} has invalid views"
                )
            observations.append(
                Observation(
                    post_id=record["status_id"],
                    video_duration_ms=duration,
                    observed_at=observed_at,
                    views=views,
                )
            )
            receipt_counts["usable_video_observations"] += 1

        if not backend_present:
            raise ValueError(
                f"{snapshot['_receipt']['path']}: backend {backend!r} is absent"
            )
        per_receipt.append(
            {
                **snapshot["_receipt"],
                "started_at": snapshot["started_at"],
                "counts": dict(sorted(receipt_counts.items())),
            }
        )

    observation_counts: dict[str, int] = defaultdict(int)
    for observation in observations:
        observation_counts[observation.post_id] += 1
    repeated_ids = {
        post_id for post_id, count in observation_counts.items() if count >= 2
    }
    filtered = [
        observation
        for observation in observations
        if observation.post_id in repeated_ids
    ]
    if not filtered:
        raise ValueError(
            f"backend {backend!r} has no video posts with at least two "
            "duration-and-view observations"
        )

    return filtered, {
        "kind": "backend_audit_receipts",
        "backend": backend,
        "cohort": {
            "post_count": snapshots[0]["cohort"]["post_count"],
            "ordered_status_ids_sha256": snapshots[0]["cohort"][
                "ordered_status_ids_sha256"
            ],
        },
        "receipt_count": len(snapshots),
        "receipts": per_receipt,
        "raw_usable_observation_count": len(observations),
        "observation_count": len(filtered),
        "post_count": len(repeated_ids),
        "single_observation_post_count": sum(
            count == 1 for count in observation_counts.values()
        ),
    }


def summarize_posts(observations: Iterable[Observation]) -> list[dict]:
    grouped: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        grouped[observation.post_id].append(observation)

    posts = []
    for post_id, rows in sorted(grouped.items()):
        rows.sort(key=lambda row: row.observed_at)
        if len(rows) < 2:
            raise ValueError(f"post {post_id!r} needs at least two observations")
        durations = {row.video_duration_ms for row in rows}
        if len(durations) != 1:
            raise ValueError(
                f"post {post_id!r} has inconsistent video_duration_ms values"
            )
        elapsed_hours = (
            rows[-1].observed_at - rows[0].observed_at
        ).total_seconds() / 3600
        if elapsed_hours <= 0.0:
            raise ValueError(
                f"post {post_id!r} needs observations at distinct increasing times"
            )
        views_delta = rows[-1].views - rows[0].views
        posts.append(
            {
                "post_id": post_id,
                "video_duration_ms": durations.pop(),
                "observation_count": len(rows),
                "first_observed_at": rows[0].observed_at.isoformat(),
                "last_observed_at": rows[-1].observed_at.isoformat(),
                "elapsed_hours": elapsed_hours,
                "views_delta": views_delta,
                "views_per_hour": views_delta / elapsed_hours,
                "count_decreased": views_delta < 0,
            }
        )
    return posts


def _metric_summary(values: Iterable[float]) -> dict:
    data = list(values)
    return {
        "n": len(data),
        "mean_views_per_hour": statistics.fmean(data) if data else None,
        "median_views_per_hour": statistics.median(data) if data else None,
    }


def analyze_thresholds(
    durations_ms: Iterable[int],
    thresholds_ms: Iterable[int],
    vqv_probability: float,
    vqv_weight: float,
    posts: Iterable[dict] = (),
) -> dict:
    durations = list(durations_ms)
    thresholds = list(thresholds_ms)
    post_rows = list(posts)
    if not durations and not post_rows:
        raise ValueError("at least one video duration is required")
    if not thresholds:
        raise ValueError("thresholds_ms must not be empty")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in durations + thresholds
    ):
        raise ValueError("durations and thresholds must be non-negative integers")
    if not math.isfinite(vqv_probability) or not 0.0 <= vqv_probability <= 1.0:
        raise ValueError("vqv_probability must be finite and between 0 and 1")
    if not math.isfinite(vqv_weight):
        raise ValueError("vqv_weight must be finite")

    all_durations = durations or [row["video_duration_ms"] for row in post_rows]
    cases = []
    for threshold in thresholds:
        duration_cases = [
            {
                "video_duration_ms": duration,
                "eligible": bool(vqv_weight_eligibility(duration, threshold, 1.0)),
                "vqv_contribution": (
                    vqv_weight_eligibility(duration, threshold, vqv_weight)
                    * vqv_probability
                ),
            }
            for duration in all_durations
        ]
        eligible_posts = [
            row
            for row in post_rows
            if vqv_weight_eligibility(row["video_duration_ms"], threshold, 1.0) != 0.0
        ]
        ineligible_posts = [
            row
            for row in post_rows
            if vqv_weight_eligibility(row["video_duration_ms"], threshold, 1.0) == 0.0
        ]
        eligible_growth = _metric_summary(
            row["views_per_hour"] for row in eligible_posts
        )
        ineligible_growth = _metric_summary(
            row["views_per_hour"] for row in ineligible_posts
        )
        mean_difference = None
        if (
            eligible_growth["mean_views_per_hour"] is not None
            and ineligible_growth["mean_views_per_hour"] is not None
        ):
            mean_difference = (
                eligible_growth["mean_views_per_hour"]
                - ineligible_growth["mean_views_per_hour"]
            )
        cases.append(
            {
                "threshold_ms": threshold,
                "predicate": f"video_duration_ms > {threshold}",
                "eligible_duration_count": sum(
                    item["eligible"] for item in duration_cases
                ),
                "duration_cases": duration_cases,
                "observed_growth": {
                    "eligible": eligible_growth,
                    "ineligible": ineligible_growth,
                    "mean_difference_views_per_hour": mean_difference,
                },
            }
        )

    return {
        "upstream_contract": {
            "repository": "xai-org/x-algorithm",
            "commit": "0bfc2795d308f90032544322747caacd535f75ae",
            "predicate": "video_duration_ms > MIN_VIDEO_DURATION_MS",
            "production_threshold": "unpublished",
            "production_vqv_weight": "unpublished",
        },
        "assumptions": {
            "vqv_probability": vqv_probability,
            "vqv_weight": vqv_weight,
            "eligible_vqv_contribution": vqv_probability * vqv_weight,
        },
        "posts": post_rows,
        "thresholds": cases,
        "limitations": [
            (
                "Public view growth is post-exposure observational data, not a "
                "Phoenix prediction or a randomized estimate of VQV treatment."
            ),
            (
                "Duration, author, topic, posting time, candidate selection, and "
                "exposure are confounded; a group difference does not identify "
                "the production threshold."
            ),
            "The production threshold and feature-switch VQV weight are unpublished.",
        ],
    }


def _parse_int_list(raw: str, name: str) -> list[int]:
    try:
        values = [int(value.strip()) for value in raw.split(",") if value.strip()]
    except ValueError as exc:
        raise ValueError(f"{name} must be a comma-separated list of integers") from exc
    if not values or any(value < 0 for value in values):
        raise ValueError(f"{name} must contain non-negative integers")
    return values


def _print_report(report: dict) -> None:
    assumptions = report["assumptions"]
    print(
        "hypothesis: "
        f"vqv_p={assumptions['vqv_probability']:.4g} "
        f"vqv_weight={assumptions['vqv_weight']:.4g} "
        f"eligible_contribution={assumptions['eligible_vqv_contribution']:.6g}"
    )
    print(
        "\nthreshold_ms  eligible  ineligible_growth/h  eligible_growth/h  difference/h"
    )
    for case in report["thresholds"]:
        observed = case["observed_growth"]
        ineligible = observed["ineligible"]["mean_views_per_hour"]
        eligible = observed["eligible"]["mean_views_per_hour"]
        difference = observed["mean_difference_views_per_hour"]

        def fmt(value: float | None) -> str:
            return "-" if value is None else f"{value:.3f}"

        print(
            f"{case['threshold_ms']:>12}"
            f"  {case['eligible_duration_count']:>8}"
            f"  {fmt(ineligible):>19}"
            f"  {fmt(eligible):>17}"
            f"  {fmt(difference):>12}"
        )
    print(
        "\nNote: observed group differences are exploratory and do not identify "
        "the unpublished production threshold."
    )


def _write_json(path: Path, report: dict, *, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"output already exists: {path}; pass --force to replace")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--durations-ms",
        default=None,
        help=(
            "comma-separated video durations for an eligibility sweep; defaults "
            "to built-in examples without --snapshots and CSV durations with it"
        ),
    )
    parser.add_argument(
        "--thresholds-ms",
        default=",".join(map(str, DEFAULT_THRESHOLDS_MS)),
        help="comma-separated hypothetical MIN_VIDEO_DURATION_MS values",
    )
    parser.add_argument(
        "--snapshots",
        type=Path,
        help="optional repeated snapshot CSV for observational view-growth splits",
    )
    parser.add_argument(
        "--backend-receipt",
        action="append",
        type=Path,
        help=(
            "privacy-minimized backend audit receipt; repeat for two or more "
            "time-separated receipts (mutually exclusive with --snapshots)"
        ),
    )
    parser.add_argument(
        "--backend",
        default="fxtwitter",
        help="backend to extract from --backend-receipt (default: fxtwitter)",
    )
    parser.add_argument("--vqv-p", type=float, default=0.1)
    parser.add_argument("--vqv-weight", type=float, default=1.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--force", action="store_true", help="allow replacing an existing output"
    )
    args = parser.parse_args(argv)

    try:
        if args.snapshots is not None and args.backend_receipt is not None:
            raise ValueError("--snapshots and --backend-receipt are mutually exclusive")
        thresholds = _parse_int_list(args.thresholds_ms, "thresholds_ms")
        posts = []
        input_meta = None
        if args.snapshots is not None:
            observations = load_observations(args.snapshots)
            posts = summarize_posts(observations)
            input_meta = {
                "path": str(args.snapshots),
                "sha256": hashlib.sha256(args.snapshots.read_bytes()).hexdigest(),
                "observation_count": len(observations),
                "post_count": len(posts),
            }
        elif args.backend_receipt is not None:
            observations, input_meta = load_backend_observations(
                args.backend_receipt, args.backend
            )
            posts = summarize_posts(observations)
        durations = (
            _parse_int_list(args.durations_ms, "durations_ms")
            if args.durations_ms is not None
            else ([] if posts else list(DEFAULT_DURATIONS_MS))
        )
        report = analyze_thresholds(
            durations, thresholds, args.vqv_p, args.vqv_weight, posts
        )
        report["input"] = input_meta
        report["tool"] = {
            "path": str(Path(__file__).relative_to(ROOT)),
            "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        if args.output is not None:
            _write_json(args.output, report, force=args.force)
    except (OSError, SnapshotError, ValueError) as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
