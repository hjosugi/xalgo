"""Fetch public post data from a URL without using the official X API.

Backend chain (first success wins):
  1. fxtwitter   - https://api.fxtwitter.com/status/{id}
  2. vxtwitter   - https://api.vxtwitter.com/Twitter/status/{id}
  3. syndication - https://cdn.syndication.twimg.com/tweet-result (official embed CDN)

All backends are unauthenticated and read only public data.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

UA = {"User-Agent": "Mozilla/5.0 (xalgo-scorer; research tool)"}
TIMEOUT = 12

_ID_RE = re.compile(
    r"(?:twitter\.com|x\.com|fxtwitter\.com|vxtwitter\.com|fixupx\.com)"
    r"/[^/]+/status(?:es)?/(\d+)"
)


@dataclass
class PostData:
    status_id: str
    url: str = ""
    text: str = ""
    author: str = ""
    author_followers: Optional[int] = None
    created_at: str = ""
    likes: Optional[int] = None
    retweets: Optional[int] = None
    replies: Optional[int] = None
    quotes: Optional[int] = None
    bookmarks: Optional[int] = None
    views: Optional[int] = None
    has_video: bool = False
    video_duration_ms: Optional[int] = None
    source_backend: str = ""
    warnings: list = field(default_factory=list)


@dataclass
class BackendAttempt:
    backend: str
    elapsed_ms: float
    post: Optional[PostData] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.post is not None


def extract_status_id(url_or_id: str) -> str:
    """Accept a full URL or a bare numeric status ID."""
    s = url_or_id.strip()
    if s.isdigit():
        return s
    m = _ID_RE.search(s)
    if not m:
        raise ValueError(f"Could not find a status ID in: {url_or_id}")
    return m.group(1)


def _syndication_token(status_id: str) -> str:
    """Token used by the official embed CDN: base36((id / 1e15) * pi)."""
    n = int((int(status_id) / 1e15) * math.pi)
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while n:
        out = digits[n % 36] + out
        n //= 36
    return out or "0"


def _from_fxtwitter(status_id: str) -> PostData:
    r = requests.get(
        f"https://api.fxtwitter.com/status/{status_id}", headers=UA, timeout=TIMEOUT
    )
    r.raise_for_status()
    t = r.json()["tweet"]
    media = t.get("media") or {}
    videos = media.get("videos") or []
    d = PostData(
        status_id=status_id,
        url=t.get("url", ""),
        text=t.get("text", ""),
        author=t.get("author", {}).get("screen_name", ""),
        author_followers=t.get("author", {}).get("followers"),
        created_at=t.get("created_at", ""),
        likes=t.get("likes"),
        retweets=t.get("retweets"),
        replies=t.get("replies"),
        bookmarks=t.get("bookmarks"),
        views=t.get("views"),
        has_video=bool(videos),
        source_backend="fxtwitter",
    )
    if videos:
        dur = videos[0].get("duration")
        if dur:
            d.video_duration_ms = int(float(dur) * 1000)
    return d


def _from_vxtwitter(status_id: str) -> PostData:
    r = requests.get(
        f"https://api.vxtwitter.com/status/{status_id}",
        headers=UA,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    t = r.json()
    media = t.get("media_extended") or []
    has_video = any(m.get("type") == "video" for m in media)
    return PostData(
        status_id=status_id,
        url=t.get("tweetURL", ""),
        text=t.get("text", ""),
        author=t.get("user_screen_name", ""),
        created_at=t.get("date", ""),
        likes=t.get("likes"),
        retweets=t.get("retweets"),
        replies=t.get("replies"),
        views=t.get("views"),
        has_video=has_video,
        source_backend="vxtwitter",
    )


def _from_syndication(status_id: str) -> PostData:
    r = requests.get(
        "https://cdn.syndication.twimg.com/tweet-result",
        params={"id": status_id, "token": _syndication_token(status_id)},
        headers=UA,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    t = r.json()
    d = PostData(
        status_id=status_id,
        text=t.get("text", ""),
        author=t.get("user", {}).get("screen_name", ""),
        created_at=t.get("created_at", ""),
        likes=t.get("favorite_count"),
        replies=t.get("conversation_count"),
        has_video="video" in t,
        source_backend="syndication",
    )
    d.warnings.append("syndication backend has no retweet/view counts")
    return d


BACKENDS = [_from_fxtwitter, _from_vxtwitter, _from_syndication]


def fetch_all_backends(url_or_id: str) -> list[BackendAttempt]:
    """Query every backend for reliability and cross-backend comparisons."""
    status_id = extract_status_id(url_or_id)
    attempts = []
    for backend in BACKENDS:
        started = time.monotonic()
        try:
            post = backend(status_id)
            attempts.append(
                BackendAttempt(
                    backend=backend.__name__.removeprefix("_from_"),
                    elapsed_ms=(time.monotonic() - started) * 1000,
                    post=post,
                )
            )
        except Exception as exc:  # noqa: BLE001 - audit must retain all failures
            attempts.append(
                BackendAttempt(
                    backend=backend.__name__.removeprefix("_from_"),
                    elapsed_ms=(time.monotonic() - started) * 1000,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return attempts


def fetch_post(url_or_id: str) -> PostData:
    status_id = extract_status_id(url_or_id)
    errors = []
    for backend in BACKENDS:
        try:
            return backend(status_id)
        except Exception as e:  # noqa: BLE001 - fall through to next backend
            errors.append(f"{backend.__name__}: {e}")
    raise RuntimeError("All backends failed:\n" + "\n".join(errors))
