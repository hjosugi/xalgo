"""Audit public post-data backends without using the X API.

For every post this script queries FxTwitter, VxTwitter, and X's syndication
embed endpoint independently. It reports availability, latency, field coverage,
and pairwise count differences. The built-in 11-post snapshot is convenient for
a smoke test; use --stdin for a larger or less biased sample.
"""

from __future__ import annotations

import argparse
import dataclasses
import itertools
import json
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.validate_popular import SAMPLE  # noqa: E402
from xalgo.fetch import BackendAttempt, fetch_all_backends  # noqa: E402

COUNT_FIELDS = ("likes", "retweets", "replies", "quotes", "bookmarks", "views")


def _relative_delta(left: int, right: int) -> float:
    return abs(left - right) / max(abs(left), abs(right), 1)


def summarize(records: list[dict]) -> dict:
    by_backend: dict[str, list[BackendAttempt]] = defaultdict(list)
    for record in records:
        for attempt in record["attempts"]:
            by_backend[attempt.backend].append(attempt)

    backend_summary = {}
    for backend, attempts in sorted(by_backend.items()):
        successes = [attempt for attempt in attempts if attempt.ok]
        coverage = {
            field: sum(
                attempt.post is not None and getattr(attempt.post, field) is not None
                for attempt in attempts
            )
            for field in COUNT_FIELDS
        }
        backend_summary[backend] = {
            "attempts": len(attempts),
            "successes": len(successes),
            "success_rate": len(successes) / len(attempts) if attempts else 0.0,
            "mean_success_latency_ms": (
                statistics.fmean(attempt.elapsed_ms for attempt in successes)
                if successes
                else None
            ),
            "field_coverage": coverage,
        }

    differences: dict[str, list[float]] = defaultdict(list)
    exact_matches: dict[str, int] = defaultdict(int)
    for record in records:
        successful = [attempt for attempt in record["attempts"] if attempt.post]
        for left, right in itertools.combinations(successful, 2):
            for field in COUNT_FIELDS:
                left_value = getattr(left.post, field)
                right_value = getattr(right.post, field)
                if left_value is None or right_value is None:
                    continue
                key = f"{left.backend}__{right.backend}__{field}"
                differences[key].append(_relative_delta(left_value, right_value))
                if left_value == right_value:
                    exact_matches[key] += 1

    consistency = {
        key: {
            "comparisons": len(values),
            "exact_matches": exact_matches[key],
            "mean_relative_delta": statistics.fmean(values),
            "max_relative_delta": max(values),
        }
        for key, values in sorted(differences.items())
    }

    # Prefer reliability first, then the fields needed for scoring, then latency.
    recommended_order = sorted(
        backend_summary,
        key=lambda backend: (
            -backend_summary[backend]["success_rate"],
            -backend_summary[backend]["field_coverage"]["views"],
            -sum(backend_summary[backend]["field_coverage"].values()),
            backend_summary[backend]["mean_success_latency_ms"] or float("inf"),
        ),
    )
    return {
        "posts": len(records),
        "backends": backend_summary,
        "pairwise_consistency": consistency,
        "sample_based_recommended_order": recommended_order,
    }


def audit(items: list[str], delay: float = 0.4) -> tuple[list[dict], dict]:
    records = []
    for item in items:
        try:
            attempts = fetch_all_backends(item)
            records.append({"input": item, "attempts": attempts})
        except ValueError as exc:
            print(f"skip {item}: {exc}", file=sys.stderr)
        if delay > 0:
            time.sleep(delay)
    return records, summarize(records)


def _json_payload(records: list[dict], summary: dict) -> dict:
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "records": [
            {
                "input": record["input"],
                "attempts": [
                    {
                        **dataclasses.asdict(attempt),
                        "ok": attempt.ok,
                    }
                    for attempt in record["attempts"]
                ],
            }
            for record in records
        ],
        "summary": summary,
    }


def _print_text(records: list[dict], summary: dict) -> None:
    print(f"posts={summary['posts']}")
    print(f"{'backend':<14}{'ok/total':>10}{'success':>10}{'latency':>12}{'views':>8}")
    for backend, stats in summary["backends"].items():
        latency = stats["mean_success_latency_ms"]
        latency_text = f"{latency:.0f} ms" if latency is not None else "-"
        print(
            f"{backend:<14}{stats['successes']:>3}/{stats['attempts']:<6}"
            f"{stats['success_rate']:>9.1%}{latency_text:>12}"
            f"{stats['field_coverage']['views']:>8}"
        )
    order = " -> ".join(summary["sample_based_recommended_order"])
    print(f"\nsample-based order: {order or '-'}")

    failures = [
        (record["input"], attempt.backend, attempt.error)
        for record in records
        for attempt in record["attempts"]
        if not attempt.ok
    ]
    if failures:
        print("\nfailures:")
        for item, backend, error in failures:
            print(f"- {item} [{backend}] {error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("posts", nargs="*", help="post URLs or numeric status IDs")
    parser.add_argument("--stdin", action="store_true", help="read one URL/ID per line")
    parser.add_argument(
        "--json", action="store_true", help="emit full machine-readable report"
    )
    parser.add_argument(
        "--delay", type=float, default=0.4, help="seconds between posts"
    )
    args = parser.parse_args(argv)

    if args.stdin:
        items = [line.strip() for line in sys.stdin if line.strip()]
    elif args.posts:
        items = args.posts
    else:
        items = [status_id for status_id, _ in SAMPLE]

    records, summary = audit(items, delay=args.delay)
    if args.json:
        print(json.dumps(_json_payload(records, summary), ensure_ascii=False, indent=2))
    else:
        _print_text(records, summary)

    successes = sum(attempt.ok for record in records for attempt in record["attempts"])
    return 0 if successes else 1


if __name__ == "__main__":
    sys.exit(main())
