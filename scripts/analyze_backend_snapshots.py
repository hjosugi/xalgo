"""Aggregate repeated backend-audit receipts for a fixed post cohort.

This tool refuses to compare different cohorts. It reports reliability,
latency, field coverage, count consistency, and whether Issue #5's minimum
100-post / three-UTC-hour observation gate has been met.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

COUNT_FIELDS = ("likes", "retweets", "replies", "quotes", "bookmarks", "views")
CURRENT_BACKEND_ORDER = ("fxtwitter", "vxtwitter", "syndication")
AUDITED_TIMEOUT_SECONDS = 12
RECOMMENDED_TIMEOUT_SECONDS = 5


class SnapshotError(ValueError):
    """Raised when an audit receipt is invalid or cannot be compared."""


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise SnapshotError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SnapshotError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise SnapshotError(f"{field} must be a finite number")
    return number


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise SnapshotError(f"{field} must be an ISO-8601 timestamp")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotError(f"{field} must be an ISO-8601 timestamp") from exc
    if timestamp.tzinfo is None:
        raise SnapshotError(f"{field} must include a timezone")
    return timestamp


def _cohort_sha256(status_ids: list[str]) -> str:
    raw = "".join(f"{status_id}\n" for status_id in status_ids).encode()
    return hashlib.sha256(raw).hexdigest()


def _created_date(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        try:
            return (
                datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
            )
        except ValueError:
            return None


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _wilson_interval(successes: int, attempts: int) -> list[float] | None:
    if attempts == 0:
        return None
    z = 1.959963984540054
    rate = successes / attempts
    denominator = 1.0 + (z * z / attempts)
    center = (rate + (z * z / (2 * attempts))) / denominator
    margin = (
        z
        * math.sqrt(
            (rate * (1.0 - rate) / attempts) + (z * z / (4 * attempts * attempts))
        )
        / denominator
    )
    return [max(0.0, center - margin), min(1.0, center + margin)]


def load_snapshot(path: Path) -> dict:
    """Load and validate one privacy-minimized audit receipt."""
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"{path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise SnapshotError(f"{path}: unsupported or missing schema_version")

    _parse_timestamp(payload.get("started_at"), f"{path}: started_at")
    _parse_timestamp(payload.get("finished_at"), f"{path}: finished_at")
    cohort = payload.get("cohort")
    records = payload.get("records")
    if not isinstance(cohort, dict) or not isinstance(records, list):
        raise SnapshotError(f"{path}: cohort and records are required")
    post_count = cohort.get("post_count")
    if (
        isinstance(post_count, bool)
        or not isinstance(post_count, int)
        or post_count != len(records)
    ):
        raise SnapshotError(f"{path}: cohort.post_count must equal record count")

    status_ids = []
    for row_index, record in enumerate(records):
        if not isinstance(record, dict):
            raise SnapshotError(f"{path}: records[{row_index}] must be an object")
        status_id = record.get("status_id")
        if not isinstance(status_id, str) or not status_id.isdigit():
            raise SnapshotError(
                f"{path}: records[{row_index}].status_id must be numeric text"
            )
        status_ids.append(status_id)
        attempts = record.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise SnapshotError(
                f"{path}: records[{row_index}].attempts must be non-empty"
            )
        seen_backends = set()
        for attempt_index, attempt in enumerate(attempts):
            field = f"{path}: records[{row_index}].attempts[{attempt_index}]"
            if not isinstance(attempt, dict):
                raise SnapshotError(f"{field} must be an object")
            backend = attempt.get("backend")
            if not isinstance(backend, str) or not backend:
                raise SnapshotError(f"{field}.backend must be non-empty text")
            if backend in seen_backends:
                raise SnapshotError(f"{field}: duplicate backend {backend}")
            seen_backends.add(backend)
            elapsed_ms = _finite_number(
                attempt.get("elapsed_ms"), f"{field}.elapsed_ms"
            )
            if elapsed_ms < 0:
                raise SnapshotError(f"{field}.elapsed_ms must be non-negative")
            if not isinstance(attempt.get("ok"), bool):
                raise SnapshotError(f"{field}.ok must be boolean")
            post = attempt.get("post")
            if attempt["ok"] != isinstance(post, dict):
                raise SnapshotError(f"{field}.post must agree with ok")

    if len(status_ids) != len(set(status_ids)):
        raise SnapshotError(f"{path}: duplicate status IDs")
    expected_hash = _cohort_sha256(status_ids)
    if cohort.get("ordered_status_ids_sha256") != expected_hash:
        raise SnapshotError(f"{path}: cohort hash does not match records")

    payload["_receipt"] = {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return payload


def aggregate_snapshots(snapshots: list[dict]) -> dict:
    """Aggregate validated snapshots, requiring one ordered cohort."""
    if not snapshots:
        raise SnapshotError("at least one snapshot is required")

    cohort_hashes = {
        snapshot["cohort"]["ordered_status_ids_sha256"] for snapshot in snapshots
    }
    post_counts = {snapshot["cohort"]["post_count"] for snapshot in snapshots}
    if len(cohort_hashes) != 1 or len(post_counts) != 1:
        raise SnapshotError("all snapshots must use the same ordered cohort")

    ordered = sorted(
        snapshots,
        key=lambda snapshot: _parse_timestamp(
            snapshot["started_at"], "snapshot.started_at"
        ),
    )
    timestamps = [
        _parse_timestamp(snapshot["started_at"], "snapshot.started_at")
        for snapshot in ordered
    ]
    if len(timestamps) != len(set(timestamps)):
        raise SnapshotError("snapshot started_at values must be unique")

    backend_data: dict[str, dict] = defaultdict(
        lambda: {
            "attempts": 0,
            "successes": 0,
            "all_latencies_ms": [],
            "success_latencies_ms": [],
            "field_coverage": Counter(),
            "failure_classes": Counter(),
        }
    )
    consistency_data: dict[str, dict] = defaultdict(
        lambda: {
            "comparisons": 0,
            "exact_matches": 0,
            "weighted_relative_delta": 0.0,
            "max_relative_delta": 0.0,
        }
    )
    cohort_profile: dict[str, dict] = {}
    snapshot_orders = []
    for snapshot in ordered:
        snapshot_orders.append(
            {
                "started_at": snapshot["started_at"],
                "recommended_order": snapshot["summary"][
                    "sample_based_recommended_order"
                ],
            }
        )
        for record in snapshot["records"]:
            if record["status_id"] not in cohort_profile:
                successful_posts = [
                    attempt["post"] for attempt in record["attempts"] if attempt["ok"]
                ]
                if successful_posts:
                    created_at = next(
                        (
                            post["created_at"]
                            for post in successful_posts
                            if post.get("created_at")
                        ),
                        None,
                    )
                    cohort_profile[record["status_id"]] = {
                        "created_date": _created_date(created_at),
                        "has_video": any(
                            bool(post.get("has_video")) for post in successful_posts
                        ),
                    }
            for attempt in record["attempts"]:
                data = backend_data[attempt["backend"]]
                data["attempts"] += 1
                data["all_latencies_ms"].append(float(attempt["elapsed_ms"]))
                if attempt["ok"]:
                    data["successes"] += 1
                    data["success_latencies_ms"].append(float(attempt["elapsed_ms"]))
                    for field in COUNT_FIELDS:
                        if attempt["post"].get(field) is not None:
                            data["field_coverage"][field] += 1
                else:
                    error_class = attempt.get("error_class") or "UnknownError"
                    data["failure_classes"][error_class] += 1

        for key, comparison in snapshot["summary"]["pairwise_consistency"].items():
            data = consistency_data[key]
            count = int(comparison["comparisons"])
            data["comparisons"] += count
            data["exact_matches"] += int(comparison["exact_matches"])
            data["weighted_relative_delta"] += (
                float(comparison["mean_relative_delta"]) * count
            )
            data["max_relative_delta"] = max(
                data["max_relative_delta"],
                float(comparison["max_relative_delta"]),
            )

    backend_summary = {}
    for backend, data in sorted(backend_data.items()):
        attempts = data["attempts"]
        successes = data["successes"]
        latencies = data["success_latencies_ms"]
        backend_summary[backend] = {
            "attempts": attempts,
            "successes": successes,
            "success_rate": successes / attempts if attempts else 0.0,
            "success_rate_wilson_95": _wilson_interval(successes, attempts),
            "mean_success_latency_ms": (
                statistics.fmean(latencies) if latencies else None
            ),
            "median_success_latency_ms": _quantile(latencies, 0.5),
            "p95_success_latency_ms": _quantile(latencies, 0.95),
            "max_attempt_latency_ms": max(data["all_latencies_ms"]),
            "timeout_failure_count": sum(
                count
                for error_class, count in data["failure_classes"].items()
                if "timeout" in error_class.casefold()
            ),
            "field_coverage": {
                field: {
                    "count": data["field_coverage"][field],
                    "rate": (
                        data["field_coverage"][field] / attempts if attempts else 0.0
                    ),
                }
                for field in COUNT_FIELDS
            },
            "failure_classes": dict(sorted(data["failure_classes"].items())),
        }

    aggregate_order = sorted(
        backend_summary,
        key=lambda backend: (
            -backend_summary[backend]["success_rate"],
            -backend_summary[backend]["field_coverage"]["views"]["count"],
            -sum(
                coverage["count"]
                for coverage in backend_summary[backend]["field_coverage"].values()
            ),
            backend_summary[backend]["mean_success_latency_ms"] or float("inf"),
        ),
    )
    consistency = {
        key: {
            "comparisons": data["comparisons"],
            "exact_matches": data["exact_matches"],
            "mean_relative_delta": (
                data["weighted_relative_delta"] / data["comparisons"]
                if data["comparisons"]
                else None
            ),
            "max_relative_delta": data["max_relative_delta"],
        }
        for key, data in sorted(consistency_data.items())
    }

    utc_hours = sorted(
        {
            timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%z")
            for timestamp in timestamps
        }
    )
    post_count = next(iter(post_counts))
    created_dates = Counter(
        profile["created_date"]
        for profile in cohort_profile.values()
        if profile["created_date"]
    )
    video_posts = sum(profile["has_video"] for profile in cohort_profile.values())
    non_video_posts = len(cohort_profile) - video_posts
    profile_summary = {
        "observable_posts": len(cohort_profile),
        "unavailable_on_all_backends": post_count - len(cohort_profile),
        "video_posts": video_posts,
        "non_video_posts": non_video_posts,
        "created_date_counts": dict(sorted(created_dates.items())),
    }
    criteria = {
        "same_ordered_cohort": True,
        "at_least_100_posts": post_count >= 100,
        "mixed_media_types_observed": video_posts > 0 and non_video_posts > 0,
        "at_least_3_created_dates": len(created_dates) >= 3,
        "at_least_3_snapshots": len(ordered) >= 3,
        "at_least_3_distinct_utc_hours": len(utc_hours) >= 3,
    }
    criteria["met"] = all(criteria.values())
    current_order = list(CURRENT_BACKEND_ORDER)
    if not criteria["met"]:
        decision = "collect more snapshots before changing fallback order or timeout"
    elif aggregate_order == current_order:
        decision = "retain current fallback order"
    else:
        decision = "aggregate evidence supports reviewing the fallback order"
    maximum_attempt_latency_ms = max(
        stats["max_attempt_latency_ms"] for stats in backend_summary.values()
    )
    timeout_failures = sum(
        stats["timeout_failure_count"] for stats in backend_summary.values()
    )
    if not criteria["met"]:
        recommended_timeout = AUDITED_TIMEOUT_SECONDS
        timeout_decision = "collect more snapshots before changing timeout"
    elif (
        timeout_failures == 0
        and maximum_attempt_latency_ms < RECOMMENDED_TIMEOUT_SECONDS * 1000
    ):
        recommended_timeout = RECOMMENDED_TIMEOUT_SECONDS
        timeout_decision = (
            f"reduce timeout from {AUDITED_TIMEOUT_SECONDS}s to "
            f"{RECOMMENDED_TIMEOUT_SECONDS}s"
        )
    else:
        recommended_timeout = AUDITED_TIMEOUT_SECONDS
        timeout_decision = f"retain {AUDITED_TIMEOUT_SECONDS}s timeout"

    return {
        "schema_version": 1,
        "cohort": {
            "post_count": post_count,
            "ordered_status_ids_sha256": next(iter(cohort_hashes)),
            "profile": profile_summary,
        },
        "snapshots": {
            "count": len(ordered),
            "started_at": [snapshot["started_at"] for snapshot in ordered],
            "distinct_utc_hours": utc_hours,
            "span_seconds": (max(timestamps) - min(timestamps)).total_seconds(),
            "receipts": [
                snapshot.get("_receipt")
                for snapshot in ordered
                if snapshot.get("_receipt")
            ],
            "per_snapshot_recommended_order": snapshot_orders,
        },
        "completion_criteria": criteria,
        "backends": backend_summary,
        "pairwise_consistency": consistency,
        "recommendation": {
            "current_order": current_order,
            "aggregate_order": aggregate_order,
            "decision": decision,
            "timeout": {
                "audited_seconds": AUDITED_TIMEOUT_SECONDS,
                "recommended_seconds": recommended_timeout,
                "maximum_attempt_latency_ms": maximum_attempt_latency_ms,
                "timeout_failure_count": timeout_failures,
                "decision": timeout_decision,
            },
        },
        "limitations": [
            (
                "Backend observations are unauthenticated public endpoint checks, "
                "not SLA data."
            ),
            "Count differences include growth during sequential requests.",
            (
                "A fixed public cohort may lose posts over time because of deletion "
                "or visibility changes."
            ),
        ],
    }


def _print_report(report: dict) -> None:
    snapshots = report["snapshots"]
    criteria = report["completion_criteria"]
    print(
        f"posts={report['cohort']['post_count']} "
        f"snapshots={snapshots['count']} "
        f"utc_hours={len(snapshots['distinct_utc_hours'])} "
        f"criteria_met={criteria['met']}"
    )
    print(
        f"{'backend':<14}{'ok/total':>12}{'success':>10}"
        f"{'median':>12}{'p95':>12}{'views':>10}"
    )
    for backend, stats in report["backends"].items():
        median = stats["median_success_latency_ms"]
        p95 = stats["p95_success_latency_ms"]
        print(
            f"{backend:<14}{stats['successes']:>4}/{stats['attempts']:<7}"
            f"{stats['success_rate']:>9.1%}"
            f"{(f'{median:.0f} ms' if median is not None else '-'):>12}"
            f"{(f'{p95:.0f} ms' if p95 is not None else '-'):>12}"
            f"{stats['field_coverage']['views']['rate']:>9.1%}"
        )
    order = " -> ".join(report["recommendation"]["aggregate_order"])
    print(f"\naggregate order: {order}")
    print(f"decision: {report['recommendation']['decision']}")
    timeout = report["recommendation"]["timeout"]
    print(
        "timeout: "
        f"{timeout['audited_seconds']}s -> {timeout['recommended_seconds']}s "
        f"({timeout['decision']})"
    )


def _write_json(path: Path, payload: dict, *, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"output already exists: {path}; pass --force to replace")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshots", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--force", action="store_true", help="allow replacing an existing output"
    )
    args = parser.parse_args(argv)

    try:
        report = aggregate_snapshots([load_snapshot(path) for path in args.snapshots])
        if args.output:
            _write_json(args.output, report, force=args.force)
    except (OSError, SnapshotError) as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
