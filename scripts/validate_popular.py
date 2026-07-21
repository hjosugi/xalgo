"""Validate the scorer against real public posts.

Feed it URLs (one per line on stdin, or built-in sample) plus an optional
external rank/score per post. It fetches live counts, scores each post,
then reports Spearman rank correlation between:
  - our score vs views          (does score track raw reach?)
  - our score vs external rank  (does score track an independent virality ranking?)

A high correlation does NOT prove we match Phoenix (which is personalized),
but a low correlation would falsify the empirical-rate proxy.

Usage:
  python scripts/validate_popular.py
  cat urls.txt | python scripts/validate_popular.py --stdin
  python scripts/validate_popular.py --json --delay 0
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from xalgo.fetch import fetch_post  # noqa: E402
from xalgo.score import load_weights, score_post  # noqa: E402

# Snapshot collected from https://xbeast.io/viral-tweets on 2026-07-20 UTC.
# The external score is proprietary and is used only to reproduce that page's
# ordering; it is not a ground-truth Phoenix score. None means an extra control
# post that was not present in the snapshot.
SAMPLE_SOURCE = "https://xbeast.io/viral-tweets"
SAMPLE = [
    ("2079205509727478218", 258.35),
    ("2079222259802054870", 153.68),
    ("2079224829845422393", 144.62),
    ("2079288782130417741", 131.72),
    ("2079172194882445346", 123.34),
    ("2079272919700517166", 104.75),
    ("2079256963196567576", 102.42),
    ("2079214333725380662", 100.53),
    ("2079493434512232838", 93.48),
    ("2026203633281274048", None),
    ("2006038274167460015", None),
]


def spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rho without scipy, using average ranks for ties."""
    n = len(xs)
    if n < 3 or len(ys) != n:
        return float("nan")

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        start = 0
        while start < len(order):
            end = start + 1
            while end < len(order) and v[order[end]] == v[order[start]]:
                end += 1
            average_rank = ((start + 1) + end) / 2
            for position in range(start, end):
                r[order[position]] = average_rank
            start = end
        return r

    rx, ry = ranks(xs), ranks(ys)
    rx_mean = sum(rx) / n
    ry_mean = sum(ry) / n
    numerator = sum((a - rx_mean) * (b - ry_mean) for a, b in zip(rx, ry))
    denominator = math.sqrt(
        sum((a - rx_mean) ** 2 for a in rx) * sum((b - ry_mean) ** 2 for b in ry)
    )
    return numerator / denominator if denominator else float("nan")


def _fmt(value: int | float | None, width: int) -> str:
    return f"{value:>{width}}" if value is not None else f"{'-':>{width}}"


def _correlations(rate_rows) -> dict:
    scores = [result.score for _, result, _ in rate_rows]
    views = [post.views for post, _, _ in rate_rows]
    correlations = {"score_vs_views": spearman(scores, views)}

    amplification = [
        (result.score, post.views / post.author_followers)
        for post, result, _ in rate_rows
        if post.author_followers and post.views and post.views > 10000
    ]
    if len(amplification) >= 3:
        score_values, amplification_values = zip(*amplification)
        correlations["score_vs_amplification"] = spearman(
            list(score_values), list(amplification_values)
        )
        correlations["amplification_n"] = len(amplification)

    external = [(result.score, ext) for _, result, ext in rate_rows if ext is not None]
    if len(external) >= 3:
        score_values, external_values = zip(*external)
        correlations["score_vs_external"] = spearman(
            list(score_values), list(external_values)
        )
        correlations["external_n"] = len(external)
    return correlations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stdin", action="store_true", help="read one post URL/ID per line"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable output"
    )
    parser.add_argument(
        "--delay", type=float, default=0.4, help="seconds between fetches"
    )
    args = parser.parse_args(argv)

    if args.stdin:
        items = [(line.strip(), None) for line in sys.stdin if line.strip()]
    else:
        items = SAMPLE

    preset_name, weights, _ = load_weights(ROOT / "weights.json")
    rows = []
    for url_or_id, ext in items:
        try:
            post = fetch_post(url_or_id)
            res = score_post(post, weights, preset_name)
            rows.append((post, res, ext))
            if args.delay > 0:
                time.sleep(args.delay)  # be polite to the free backends
        except Exception as e:  # noqa: BLE001
            print(f"skip {url_or_id}: {e}", file=sys.stderr)

    rate_rows = [(p, r, e) for p, r, e in rows if r.mode == "rate"]
    rate_rows.sort(key=lambda t: -t[1].score)

    correlations = _correlations(rate_rows)
    if args.json:
        print(
            json.dumps(
                {
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "sample_source": None if args.stdin else SAMPLE_SOURCE,
                    "preset": preset_name,
                    "rows": [
                        {
                            "post": dataclasses.asdict(post),
                            "result": dataclasses.asdict(result),
                            "external_score": external,
                        }
                        for post, result, external in rate_rows
                    ],
                    "correlations": correlations,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"\npreset={preset_name}  mode=rate  n={len(rate_rows)}")
    if not args.stdin:
        print(f"sample snapshot: {SAMPLE_SOURCE} (2026-07-20 UTC)")
    print(
        f"{'#':<3}{'author':<16}{'score':>10}{'views':>10}{'likes':>9}{'rt':>8}{'rep':>7}{'ext':>8}"
    )
    for i, (p, r, e) in enumerate(rate_rows, 1):
        print(
            f"{i:<3}@{p.author:<15}{r.score:>10.5f}{_fmt(p.views, 10)}{_fmt(p.likes, 9)}"
            f"{_fmt(p.retweets, 8)}{_fmt(p.replies, 7)}"
            f"{(f'{e:.1f}' if e is not None else '-'):>8}"
        )

    print(f"\nSpearman(score, views)         = {correlations['score_vs_views']:+.3f}")
    if "score_vs_amplification" in correlations:
        print(
            "Spearman(score, amplification) = "
            f"{correlations['score_vs_amplification']:+.3f}  "
            f"(n={correlations['amplification_n']})"
        )
    if "score_vs_external" in correlations:
        print(
            "Spearman(score, external score) = "
            f"{correlations['score_vs_external']:+.3f}  "
            f"(n={correlations['external_n']})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
