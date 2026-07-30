"""Audit public post-data backends without using the X API.

For every post this script queries FxTwitter, VxTwitter, and X's syndication
embed endpoint independently. It reports availability, latency, field coverage,
and pairwise count differences. The built-in 11-post snapshot is convenient for
a smoke test; use --stdin for a larger or less biased sample.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
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
from xalgo.fetch import (  # noqa: E402
    BackendAttempt,
    extract_status_id,
    fetch_all_backends,
)

COUNT_FIELDS = ("likes", "retweets", "replies", "quotes", "bookmarks", "views")
RECEIPT_POST_FIELDS = (
    "created_at",
    "likes",
    "retweets",
    "replies",
    "quotes",
    "bookmarks",
    "views",
    "has_video",
    "video_duration_ms",
)


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


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _cohort_sha256(status_ids: list[str]) -> str:
    return _sha256_bytes("".join(f"{status_id}\n" for status_id in status_ids).encode())


def _receipt_payload(
    records: list[dict],
    summary: dict,
    *,
    started_at: str,
    finished_at: str,
    source: dict | None = None,
) -> dict:
    """Build a content-minimized snapshot for repeated reliability analysis."""
    status_ids = [extract_status_id(record["input"]) for record in records]
    return {
        "schema_version": 1,
        "started_at": started_at,
        "finished_at": finished_at,
        "cohort": {
            "post_count": len(status_ids),
            "ordered_status_ids_sha256": _cohort_sha256(status_ids),
            "source": source,
        },
        "tool": {
            "path": "scripts/audit_backends.py",
            "sha256": _sha256_bytes(Path(__file__).read_bytes()),
        },
        "records": [
            {
                "status_id": status_id,
                "attempts": [
                    {
                        "backend": attempt.backend,
                        "elapsed_ms": attempt.elapsed_ms,
                        "ok": attempt.ok,
                        "error_class": (
                            attempt.error.split(":", 1)[0] if attempt.error else None
                        ),
                        "post": (
                            {
                                field: getattr(attempt.post, field)
                                for field in RECEIPT_POST_FIELDS
                            }
                            if attempt.post
                            else None
                        ),
                    }
                    for attempt in record["attempts"]
                ],
            }
            for status_id, record in zip(status_ids, records)
        ],
        "summary": summary,
        "privacy": (
            "Public status IDs and count fields only; post text, author identity, "
            "URLs, cookies, and credentials are excluded."
        ),
    }


def _read_input_file(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _normalize_items(items: list[str]) -> tuple[list[str], int]:
    status_ids = [extract_status_id(item) for item in items]
    unique_ids = list(dict.fromkeys(status_ids))
    return unique_ids, len(status_ids) - len(unique_ids)


def _write_receipt(path: Path, payload: dict, *, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(
            f"receipt already exists: {path}; pass --force to replace"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


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
        "--input-file",
        type=Path,
        help="read one URL/ID per line; blank lines and # comments are ignored",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit full machine-readable report"
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        help="write a content-minimized repeated-audit snapshot",
    )
    parser.add_argument(
        "--force", action="store_true", help="allow replacing an existing receipt"
    )
    parser.add_argument(
        "--min-posts",
        type=int,
        default=0,
        help="refuse to run when the deduplicated cohort is smaller",
    )
    parser.add_argument(
        "--delay", type=float, default=0.4, help="seconds between posts"
    )
    args = parser.parse_args(argv)

    input_modes = sum(
        bool(value) for value in (args.stdin, args.input_file, args.posts)
    )
    if input_modes > 1:
        parser.error("use only one of positional posts, --stdin, or --input-file")
    if args.min_posts < 0:
        parser.error("--min-posts must be non-negative")
    if args.delay < 0:
        parser.error("--delay must be non-negative")
    if args.stdin:
        items = [line.strip() for line in sys.stdin if line.strip()]
        source = {"kind": "stdin", "sha256": None}
    elif args.input_file:
        try:
            raw = args.input_file.read_bytes()
            items = _read_input_file(args.input_file)
        except OSError as exc:
            parser.error(str(exc))
        source = {
            "kind": "file",
            "name": args.input_file.name,
            "sha256": _sha256_bytes(raw),
        }
    elif args.posts:
        items = args.posts
        source = {"kind": "arguments", "sha256": None}
    else:
        items = [status_id for status_id, _ in SAMPLE]
        source = {"kind": "built_in_sample", "sha256": None}

    try:
        items, duplicate_count = _normalize_items(items)
    except ValueError as exc:
        parser.error(str(exc))
    if duplicate_count:
        print(f"ignored {duplicate_count} duplicate status IDs", file=sys.stderr)
    if len(items) < args.min_posts:
        parser.error(
            f"deduplicated cohort has {len(items)} posts; --min-posts requires "
            f"{args.min_posts}"
        )

    started_at = datetime.now(timezone.utc).isoformat()
    records, summary = audit(items, delay=args.delay)
    finished_at = datetime.now(timezone.utc).isoformat()
    if args.receipt:
        try:
            _write_receipt(
                args.receipt,
                _receipt_payload(
                    records,
                    summary,
                    started_at=started_at,
                    finished_at=finished_at,
                    source=source,
                ),
                force=args.force,
            )
        except OSError as exc:
            parser.error(str(exc))
    if args.json:
        print(json.dumps(_json_payload(records, summary), ensure_ascii=False, indent=2))
    else:
        _print_text(records, summary)

    successes = sum(attempt.ok for record in records for attempt in record["attempts"])
    return 0 if successes else 1


if __name__ == "__main__":
    sys.exit(main())
