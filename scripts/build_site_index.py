#!/usr/bin/env python3
"""Build the client-side search index for the static site.

The wiki pages are plain HTML, so the index is derived from the markup:
one entry per page, one section per ``<h2>``.  The site's ``site.js`` fetches
``web/search-index.json`` and searches titles and text client-side.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
OUT = WEB / "search-index.json"

SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(source: str) -> str:
    text = TAG_RE.sub(" ", source)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def page_entry(path: Path) -> dict[str, object]:
    source = SCRIPT_RE.sub(" ", path.read_text(encoding="utf-8"))
    heading = H1_RE.search(source)
    title = strip_tags(heading.group(1)) if heading else path.stem

    parts = H2_RE.split(source)
    sections: list[dict[str, str]] = []
    lead = strip_tags(parts[0])
    if lead:
        sections.append({"title": "", "text": lead})
    for index in range(1, len(parts), 2):
        section_title = strip_tags(parts[index])
        section_text = strip_tags(parts[index + 1]) if index + 1 < len(parts) else ""
        if section_title or section_text:
            sections.append({"title": section_title, "text": section_text})
    return {"url": path.name, "title": title, "sections": sections}


def main() -> int:
    pages = [page_entry(path) for path in sorted(WEB.glob("*.html"))]
    OUT.write_text(
        json.dumps(pages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT.relative_to(ROOT)} ({len(pages)} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
