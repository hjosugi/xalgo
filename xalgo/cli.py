"""xalgo CLI.

Usage:
  python -m xalgo.cli score <post-url> [--preset repo_demo] [--json]
                                       [--dwell-p 0.3] [--vqv-p 0.1]
                                       [--weight vqv=1.0]
  python -m xalgo.cli diff  [--since 2026-05-01] [--json]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from .fetch import fetch_post
from .score import author_diversity_multiplier, load_weights, score_post

ROOT = Path(__file__).resolve().parent.parent


def cmd_score(args: argparse.Namespace) -> int:
    post = fetch_post(args.url)
    preset_name, weights, cfg = load_weights(ROOT / "weights.json", args.preset)
    weights = dict(weights)
    for override in args.weight:
        try:
            action, raw_value = override.split("=", 1)
            if action not in weights:
                raise KeyError(
                    f"'{action}' is not in preset '{preset_name}'; "
                    "use --preset full_template for all upstream actions"
                )
            weights[action] = float(raw_value)
        except ValueError as exc:
            raise ValueError(
                "--weight must use ACTION=NUMBER, for example vqv=1.0"
            ) from exc

    extra_p = {}
    if args.dwell_p is not None:
        extra_p["dwell"] = args.dwell_p
    if args.vqv_p is not None and post.has_video:
        extra_p["vqv"] = args.vqv_p

    result = score_post(post, weights, preset_name, extra_p)

    if args.json:
        print(
            json.dumps(
                {
                    "post": dataclasses.asdict(post),
                    "result": dataclasses.asdict(result),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"\n@{post.author}  ({post.source_backend})")
    text = post.text.replace("\n", " ")
    print(f"  {text[:80]}{'...' if len(text) > 80 else ''}")
    print(
        f"  likes={post.likes} rt={post.retweets} replies={post.replies} views={post.views}"
    )
    print(f"\n[preset={result.preset} | mode={result.mode}]")
    for k, v in sorted(result.breakdown.items(), key=lambda x: -abs(x[1])):
        p = result.p_hat.get(k)
        p_str = f"p_hat={p:.6f}" if p is not None else "log1p(count)"
        print(f"  {k:<22} {p_str:<18} contrib={v:+.6f}")
    print(f"\n  SCORE = {result.score:.6f}")

    ad = cfg.get("author_diversity", {})
    m1 = author_diversity_multiplier(1, ad.get("decay", 0.9), ad.get("floor", 0.2))
    print(f"  (author diversity example: 2nd post by same author x{m1:.3f})")
    for w in result.warnings:
        print(f"  note: {w}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    # Delegate to scripts/track_upstream.py so CLI and CI share one implementation
    sys.path.insert(0, str(ROOT / "scripts"))
    import track_upstream  # noqa: PLC0415

    return track_upstream.run(since=args.since, as_json=args.json)


def main() -> int:
    ap = argparse.ArgumentParser(prog="xalgo")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("score", help="score a post from its URL (no X API)")
    sc.add_argument("url")
    sc.add_argument("--preset", default=None)
    sc.add_argument("--json", action="store_true")
    sc.add_argument("--dwell-p", type=float, default=None, help="assumed P(dwell)")
    sc.add_argument(
        "--vqv-p", type=float, default=None, help="assumed P(video quality view)"
    )
    sc.add_argument(
        "--weight",
        action="append",
        default=[],
        metavar="ACTION=NUMBER",
        help="override one selected-preset weight; repeatable",
    )
    sc.set_defaults(fn=cmd_score)

    df = sub.add_parser("diff", help="detect upstream scoring changes from commits/PRs")
    df.add_argument("--since", default=None, help="ISO date, e.g. 2026-05-01")
    df.add_argument("--json", action="store_true")
    df.set_defaults(fn=cmd_diff)

    args = ap.parse_args()
    try:
        return args.fn(args)
    except (KeyError, RuntimeError, ValueError) as exc:
        print(f"xalgo: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
