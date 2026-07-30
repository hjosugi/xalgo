"""Validate and summarize a structured Phoenix probability export.

The public ``run_pipeline.py`` prints only a few selected output columns. Apply
``experiments/phoenix/export_probabilities.patch`` to the pinned upstream
checkout to export every column, then use this script to compute deterministic
quantiles and histogram counts.

Published ``runners.py`` labels are included only as references. They conflict
with the indices selected by ``run_pipeline.py`` and are not verified
checkpoint metadata.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

HISTOGRAM_BINS = (0.0, 0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0)
RUNNERS_ACTIONS = (
    "favorite_score",
    "reply_score",
    "repost_score",
    "photo_expand_score",
    "click_score",
    "profile_click_score",
    "vqv_score",
    "share_score",
    "share_via_dm_score",
    "share_via_copy_link_score",
    "dwell_score",
    "quote_score",
    "quoted_click_score",
    "follow_author_score",
    "not_interested_score",
    "block_author_score",
    "mute_author_score",
    "report_score",
    "dwell_time",
)
PROXY_ACTIONS = ("favorite", "reply", "retweet")


class ProbabilityExportError(ValueError):
    """Raised when a probability export does not satisfy its schema."""


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ProbabilityExportError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ProbabilityExportError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise ProbabilityExportError(f"{field} must be a finite number")
    return number


def _quantile(sorted_values: list[float], fraction: float) -> float:
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def describe_values(values: Iterable[float]) -> dict[str, Any]:
    """Return deterministic descriptive statistics and fixed-bin counts."""
    numbers = sorted(float(value) for value in values)
    if not numbers:
        raise ProbabilityExportError("cannot summarize an empty value sequence")
    if any(not math.isfinite(value) for value in numbers):
        raise ProbabilityExportError("summary values must be finite")

    counts = [0] * (len(HISTOGRAM_BINS) - 1)
    for value in numbers:
        if not 0.0 <= value <= 1.0:
            raise ProbabilityExportError("probability values must be between 0 and 1")
        index = bisect.bisect_right(HISTOGRAM_BINS, value) - 1
        index = min(index, len(counts) - 1)
        counts[index] += 1

    return {
        "count": len(numbers),
        "mean": sum(numbers) / len(numbers),
        "min": numbers[0],
        "p05": _quantile(numbers, 0.05),
        "p25": _quantile(numbers, 0.25),
        "median": _quantile(numbers, 0.50),
        "p75": _quantile(numbers, 0.75),
        "p95": _quantile(numbers, 0.95),
        "max": numbers[-1],
        "histogram_counts": counts,
    }


def analyze_probability_export(
    payload: Any, *, input_sha256: str | None = None
) -> dict[str, Any]:
    """Validate the instrumentation export and summarize every output column."""
    if not isinstance(payload, dict):
        raise ProbabilityExportError("export root must be a JSON object")
    if payload.get("schema_version") != 1:
        raise ProbabilityExportError("unsupported or missing schema_version")

    num_actions = payload.get("num_actions")
    if (
        isinstance(num_actions, bool)
        or not isinstance(num_actions, int)
        or num_actions <= 0
    ):
        raise ProbabilityExportError("num_actions must be a positive integer")

    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ProbabilityExportError("candidates must be a non-empty list")

    columns: list[list[float]] = [[] for _ in range(num_actions)]
    seen_post_ids: set[int] = set()
    retrieval_scores = []
    for row_index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise ProbabilityExportError(f"candidates[{row_index}] must be an object")
        post_id = candidate.get("post_id")
        if isinstance(post_id, bool) or not isinstance(post_id, int):
            raise ProbabilityExportError(
                f"candidates[{row_index}].post_id must be an integer"
            )
        if post_id in seen_post_ids:
            raise ProbabilityExportError(f"duplicate post_id in export: {post_id}")
        seen_post_ids.add(post_id)

        retrieval_scores.append(
            _finite_number(
                candidate.get("retrieval_score"),
                f"candidates[{row_index}].retrieval_score",
            )
        )
        probabilities = candidate.get("probabilities_by_column")
        if not isinstance(probabilities, list) or len(probabilities) != num_actions:
            raise ProbabilityExportError(
                f"candidates[{row_index}].probabilities_by_column must contain "
                f"{num_actions} values"
            )
        for column_index, raw_value in enumerate(probabilities):
            value = _finite_number(
                raw_value,
                f"candidates[{row_index}].probabilities_by_column[{column_index}]",
            )
            if not 0.0 <= value <= 1.0:
                raise ProbabilityExportError(
                    f"probability at candidate {row_index}, column "
                    f"{column_index} is outside [0, 1]"
                )
            columns[column_index].append(value)

    column_summaries = []
    for index, values in enumerate(columns):
        summary = describe_values(values)
        summary["column"] = index
        summary["published_runners_label"] = (
            RUNNERS_ACTIONS[index] if index < len(RUNNERS_ACTIONS) else None
        )
        column_summaries.append(summary)

    report: dict[str, Any] = {
        "schema_version": 1,
        "input_sha256": input_sha256,
        "candidate_count": len(candidates),
        "output_column_count": num_actions,
        "retrieval_score": {
            "min": min(retrieval_scores),
            "max": max(retrieval_scores),
        },
        "histogram_bins": list(HISTOGRAM_BINS),
        "columns": column_summaries,
        "label_status": (
            "published runners.py labels only; run_pipeline.py uses conflicting "
            "indices and the checkpoint has no semantic head metadata"
        ),
        "limitations": [
            "The export uses one synthetic example viewer history.",
            "The bundled corpus contains sports candidates only.",
            (
                "Public count rates are post-exposure aggregates, not "
                "viewer-specific Phoenix predictions."
            ),
        ],
    }
    return report


def analyze_proxy_payload(payload: Any) -> dict[str, Any]:
    """Aggregate public-count rates emitted by validate_popular.py --json."""
    if not isinstance(payload, dict):
        raise ProbabilityExportError("proxy root must be a JSON object")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ProbabilityExportError("proxy rows must be a non-empty list")

    values: dict[str, list[float]] = {action: [] for action in PROXY_ACTIONS}
    for row_index, row in enumerate(rows):
        try:
            p_hat = row["result"]["p_hat"]
        except (KeyError, TypeError) as exc:
            raise ProbabilityExportError(
                f"proxy rows[{row_index}] is missing result.p_hat"
            ) from exc
        for action in PROXY_ACTIONS:
            value = _finite_number(
                p_hat.get(action), f"proxy rows[{row_index}].p_hat.{action}"
            )
            if not 0.0 <= value <= 1.0:
                raise ProbabilityExportError(
                    f"proxy rate for {action} at row {row_index} is outside [0, 1]"
                )
            values[action].append(value)

    return {
        "row_count": len(rows),
        "fetched_at": payload.get("fetched_at"),
        "sample_source": payload.get("sample_source"),
        "rates": {
            action: describe_values(action_values)
            for action, action_values in values.items()
        },
        "comparability": (
            "marginal descriptive comparison only; candidates, viewers, exposure "
            "times, and action-head labels are not matched"
        ),
    }


def _read_json(path: Path) -> tuple[Any, str]:
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _print_report(report: dict[str, Any]) -> None:
    retrieval = report["retrieval_score"]
    print(
        f"candidates={report['candidate_count']} "
        f"columns={report['output_column_count']} "
        f"retrieval=[{retrieval['min']:.6g}, {retrieval['max']:.6g}]"
    )
    print(f"input_sha256={report['input_sha256']}")
    print(f"labels: {report['label_status']}")
    print(
        "\ncol  runners.py label             mean       median        p95        max  bins"
    )
    for column in report["columns"]:
        label = column["published_runners_label"] or "-"
        counts = ",".join(str(count) for count in column["histogram_counts"])
        print(
            f"{column['column']:>3}  {label:<26}"
            f"{column['mean']:>10.4g} {column['median']:>12.4g}"
            f"{column['p95']:>11.4g} {column['max']:>10.4g}  {counts}"
        )

    if "public_proxy" in report:
        proxy = report["public_proxy"]
        print(
            f"\npublic proxy rows={proxy['row_count']} fetched_at={proxy['fetched_at']}"
        )
        for action, summary in proxy["rates"].items():
            print(
                f"{action:<10} mean={summary['mean']:.4g} "
                f"median={summary['median']:.4g} "
                f"p95={summary['p95']:.4g}"
            )
        print(f"comparison: {proxy['comparability']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probabilities_json", type=Path)
    parser.add_argument(
        "--proxy-json",
        type=Path,
        help="optional validate_popular.py --json result for marginal comparison",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        payload, input_sha256 = _read_json(args.probabilities_json)
        report = analyze_probability_export(payload, input_sha256=input_sha256)
        if args.proxy_json:
            proxy_payload, proxy_sha256 = _read_json(args.proxy_json)
            report["public_proxy"] = analyze_proxy_payload(proxy_payload)
            report["public_proxy"]["input_sha256"] = proxy_sha256
    except (OSError, json.JSONDecodeError, ProbabilityExportError) as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
