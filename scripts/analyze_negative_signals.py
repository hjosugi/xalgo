#!/usr/bin/env python3
"""Sweep negative Phoenix probabilities through the upstream offset formula.

Published artifacts do not contain production feature-switch weights.  Use
``--unit-negative-weights`` for a dimensionless sensitivity check, or provide
explicit ``--weight ACTION=VALUE`` overrides for a stated hypothesis.
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

from xalgo.score import (  # noqa: E402
    NEGATIVE_NORMALIZATION_ACTIONS,
    load_weights,
    normalization_sums,
    offset_score,
)

DEFAULT_PROBABILITIES = (0.0, 0.01, 0.05, 0.10, 0.25, 0.50, 1.0)


def _parse_csv_floats(raw: str, name: str) -> list[float]:
    try:
        values = [float(value.strip()) for value in raw.split(",") if value.strip()]
    except ValueError as exc:
        raise ValueError(f"{name} must be a comma-separated list of numbers") from exc
    if not values:
        raise ValueError(f"{name} must not be empty")
    if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values):
        raise ValueError(f"{name} values must be finite and between 0 and 1")
    return values


def _apply_overrides(weights: dict[str, float], overrides: Iterable[str]) -> None:
    for override in overrides:
        try:
            action, raw_value = override.split("=", 1)
            if action not in weights:
                raise KeyError(action)
            value = float(raw_value)
        except (KeyError, ValueError) as exc:
            raise ValueError(
                "--weight must use an action in the selected preset and a finite "
                "number, for example --weight report=-10"
            ) from exc
        if not math.isfinite(value):
            raise ValueError(f"Weight for '{action}' must be finite")
        weights[action] = value


def analyze_sensitivity(
    weights: dict[str, float],
    positive_score: float,
    probabilities: Iterable[float],
    negative_scores_offset: float,
) -> dict:
    """Analyze each negative signal alone and all negative signals together."""
    if not math.isfinite(positive_score) or positive_score < 0.0:
        raise ValueError("positive_score must be finite and non-negative")
    probability_values = list(probabilities)
    if not probability_values:
        raise ValueError("probabilities must not be empty")
    if any(
        not math.isfinite(value) or not 0.0 <= value <= 1.0
        for value in probability_values
    ):
        raise ValueError("probabilities must be finite and between 0 and 1")

    positive_sum, negative_sum, total_sum = normalization_sums(weights)
    configured = {
        action: weights.get(action, 0.0) for action in NEGATIVE_NORMALIZATION_ACTIONS
    }
    if not any(weight != 0.0 for weight in configured.values()):
        raise ValueError(
            "selected preset has no negative weights; pass "
            "--unit-negative-weights or explicit --weight overrides"
        )

    scenarios = []
    for action, weight in configured.items():
        points = []
        for probability in probability_values:
            combined = positive_score + (weight * probability)
            points.append(
                {
                    "probability": probability,
                    "combined_score": combined,
                    "offset_score": offset_score(
                        combined, weights, negative_scores_offset
                    ),
                }
            )
        scenarios.append(
            {
                "action": action,
                "weight": weight,
                "zero_crossing_probability": (
                    positive_score / -weight if weight < 0.0 else None
                ),
                "points": points,
            }
        )

    all_points = []
    negative_weight_sum = sum(configured.values())
    for probability in probability_values:
        combined = positive_score + (negative_weight_sum * probability)
        all_points.append(
            {
                "probability": probability,
                "combined_score": combined,
                "offset_score": offset_score(combined, weights, negative_scores_offset),
            }
        )

    return {
        "positive_score": positive_score,
        "negative_scores_offset": negative_scores_offset,
        "normalization": {
            "positive_sum": positive_sum,
            "negative_sum": negative_sum,
            "total_sum": total_sum,
        },
        "negative_weights": configured,
        "scenarios": scenarios,
        "all_negative_equal_probability": {
            "weight_sum": negative_weight_sum,
            "zero_crossing_probability": (
                positive_score / -negative_weight_sum
                if negative_weight_sum < 0.0
                else None
            ),
            "points": all_points,
        },
    }


def _bar(value: float, scale: float, width: int = 20) -> str:
    if scale <= 0.0:
        return ""
    count = min(width, round(max(value, 0.0) / scale * width))
    return "#" * count


def _print_report(report: dict) -> None:
    normalization = report["normalization"]
    print(
        "normalization: "
        f"positive_sum={normalization['positive_sum']:.4g} "
        f"negative_sum={normalization['negative_sum']:.4g} "
        f"total_sum={normalization['total_sum']:.4g} "
        f"offset={report['negative_scores_offset']:.4g}"
    )

    all_points = report["all_negative_equal_probability"]["points"]
    scale = max((point["offset_score"] for point in all_points), default=0.0)
    print("\nAll five negative signals at the same probability")
    print("p       combined       offset  chart")
    for point in all_points:
        print(
            f"{point['probability']:>4.2f}"
            f"  {point['combined_score']:>12.6f}"
            f"  {point['offset_score']:>11.6f}  "
            f"{_bar(point['offset_score'], scale)}"
        )

    print("\nPer-signal zero crossing (positive score cancelled)")
    for scenario in report["scenarios"]:
        crossing = scenario["zero_crossing_probability"]
        crossing_text = "never" if crossing is None else f"{crossing:.4f}"
        print(
            f"{scenario['action']:<16} "
            f"weight={scenario['weight']:>8.3g}  p={crossing_text}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "weights.json")
    parser.add_argument("--preset", default="full_template")
    parser.add_argument(
        "--positive-score",
        type=float,
        default=0.1,
        help="combined contribution from positive actions before negatives",
    )
    parser.add_argument(
        "--probabilities",
        default=",".join(map(str, DEFAULT_PROBABILITIES)),
        help="comma-separated probability sweep in [0,1]",
    )
    parser.add_argument(
        "--negative-scores-offset",
        type=float,
        default=None,
        help="override weights.json negative_scores_offset",
    )
    parser.add_argument(
        "--weight",
        action="append",
        default=[],
        metavar="ACTION=NUMBER",
        help="override a selected-preset weight; repeatable",
    )
    parser.add_argument(
        "--unit-negative-weights",
        action="store_true",
        help="set all five negative weights to -1 for dimensionless sensitivity",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        preset_name, configured_weights, config = load_weights(args.config, args.preset)
        weights = dict(configured_weights)
        if args.unit_negative_weights:
            for action in NEGATIVE_NORMALIZATION_ACTIONS:
                if action not in weights:
                    raise ValueError(
                        f"preset '{preset_name}' does not define '{action}'"
                    )
                weights[action] = -1.0
        _apply_overrides(weights, args.weight)
        probabilities = _parse_csv_floats(args.probabilities, "probabilities")
        configured_offset = config.get("negative_scores_offset", 0.0)
        offset = (
            float(configured_offset)
            if args.negative_scores_offset is None
            else args.negative_scores_offset
        )
        report = analyze_sensitivity(
            weights, args.positive_score, probabilities, offset
        )
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    report["preset"] = preset_name
    report["parameter_status"] = (
        "hypothetical unit weights"
        if args.unit_negative_weights
        else "user/config supplied; production feature-switch values are unpublished"
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print(f"preset={preset_name} ({report['parameter_status']})")
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
