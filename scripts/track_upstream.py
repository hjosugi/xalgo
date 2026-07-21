"""Detect ranking-relevant changes in xai-org/x-algorithm.

The tracker inspects both commits on ``main`` and merged pull requests.  The
upstream repository currently exposes no pull-request REST endpoint (404), so
that condition is reported but does not make commit tracking fail.  If the
endpoint is enabled later, changed PR files are inspected automatically.

Exit codes:
  0: no ranking-relevant change
  2: ranking-relevant commit or merged PR found
  other: an actual tracker failure
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import requests

REPO = "xai-org/x-algorithm"
API = f"https://api.github.com/repos/{REPO}"
ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state" / "last_commit.txt"
LAST_CHECK_FILE = ROOT / "state" / "last_checked_at.txt"
REPORT_FILE = ROOT / "report.md"

# A path match is enough to flag a change.  The regular expression below is
# only used to extract a compact set of especially interesting patch lines.
ALGORITHM_PATHS = (
    "candidate-pipeline/",
    "home-mixer/candidate_pipeline/",
    "home-mixer/filters/",
    "home-mixer/scorers/",
    "home-mixer/selectors/",
    "home-mixer/sources/",
    "phoenix/grok.py",
    "phoenix/recsys_model.py",
    "phoenix/recsys_retrieval_model.py",
    "phoenix/run_pipeline.py",
    "phoenix/run_ranker.py",
    "phoenix/run_retrieval.py",
    "phoenix/runners.py",
)
SIGNAL_RE = re.compile(
    r"(weight|decay|floor|offset|action|score|rank|filter|candidate|attention|top[_-]?k)",
    re.IGNORECASE,
)


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "xalgo-upstream-tracker",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get(url: str, **params):
    response = requests.get(url, headers=_headers(), params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def _read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def _is_algorithm_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in ALGORITHM_PATHS)


def _interesting_lines(patch: str, limit: int = 40) -> list[str]:
    lines = []
    for line in patch.splitlines():
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
            continue
        if SIGNAL_RE.search(line):
            lines.append(line)
        if len(lines) == limit:
            break
    return lines


def _analyze_files(files: Iterable[dict]) -> list[dict]:
    hits = []
    for changed in files:
        path = changed["filename"]
        if not _is_algorithm_path(path):
            continue
        hits.append(
            {
                "path": path,
                "status": changed.get("status", "modified"),
                "signal_lines": _interesting_lines(changed.get("patch", "")),
            }
        )
    return hits


def analyze_commit(sha: str) -> dict:
    detail = _get(f"{API}/commits/{sha}")
    return {
        "sha": sha[:10],
        "full_sha": sha,
        "message": detail["commit"]["message"].splitlines()[0],
        "date": detail["commit"]["committer"]["date"],
        "url": detail["html_url"],
        "algorithm_files": _analyze_files(detail.get("files", [])),
    }


def _list_new_commits(since_iso: str, last_sha: str | None) -> list[str]:
    """Return newest-first SHAs, stopping at the saved baseline when possible."""
    shas: list[str] = []
    for page in range(1, 11):
        commits = _get(
            f"{API}/commits",
            sha="main",
            since=since_iso,
            per_page=100,
            page=page,
        )
        if not commits:
            break
        for commit in commits:
            if last_sha and commit["sha"] == last_sha:
                return shas
            shas.append(commit["sha"])
        if len(commits) < 100:
            break
    return shas


def _list_pr_files(number: int) -> list[dict]:
    files: list[dict] = []
    for page in range(1, 11):
        batch = _get(f"{API}/pulls/{number}/files", per_page=100, page=page)
        files.extend(batch)
        if len(batch) < 100:
            break
    return files


def merged_prs(since_iso: str) -> tuple[list[dict], str]:
    """Inspect merged PR files, tolerating repositories with PRs disabled."""
    try:
        pulls = _get(
            f"{API}/pulls",
            state="closed",
            sort="updated",
            direction="desc",
            per_page=100,
        )
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return [], "unavailable (upstream pull-request API returned 404)"
        raise

    results = []
    since_time = _parse_timestamp(since_iso)
    for pr in pulls:
        merged_at = pr.get("merged_at")
        if not merged_at or _parse_timestamp(merged_at) < since_time:
            continue
        results.append(
            {
                "number": pr["number"],
                "title": pr["title"],
                "merged_at": merged_at,
                "url": pr["html_url"],
                "algorithm_files": _analyze_files(_list_pr_files(pr["number"])),
            }
        )
    return results, "available"


def _resolve_since(explicit_since: str | None, now: datetime) -> str:
    if explicit_since:
        # Accept a date for convenience or a complete ISO-8601 timestamp.
        return (
            f"{explicit_since}T00:00:00Z"
            if "T" not in explicit_since
            else explicit_since.replace("+00:00", "Z")
        )
    last_check = _read_text(LAST_CHECK_FILE)
    if last_check:
        return last_check
    return (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_report(since: str | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since_iso = _resolve_since(since, now)
    # An explicit window is an ad-hoc historical query and must not be cut
    # short by (or overwrite) the scheduler's saved baseline.
    last_sha = _read_text(STATE_FILE) if since is None else None
    new_shas = _list_new_commits(since_iso, last_sha)
    commits = [analyze_commit(sha) for sha in new_shas]
    prs, pr_api_status = merged_prs(since_iso)
    return {
        "checked_at": now.isoformat(),
        "since": since_iso,
        "upstream_head": new_shas[0] if new_shas else last_sha,
        "new_commit_count": len(commits),
        "algorithm_commits": [c for c in commits if c["algorithm_files"]],
        "merged_pr_count": len(prs),
        "algorithm_pull_requests": [pr for pr in prs if pr["algorithm_files"]],
        "pull_request_api": pr_api_status,
    }


def _persist_state(report: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if report.get("upstream_head"):
        STATE_FILE.write_text(report["upstream_head"] + "\n", encoding="utf-8")
    LAST_CHECK_FILE.write_text(report["checked_at"] + "\n", encoding="utf-8")


def run(since: str | None = None, as_json: bool = False) -> int:
    report = build_report(since=since)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _write_markdown(report)
        print(REPORT_FILE.read_text(encoding="utf-8"))
    if since is None:
        _persist_state(report)
    changed = report["algorithm_commits"] or report["algorithm_pull_requests"]
    return 2 if changed else 0


def _append_change(lines: list[str], change: dict, heading: str) -> None:
    lines.extend([f"### {heading}", "", change["url"], ""])
    for changed_file in change["algorithm_files"]:
        lines.append(f"- **{changed_file['path']}** ({changed_file['status']})")
        for signal_line in changed_file["signal_lines"]:
            lines.append(f"  - `{signal_line[:240]}`")
    lines.append("")


def _write_markdown(report: dict) -> None:
    lines = [
        f"# Upstream algorithm check — {report['checked_at']}",
        "",
        f"Window start: `{report['since']}`",
        f"New commits on main: {report['new_commit_count']}",
        f"Merged PRs inspected: {report['merged_pr_count']}",
        f"Pull-request API: {report['pull_request_api']}",
        "",
    ]
    if not report["algorithm_commits"] and not report["algorithm_pull_requests"]:
        lines.extend(["No ranking-relevant changes.", ""])

    if report["algorithm_commits"]:
        lines.extend(["## Ranking-relevant commits", ""])
        for commit in report["algorithm_commits"]:
            heading = f"`{commit['sha']}` {commit['message']} ({commit['date']})"
            _append_change(lines, commit, heading)

    if report["algorithm_pull_requests"]:
        lines.extend(["## Ranking-relevant merged pull requests", ""])
        for pr in report["algorithm_pull_requests"]:
            heading = f"PR #{pr['number']} {pr['title']} ({pr['merged_at']})"
            _append_change(lines, pr, heading)

    REPORT_FILE.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since", help="ISO date/timestamp; defaults to saved check time"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    return run(since=args.since, as_json=args.json)


if __name__ == "__main__":
    sys.exit(main())
