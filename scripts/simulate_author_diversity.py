#!/usr/bin/env python3
"""Simulate the upstream author-diversity multiplier over a candidate set.

The "burst" case places all target-author posts in one feed response.  The
"distributed" comparison places each target post in a separate response, so
the per-response author counter resets and its multiplier remains 1.0.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from xalgo.score import author_diversity_multiplier  # noqa: E402

DEFAULT_AUTHOR_SCORES = (1.00, 0.94, 0.88)
DEFAULT_COMPETITOR_SCORES = (0.98, 0.92, 0.86, 0.80, 0.74)
DEFAULT_DECAYS = (0.5, 0.7, 0.9)
DEFAULT_FLOORS = (0.0, 0.2, 0.4)


def _validate_scores(name: str, values: Iterable[float]) -> list[float]:
    scores = list(values)
    if not scores:
        raise ValueError(f"{name} must contain at least one score")
    if any(not math.isfinite(value) or value < 0.0 for value in scores):
        raise ValueError(f"{name} must contain finite, non-negative scores")
    return scores


def simulate_case(
    author_scores: Iterable[float],
    competitor_scores: Iterable[float],
    decay: float,
    floor: float,
    top_k: int,
) -> dict:
    """Return burst/distributed ranks for one decay/floor pair."""
    author = _validate_scores("author_scores", author_scores)
    competitors = _validate_scores("competitor_scores", competitor_scores)
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    candidates = [
        {
            "id": f"target_{index + 1}",
            "author": "target",
            "base_score": score,
            "input_order": index,
        }
        for index, score in enumerate(author)
    ]
    candidates.extend(
        {
            "id": f"competitor_{index + 1}",
            "author": f"competitor_{index + 1}",
            "base_score": score,
            "input_order": len(author) + index,
        }
        for index, score in enumerate(competitors)
    )

    raw_order = sorted(
        candidates, key=lambda item: (-item["base_score"], item["input_order"])
    )
    author_counts: dict[str, int] = {}
    for raw_rank, item in enumerate(raw_order, start=1):
        position = author_counts.get(item["author"], 0)
        author_counts[item["author"]] = position + 1
        multiplier = author_diversity_multiplier(position, decay, floor)
        item.update(
            {
                "raw_rank": raw_rank,
                "author_position": position,
                "multiplier": multiplier,
                "adjusted_score": item["base_score"] * multiplier,
            }
        )

    adjusted_order = sorted(
        raw_order, key=lambda item: (-item["adjusted_score"], item["input_order"])
    )
    adjusted_ranks = {
        item["id"]: rank for rank, item in enumerate(adjusted_order, start=1)
    }

    target_results = []
    for item in candidates[: len(author)]:
        multiplier = item["multiplier"]
        break_even_uplift = None if multiplier == 0.0 else (1.0 / multiplier) - 1.0
        distributed_rank = 1 + sum(score > item["base_score"] for score in competitors)
        target_results.append(
            {
                "id": item["id"],
                "base_score": item["base_score"],
                "raw_rank": item["raw_rank"],
                "author_position": item["author_position"],
                "multiplier": multiplier,
                "adjusted_score": item["adjusted_score"],
                "burst_rank": adjusted_ranks[item["id"]],
                "distributed_rank": distributed_rank,
                "rank_loss": adjusted_ranks[item["id"]] - distributed_rank,
                "break_even_score_uplift": break_even_uplift,
            }
        )

    finite_uplifts = [
        item["break_even_score_uplift"]
        for item in target_results
        if item["break_even_score_uplift"] is not None
    ]
    has_unbounded_uplift = any(
        item["break_even_score_uplift"] is None for item in target_results
    )
    return {
        "decay": decay,
        "floor": floor,
        "top_k": top_k,
        "burst_top_k": sum(item["burst_rank"] <= top_k for item in target_results),
        "distributed_top_k": sum(
            item["distributed_rank"] <= top_k for item in target_results
        ),
        "mean_rank_loss": sum(item["rank_loss"] for item in target_results)
        / len(target_results),
        "max_break_even_score_uplift": (
            None if has_unbounded_uplift else max(finite_uplifts)
        ),
        "has_unbounded_break_even_uplift": has_unbounded_uplift,
        "target_posts": target_results,
    }


def simulate_grid(
    author_scores: Iterable[float],
    competitor_scores: Iterable[float],
    decays: Iterable[float],
    floors: Iterable[float],
    top_k: int,
) -> list[dict]:
    decay_values = list(decays)
    floor_values = list(floors)
    if not decay_values or not floor_values:
        raise ValueError("decays and floors must not be empty")
    return [
        simulate_case(author_scores, competitor_scores, decay, floor, top_k)
        for decay in decay_values
        for floor in floor_values
    ]


def _parse_csv_floats(raw: str, name: str) -> list[float]:
    try:
        values = [float(value.strip()) for value in raw.split(",") if value.strip()]
    except ValueError as exc:
        raise ValueError(f"{name} must be a comma-separated list of numbers") from exc
    return _validate_scores(name, values)


def _load_reference(path: Path) -> tuple[float, float]:
    config = json.loads(path.read_text(encoding="utf-8"))
    values = config.get("author_diversity", {})
    return float(values.get("decay", 0.9)), float(values.get("floor", 0.2))


def _print_report(report: dict) -> None:
    print(
        "decay  floor  burst_topK  distributed_topK  mean_rank_loss  "
        "max_break_even_uplift"
    )
    for case in report["grid"]:
        max_uplift = case["max_break_even_score_uplift"]
        uplift_text = "unbounded" if max_uplift is None else f"{max_uplift:.1%}"
        print(
            f"{case['decay']:>5.2f}  {case['floor']:>5.2f}"
            f"  {case['burst_top_k']:>10}  {case['distributed_top_k']:>16}"
            f"  {case['mean_rank_loss']:>14.2f}"
            f"  {uplift_text:>22}"
        )

    reference = report["reference"]
    print(f"\nReference decay={reference['decay']:.2f}, floor={reference['floor']:.2f}")
    print("post      raw  multiplier  adjusted  burst_rank  split_rank  uplift")
    for item in reference["target_posts"]:
        uplift = item["break_even_score_uplift"]
        uplift_text = "unbounded" if uplift is None else f"{uplift:.1%}"
        print(
            f"{item['id']:<8}  {item['base_score']:>4.2f}"
            f"  {item['multiplier']:>10.3f}"
            f"  {item['adjusted_score']:>8.3f}"
            f"  {item['burst_rank']:>10}"
            f"  {item['distributed_rank']:>10}"
            f"  {uplift_text:>9}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--author-scores",
        default=",".join(map(str, DEFAULT_AUTHOR_SCORES)),
        help="comma-separated raw scores for repeated posts by one author",
    )
    parser.add_argument(
        "--competitor-scores",
        default=",".join(map(str, DEFAULT_COMPETITOR_SCORES)),
        help="comma-separated raw scores for one-post competitor authors",
    )
    parser.add_argument(
        "--decays",
        default=",".join(map(str, DEFAULT_DECAYS)),
        help="comma-separated decay grid",
    )
    parser.add_argument(
        "--floors",
        default=",".join(map(str, DEFAULT_FLOORS)),
        help="comma-separated floor grid",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--config", type=Path, default=ROOT / "weights.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        author_scores = _parse_csv_floats(args.author_scores, "author_scores")
        competitor_scores = _parse_csv_floats(
            args.competitor_scores, "competitor_scores"
        )
        decays = _parse_csv_floats(args.decays, "decays")
        floors = _parse_csv_floats(args.floors, "floors")
        reference_decay, reference_floor = _load_reference(args.config)
        grid = simulate_grid(
            author_scores, competitor_scores, decays, floors, args.top_k
        )
        reference = simulate_case(
            author_scores,
            competitor_scores,
            reference_decay,
            reference_floor,
            args.top_k,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    report = {
        "assumption": (
            "distributed means one target-author post per feed response; "
            "the author counter resets between responses"
        ),
        "author_scores": author_scores,
        "competitor_scores": competitor_scores,
        "grid": grid,
        "reference": reference,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
