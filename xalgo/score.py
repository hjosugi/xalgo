"""Score a post with the upstream weighted-sum formula.

Upstream (home-mixer/scorers/ranking_scorer.rs):
    combined = sum( weight_i * P(action_i) )
    score    = offset(combined)

The real P(action) values are personalized Phoenix (Grok-based transformer)
predictions for one viewer. Without the model and a viewer history we cannot
reproduce them. Instead we use EMPIRICAL rates from public counts:

    p_hat(favorite) = likes    / views
    p_hat(reply)    = replies  / views
    p_hat(retweet)  = retweets / views
    p_hat(quote)    = quotes   / views   (when available)

So the output is a crowd-average score, not a per-viewer score.
When views are missing we fall back to a log-scaled raw engagement score.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from .fetch import PostData

# Map weight keys -> PostData count attributes usable as empirical rates.
COUNT_FOR_WEIGHT = {
    "favorite": "likes",
    "reply": "replies",
    "retweet": "retweets",
    "quote": "quotes",
}


@dataclass
class ScoreResult:
    preset: str
    mode: str  # "rate" or "raw"
    score: float
    breakdown: Dict[str, float]
    p_hat: Dict[str, float]
    warnings: list


def load_weights(path: Path, preset: Optional[str] = None):
    cfg = json.loads(path.read_text(encoding="utf-8"))
    name = preset or cfg.get("default_preset", "repo_demo")
    if name not in cfg["presets"]:
        raise KeyError(f"Unknown preset '{name}'. Available: {list(cfg['presets'])}")
    return name, cfg["presets"][name], cfg


def _rate(count: Optional[int], views: int) -> Optional[float]:
    if count is None:
        return None
    return min(count / views, 1.0)


def score_post(
    post: PostData,
    weights: Dict[str, float],
    preset_name: str,
    extra_p: Optional[Dict[str, float]] = None,
) -> ScoreResult:
    """extra_p lets the caller inject probabilities that public data lacks,
    e.g. --dwell-p 0.3 for P(dwell)."""
    warnings = list(post.warnings)
    extra_p = extra_p or {}
    for action, probability in extra_p.items():
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise ValueError(f"Probability for '{action}' must be between 0 and 1")
    unknown = sorted(set(extra_p) - set(weights))
    if unknown:
        raise KeyError(
            f"No weight configured for injected actions: {', '.join(unknown)}"
        )

    if post.views and post.views > 0:
        mode = "rate"
        p_hat: Dict[str, float] = {}
        for wkey in weights:
            if wkey in extra_p:
                p_hat[wkey] = extra_p[wkey]
                continue
            attr = COUNT_FOR_WEIGHT.get(wkey)
            if attr is not None:
                r = _rate(getattr(post, attr), post.views)
                if r is not None:
                    p_hat[wkey] = r
        breakdown = {k: weights[k] * p for k, p in p_hat.items()}
        score = sum(breakdown.values())
        missing = [k for k in weights if k not in p_hat and weights[k] != 0.0]
        if missing:
            warnings.append(
                "no public signal for weighted actions (treated as 0): "
                + ", ".join(missing)
            )
    else:
        mode = "raw"
        warnings.append("view count unavailable -> raw log-scaled engagement score")
        p_hat = {}
        breakdown = {}
        for wkey, w in weights.items():
            attr = COUNT_FOR_WEIGHT.get(wkey)
            if attr is None:
                continue
            cnt = getattr(post, attr)
            if cnt is None:
                continue
            # log1p keeps mega-viral posts comparable on one scale
            breakdown[wkey] = w * math.log1p(cnt)
        score = sum(breakdown.values())

    return ScoreResult(
        preset=preset_name,
        mode=mode,
        score=score,
        breakdown=breakdown,
        p_hat=p_hat,
        warnings=warnings,
    )


def author_diversity_multiplier(position: int, decay: float, floor: float) -> float:
    """Upstream: (1 - floor) * decay^position + floor
    Penalty applied to the 2nd, 3rd... post by the same author in one feed."""
    if position < 0:
        raise ValueError("position must be non-negative")
    if not 0.0 <= decay <= 1.0 or not 0.0 <= floor <= 1.0:
        raise ValueError("decay and floor must be between 0 and 1")
    return (1.0 - floor) * (decay**position) + floor
