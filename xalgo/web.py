"""Small local web app for exploring the xalgo scoring model.

Run with::

    python -m xalgo.web

The server intentionally uses only the Python standard library so the browser
experience has the same installation requirements as the CLI.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .fetch import PostData, fetch_post
from .score import author_diversity_multiplier, load_weights, score_post

ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web"
WEIGHTS_PATH = ROOT / "weights.json"
MAX_REQUEST_BYTES = 64 * 1024


def _finite_number(value: Any, name: str, *, minimum: float = 0) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(number) or number < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return number


def _optional_count(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value in (None, ""):
        return None
    number = _finite_number(value, key)
    if not number.is_integer():
        raise ValueError(f"{key} must be a whole number")
    return int(number)


def _post_from_manual(data: dict[str, Any]) -> PostData:
    return PostData(
        status_id="manual",
        text=str(data.get("text") or "手入力したサンプル投稿"),
        author=str(data.get("author") or "learner"),
        likes=_optional_count(data, "likes"),
        retweets=_optional_count(data, "retweets"),
        replies=_optional_count(data, "replies"),
        quotes=_optional_count(data, "quotes"),
        views=_optional_count(data, "views"),
        has_video=bool(data.get("has_video", False)),
        source_backend="manual",
    )


def build_score_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a browser request and return the same result as the CLI."""
    preset_name, preset_weights, cfg = load_weights(
        WEIGHTS_PATH, str(payload.get("preset") or "repo_demo")
    )
    weights = dict(preset_weights)

    overrides = payload.get("weights") or {}
    if not isinstance(overrides, dict):
        raise ValueError("weights must be an object")
    for action, value in overrides.items():
        if action not in weights:
            raise KeyError(f"'{action}' is not part of preset '{preset_name}'")
        weights[action] = _finite_number(value, f"weight.{action}", minimum=-10000)

    source = payload.get("source", "manual")
    if source == "url":
        url = str(payload.get("url") or "").strip()
        if not url:
            raise ValueError("X post URL is required")
        post = fetch_post(url)
    elif source == "manual":
        manual = payload.get("post") or {}
        if not isinstance(manual, dict):
            raise ValueError("post must be an object")
        post = _post_from_manual(manual)
    else:
        raise ValueError("source must be 'manual' or 'url'")

    probabilities = payload.get("probabilities") or {}
    if not isinstance(probabilities, dict):
        raise ValueError("probabilities must be an object")
    extra_p = {
        action: _finite_number(value, f"probability.{action}")
        for action, value in probabilities.items()
        if value not in (None, "")
    }

    result = score_post(post, weights, preset_name, extra_p)
    ad = cfg.get("author_diversity", {})
    position = int(_finite_number(payload.get("author_position", 1), "author_position"))
    multiplier = author_diversity_multiplier(
        position,
        float(ad.get("decay", 0.9)),
        float(ad.get("floor", 0.2)),
    )
    return {
        "post": dataclasses.asdict(post),
        "result": dataclasses.asdict(result),
        "weights": weights,
        "author_diversity": {
            "position": position,
            "multiplier": multiplier,
            "adjusted_score": result.score * multiplier,
        },
    }


class XalgoHandler(SimpleHTTPRequestHandler):
    """Static-file and JSON API handler."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def _json(self, status: HTTPStatus, data: dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path in {"/api/config", "/weights.json"}:
            cfg = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
            if self.path == "/weights.json":
                self._json(HTTPStatus.OK, cfg)
                return
            self._json(
                HTTPStatus.OK,
                {
                    "default_preset": cfg["default_preset"],
                    "presets": cfg["presets"],
                    "author_diversity": cfg.get("author_diversity", {}),
                },
            )
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/api/score":
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("request body has an invalid size")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            self._json(HTTPStatus.OK, build_score_response(payload))
        except (json.JSONDecodeError, KeyError, RuntimeError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"xalgo web: {fmt % args}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the xalgo learning web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), XalgoHandler)
    print(f"xalgo learning lab: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
