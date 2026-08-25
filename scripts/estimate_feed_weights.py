#!/usr/bin/env python3
"""Estimate cohort-specific ranking coefficients from anonymized feed snapshots.

The estimator fits a pairwise logistic ranking model: for every pair of posts
shown in the same snapshot, the feature difference of the higher-ranked post
minus the lower-ranked post should receive a positive score.  A separate test
CSV can be supplied to prove author-disjoint held-out evaluation.

This tool never logs in to X and rejects cookies, tokens, raw viewer IDs, and
raw author IDs.  Estimated coefficients describe association in the supplied
cohort; they are not identified production feature-switch values.
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.evaluate_feed_snapshot import (  # noqa: E402
    FORBIDDEN_COLUMN_NAMES,
    FORBIDDEN_COLUMN_PARTS,
    SnapshotError,
    _parse_timestamp,
    kendall_tau_b,
    rankdata,
    spearman,
)
from xalgo.score import load_weights  # noqa: E402

REQUIRED_COLUMNS = {
    "snapshot_id",
    "viewer_hash",
    "requested_at",
    "position",
    "post_id",
    "author_hash",
}
FEATURE_PREFIX = "p_"
HASH_PREFIX = "sha256:"


@dataclass(frozen=True)
class RankRow:
    snapshot_id: str
    viewer_hash: str
    requested_at: str
    position: int
    post_id: str
    author_hash: str
    features: tuple[float, ...]


@dataclass(frozen=True)
class RankDataset:
    path: Path
    sha256: str
    feature_names: tuple[str, ...]
    rows: tuple[RankRow, ...]


def _validate_columns(columns: set[str]) -> tuple[str, ...]:
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
    features = tuple(
        sorted(column for column in columns if column.startswith(FEATURE_PREFIX))
    )
    if not features:
        raise SnapshotError("at least one p_ACTION feature column is required")
    invalid = [name for name in features if len(name) == len(FEATURE_PREFIX)]
    if invalid:
        raise SnapshotError("probability feature names must include an action after p_")
    return features


def _validate_hash(value: str, name: str, line_number: int) -> None:
    digest = value.removeprefix(HASH_PREFIX)
    if (
        not value.startswith(HASH_PREFIX)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest.lower())
    ):
        raise SnapshotError(
            f"{name} must be a sha256: prefix plus 64 hexadecimal characters "
            f"at CSV line {line_number}"
        )


def _validate_snapshot(rows: list[RankRow]) -> None:
    snapshot_id = rows[0].snapshot_id
    if len(rows) < 3:
        raise SnapshotError(f"snapshot {snapshot_id} needs at least 3 posts")
    if len({row.viewer_hash for row in rows}) != 1:
        raise SnapshotError(f"snapshot {snapshot_id} mixes viewer hashes")
    if len({row.requested_at for row in rows}) != 1:
        raise SnapshotError(f"snapshot {snapshot_id} mixes request timestamps")
    if len({row.position for row in rows}) != len(rows):
        raise SnapshotError(f"snapshot {snapshot_id} has duplicate positions")
    if len({row.post_id for row in rows}) != len(rows):
        raise SnapshotError(f"snapshot {snapshot_id} has duplicate post IDs")


def load_dataset(path: Path, min_rows: int) -> RankDataset:
    if min_rows < 3:
        raise SnapshotError("minimum row count must be at least 3")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        features = _validate_columns(set(reader.fieldnames or []))
        rows: list[RankRow] = []
        for line_number, raw in enumerate(reader, 2):
            try:
                position = int(raw["position"])
                values = tuple(float(raw[name]) for name in features)
            except (TypeError, ValueError) as exc:
                raise SnapshotError(
                    f"invalid number at CSV line {line_number}"
                ) from exc
            if position < 1:
                raise SnapshotError(f"position must be >= 1 at CSV line {line_number}")
            if any(
                not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values
            ):
                raise SnapshotError(
                    f"p_ACTION values must be finite probabilities in [0,1] at CSV line {line_number}"
                )
            cleaned = {
                name: (raw.get(name) or "").strip()
                for name in (
                    "snapshot_id",
                    "viewer_hash",
                    "requested_at",
                    "post_id",
                    "author_hash",
                )
            }
            for name, value in cleaned.items():
                if not value:
                    raise SnapshotError(f"{name} is empty at CSV line {line_number}")
            _validate_hash(cleaned["viewer_hash"], "viewer_hash", line_number)
            _validate_hash(cleaned["author_hash"], "author_hash", line_number)
            rows.append(
                RankRow(
                    snapshot_id=cleaned["snapshot_id"],
                    viewer_hash=cleaned["viewer_hash"],
                    requested_at=_parse_timestamp(cleaned["requested_at"]),
                    position=position,
                    post_id=cleaned["post_id"],
                    author_hash=cleaned["author_hash"],
                    features=values,
                )
            )
    if len(rows) < min_rows:
        raise SnapshotError(
            f"dataset needs at least {min_rows} rows; found {len(rows)}"
        )
    grouped: dict[str, list[RankRow]] = defaultdict(list)
    for row in rows:
        grouped[row.snapshot_id].append(row)
    for snapshot_rows in grouped.values():
        _validate_snapshot(snapshot_rows)
    return RankDataset(
        path=path,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        feature_names=features,
        rows=tuple(rows),
    )


def validate_author_disjoint(train: RankDataset, test: RankDataset) -> dict[str, int]:
    if train.feature_names != test.feature_names:
        raise SnapshotError("train and test CSVs must have identical p_ACTION columns")
    train_authors = {row.author_hash for row in train.rows}
    test_authors = {row.author_hash for row in test.rows}
    overlap = train_authors & test_authors
    if overlap:
        raise SnapshotError(
            f"author-disjoint validation failed: {len(overlap)} author hash(es) overlap"
        )
    overlapping_posts = {row.post_id for row in train.rows} & {
        row.post_id for row in test.rows
    }
    if overlapping_posts:
        raise SnapshotError(
            f"held-out validation failed: {len(overlapping_posts)} post ID(s) overlap"
        )
    return {
        "train_unique_authors": len(train_authors),
        "test_unique_authors": len(test_authors),
        "overlapping_authors": 0,
        "overlapping_posts": 0,
    }


def pairwise_differences(dataset: RankDataset) -> list[tuple[float, ...]]:
    grouped: dict[str, list[RankRow]] = defaultdict(list)
    for row in dataset.rows:
        grouped[row.snapshot_id].append(row)
    pairs = []
    for rows in grouped.values():
        ordered = sorted(rows, key=lambda row: row.position)
        for higher_index, higher in enumerate(ordered):
            for lower in ordered[higher_index + 1 :]:
                difference = tuple(
                    high - low for high, low in zip(higher.features, lower.features)
                )
                if any(value != 0.0 for value in difference):
                    pairs.append(difference)
    if not pairs:
        raise SnapshotError("no informative within-snapshot feature pairs")
    return pairs


def _negative_logistic_slope(margin: float) -> float:
    if margin >= 0.0:
        exp_negative = math.exp(-margin)
        return exp_negative / (1.0 + exp_negative)
    return 1.0 / (1.0 + math.exp(margin))


def _logistic_loss(margin: float) -> float:
    return math.log1p(math.exp(-abs(margin))) + max(-margin, 0.0)


def fit_pairwise_logistic(
    pairs: list[tuple[float, ...]],
    *,
    epochs: int = 2000,
    learning_rate: float = 0.2,
    l2: float = 0.01,
    tolerance: float = 1e-10,
) -> tuple[list[float], dict[str, float | int]]:
    if not pairs or not pairs[0]:
        raise SnapshotError("pairwise training data is empty")
    if epochs < 1 or learning_rate <= 0.0 or l2 < 0.0 or tolerance < 0.0:
        raise SnapshotError("invalid optimizer configuration")
    width = len(pairs[0])
    if any(len(pair) != width for pair in pairs):
        raise SnapshotError("inconsistent pairwise feature width")
    scales = [
        math.sqrt(statistics.fmean(pair[index] ** 2 for pair in pairs))
        for index in range(width)
    ]
    scales = [scale if scale > 1e-12 else 1.0 for scale in scales]
    normalized = [
        tuple(value / scales[index] for index, value in enumerate(pair))
        for pair in pairs
    ]
    weights = [0.0] * width
    completed_epochs = 0
    for epoch in range(epochs):
        gradient = [l2 * weight for weight in weights]
        for pair in normalized:
            margin = sum(weight * value for weight, value in zip(weights, pair))
            slope = _negative_logistic_slope(margin)
            for index, value in enumerate(pair):
                gradient[index] -= slope * value / len(normalized)
        step = learning_rate / math.sqrt(1.0 + epoch / 200.0)
        updated = [weight - step * value for weight, value in zip(weights, gradient)]
        completed_epochs = epoch + 1
        if (
            max(abs(after - before) for before, after in zip(weights, updated))
            <= tolerance
        ):
            weights = updated
            break
        weights = updated
    coefficients = [weight / scale for weight, scale in zip(weights, scales)]
    margins = [sum(c * x for c, x in zip(coefficients, pair)) for pair in pairs]
    return coefficients, {
        "epochs_completed": completed_epochs,
        "pair_count": len(pairs),
        "mean_logistic_loss": statistics.fmean(
            _logistic_loss(value) for value in margins
        ),
        "pairwise_accuracy": statistics.fmean(
            1.0 if value > 0.0 else 0.5 if value == 0.0 else 0.0 for value in margins
        ),
    }


def evaluate_coefficients(
    dataset: RankDataset, coefficients: list[float]
) -> dict[str, object]:
    pairs = pairwise_differences(dataset)
    margins = [sum(c * x for c, x in zip(coefficients, pair)) for pair in pairs]
    grouped: dict[str, list[RankRow]] = defaultdict(list)
    for row in dataset.rows:
        grouped[row.snapshot_id].append(row)
    snapshot_metrics = []
    for snapshot_id, rows in sorted(grouped.items()):
        predicted_scores = [
            sum(c * x for c, x in zip(coefficients, row.features)) for row in rows
        ]
        predicted_ranks = rankdata([-score for score in predicted_scores])
        observed_ranks = rankdata([float(row.position) for row in rows])
        snapshot_spearman = spearman(predicted_ranks, observed_ranks)
        snapshot_kendall = kendall_tau_b(predicted_ranks, observed_ranks)
        snapshot_metrics.append(
            {
                "snapshot_id": snapshot_id,
                "rows": len(rows),
                "spearman": (
                    snapshot_spearman if math.isfinite(snapshot_spearman) else None
                ),
                "kendall_tau_b": (
                    snapshot_kendall if math.isfinite(snapshot_kendall) else None
                ),
            }
        )
    return {
        "rows": len(dataset.rows),
        "snapshots": len(grouped),
        "pair_count": len(pairs),
        "pairwise_accuracy": statistics.fmean(
            1.0 if value > 0.0 else 0.5 if value == 0.0 else 0.0 for value in margins
        ),
        "mean_logistic_loss": statistics.fmean(
            _logistic_loss(value) for value in margins
        ),
        "mean_spearman": _finite_mean(item["spearman"] for item in snapshot_metrics),
        "mean_kendall_tau_b": _finite_mean(
            item["kendall_tau_b"] for item in snapshot_metrics
        ),
        "snapshot_metrics": snapshot_metrics,
    }


def _finite_mean(values) -> float | None:
    finite = [value for value in values if value is not None and math.isfinite(value)]
    return statistics.fmean(finite) if finite else None


def _normalized_coefficients(
    names: tuple[str, ...], values: list[float]
) -> dict[str, float]:
    magnitude = sum(abs(value) for value in values)
    if magnitude == 0.0:
        return {name: 0.0 for name in names}
    return {name: value / magnitude for name, value in zip(names, values)}


def _public_coefficients(
    feature_names: tuple[str, ...], weights_path: Path
) -> list[float]:
    _, weights, _ = load_weights(weights_path, "upstream_2026_08")
    return [
        float(weights.get(name.removeprefix(FEATURE_PREFIX), 0.0))
        for name in feature_names
    ]


def _cosine(left: list[float], right: list[float]) -> float | None:
    denominator = math.sqrt(
        sum(value**2 for value in left) * sum(value**2 for value in right)
    )
    if denominator == 0.0:
        return None
    return sum(a * b for a, b in zip(left, right)) / denominator


def build_report(
    train: RankDataset,
    test: RankDataset | None,
    *,
    epochs: int,
    learning_rate: float,
    l2: float,
    weights_path: Path,
) -> dict[str, object]:
    disjoint = validate_author_disjoint(train, test) if test is not None else None
    pairs = pairwise_differences(train)
    coefficients, training_optimizer = fit_pairwise_logistic(
        pairs, epochs=epochs, learning_rate=learning_rate, l2=l2
    )
    public = _public_coefficients(train.feature_names, weights_path)
    evaluation_dataset = test or train
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "train": {
                "sha256": train.sha256,
                "rows": len(train.rows),
                "snapshots": len({row.snapshot_id for row in train.rows}),
            },
            "test": (
                {
                    "sha256": test.sha256,
                    "rows": len(test.rows),
                    "snapshots": len({row.snapshot_id for row in test.rows}),
                }
                if test is not None
                else None
            ),
        },
        "features": list(train.feature_names),
        "optimizer": {
            "algorithm": "full-batch pairwise logistic gradient descent",
            "epochs_requested": epochs,
            "learning_rate": learning_rate,
            "l2": l2,
            **training_optimizer,
        },
        "estimated_coefficients": dict(zip(train.feature_names, coefficients)),
        "estimated_l1_normalized": _normalized_coefficients(
            train.feature_names, coefficients
        ),
        "public_default_coefficients": dict(zip(train.feature_names, public)),
        "public_default_l1_normalized": _normalized_coefficients(
            train.feature_names, public
        ),
        "estimated_vs_public_cosine": _cosine(coefficients, public),
        "train_metrics": evaluate_coefficients(train, coefficients),
        "held_out_metrics": evaluate_coefficients(evaluation_dataset, coefficients),
        "author_disjoint": disjoint,
        "evaluation_mode": "author_disjoint_held_out"
        if test is not None
        else "in_sample",
        "tool": {
            "path": "scripts/estimate_feed_weights.py",
            "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "limitations": [
            "Coefficients are cohort-specific ranking associations, not identified production weights.",
            "Displayed candidates omit unexposed posts and retain position, exposure, and selection bias.",
            "Public count rates are post-exposure proxies, not personalized Phoenix predictions.",
            "A held-out CSV proves author separation but does not remove viewer or topic confounding.",
        ],
    }


def render_text(report: dict[str, object]) -> str:
    held_out = report["held_out_metrics"]

    def metric(value: float | None) -> str:
        return "n/a" if value is None else f"{value:+.4f}"

    lines = [
        f"mode={report['evaluation_mode']}",
        f"train_rows={report['inputs']['train']['rows']} pairs={report['optimizer']['pair_count']}",
        (
            "held_out: "
            f"accuracy={held_out['pairwise_accuracy']:.4f} "
            f"spearman={metric(held_out['mean_spearman'])} "
            f"kendall={metric(held_out['mean_kendall_tau_b'])}"
        ),
        "estimated coefficients:",
    ]
    lines.extend(
        f"  {name}: {value:+.8g}"
        for name, value in report["estimated_coefficients"].items()
    )
    lines.append(
        "limitations: observational cohort association; no production-weight claim"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("train_csv", type=Path)
    parser.add_argument("--test-csv", type=Path)
    parser.add_argument("--min-train-rows", type=int, default=50)
    parser.add_argument("--min-test-rows", type=int, default=20)
    parser.add_argument("--epochs", type=int, default=2000)
    parser.add_argument("--learning-rate", type=float, default=0.2)
    parser.add_argument("--l2", type=float, default=0.01)
    parser.add_argument("--weights", type=Path, default=ROOT / "weights.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        train = load_dataset(args.train_csv, args.min_train_rows)
        test = (
            load_dataset(args.test_csv, args.min_test_rows)
            if args.test_csv is not None
            else None
        )
        report = build_report(
            train,
            test,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            l2=args.l2,
            weights_path=args.weights,
        )
    except (KeyError, OSError, SnapshotError, ValueError, json.JSONDecodeError) as exc:
        print(f"estimation failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        if args.json
        else render_text(report)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
