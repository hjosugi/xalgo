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
import ast
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
CORPUS_FILE = ROOT / "state" / "upstream_tracking_corpus.json"

# A path match is enough to flag a change.  The regular expression below is
# only used to extract a compact set of especially interesting patch lines.
RANKING_PATHS = (
    "README.md",
    "candidate-pipeline/",
    "home-mixer/candidate_hydrators/",
    "home-mixer/candidate_pipeline/",
    "home-mixer/filters/",
    "home-mixer/models/",
    "home-mixer/params/",
    "home-mixer/query_hydrators/",
    "home-mixer/scorers/",
    "home-mixer/selectors/",
    "home-mixer/sources/",
    "grox/classifiers/content/banger_initial_screen.py",
    "grox/classifiers/content/reply_ranking.py",
    "grox/embedder/",
    "grox/plans/plan_initial_banger.py",
    "grox/plans/plan_reply_ranking.py",
    "grox/tasks/task_rank_replies.py",
    "phoenix/README.md",
    "phoenix/artifacts/oss-phoenix-artifacts.zip",
    "phoenix/crates/common/xai-recsys/",
    "phoenix/crates/serving/xai-recsys-proto/",
    "phoenix/reference/",
    "phoenix/xrex/configs/",
    "phoenix/xrex/data/recsys/",
    "phoenix/xrex/inference/",
    "phoenix/xrex/models/",
    "phoenix/recsys_model.py",
    "phoenix/recsys_retrieval_model.py",
    "phoenix/run_pipeline.py",
    "phoenix/run_ranker.py",
    "phoenix/run_retrieval.py",
    "phoenix/runners.py",
    "simclusters/",
)
POLICY_PATHS = (
    "abuse-enforcement-service/",
    "adult-content/",
    "botmaker-rules/",
    "botmaker/",
    "media-model-proxy/",
    "scarecrow/",
    "visibility-filtering/",
)
GROX_POLICY_TERMS = (
    "post_safety",
    "safety_ptos",
    "spam",
)
SIGNAL_RE = re.compile(
    r"(weight|decay|floor|offset|action|score|rank|filter|candidate|attention|top[_-]?k)",
    re.IGNORECASE,
)
STRUCTURAL_NAME_RE = re.compile(
    r"(weight|decay|floor|offset|action|score|rank|filter|candidate|attention|top[_-]?k)",
    re.IGNORECASE,
)
PY_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")
PY_FUNCTION_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
RUST_CONST_RE = re.compile(
    r"^\s*(?:pub\s+)?(?:const|static)\s+([A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*:[^=]+)?\s*=\s*(.+?);?\s*$"
)
RUST_FUNCTION_RE = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*\("
)
RUST_FIELD_RE = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[^:]+,?\s*$"
)
ACTION_NAMES = {
    "favorite",
    "reply",
    "retweet",
    "photo_expand",
    "video_open",
    "click",
    "open_link",
    "profile_click",
    "vqv",
    "share",
    "share_via_dm",
    "share_via_copy_link",
    "dwell",
    "quote",
    "quoted_click",
    "quoted_vqv",
    "cont_dwell_time",
    "cont_click_dwell_time",
    "cont_active_secs_5m_residual_norm",
    "follow_author",
    "post_unexplored",
    "not_interested",
    "block_author",
    "mute_author",
    "report",
    "not_dwelled",
}


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


def _classify_path(path: str) -> str:
    if any(path == prefix or path.startswith(prefix) for prefix in POLICY_PATHS):
        return "policy"
    if path.startswith("grox/") and any(term in path for term in GROX_POLICY_TERMS):
        return "policy"
    if _is_algorithm_path(path):
        return "ranking"
    return "unrelated"


def _subsystem(path: str) -> str:
    if path.startswith("grox/"):
        return "grox"
    if path.startswith("phoenix/"):
        return "phoenix"
    if path.startswith("home-mixer/"):
        return "home-mixer"
    if path.startswith("candidate-pipeline/"):
        return "candidate-pipeline"
    if path.startswith("visibility-filtering/"):
        return "visibility-filtering"
    if path.startswith("simclusters/"):
        return "simclusters"
    return "repository"


def _is_algorithm_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in RANKING_PATHS)


def _interesting_lines(patch: str, path: str = "", limit: int = 24) -> list[str]:
    lines = []
    code_file = path.endswith((".py", ".rs"))
    for line in patch.splitlines():
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
            continue
        stripped = line[1:].strip()
        if code_file and re.match(
            r"^(?:use\s|from\s|import\s|pub\s+mod\s|mod\s)", stripped
        ):
            continue
        if code_file and stripped.startswith(("//", "#")):
            continue
        if SIGNAL_RE.search(line):
            lines.append(line)
        if len(lines) == limit:
            break
    return lines


def _normalize_expression(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().rstrip(";"))


def _python_structure(source: str) -> dict[str, set[str]]:
    result = {
        "assignments": set(),
        "functions": set(),
        "fields": set(),
        "actions": set(),
        "formulas": set(),
    }
    try:
        tree = ast.parse(source)
    except SyntaxError:
        for line in source.splitlines():
            assignment = PY_ASSIGN_RE.match(line)
            if assignment and STRUCTURAL_NAME_RE.search(assignment.group(1)):
                result["assignments"].add(
                    f"{assignment.group(1)}={_normalize_expression(assignment.group(2))}"
                )
            function = PY_FUNCTION_RE.match(line)
            if function and STRUCTURAL_NAME_RE.search(function.group(1)):
                result["functions"].add(function.group(1))
            if STRUCTURAL_NAME_RE.search(line) and any(
                operator in line for operator in ("+", "-", "*", "/", "**")
            ):
                result["formulas"].add(_normalize_expression(line))
        return result

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if STRUCTURAL_NAME_RE.search(node.name):
                result["functions"].add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and STRUCTURAL_NAME_RE.search(
                    target.id
                ):
                    result["assignments"].add(
                        f"{target.id}={ast.dump(value, include_attributes=False)}"
                    )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.lower() in ACTION_NAMES:
                result["actions"].add(node.value.lower())
        elif isinstance(node, (ast.BinOp, ast.Compare)):
            dumped = ast.dump(node, include_attributes=False)
            if STRUCTURAL_NAME_RE.search(dumped):
                result["formulas"].add(dumped)
    return result


def _rust_structure(source: str) -> dict[str, set[str]]:
    result = {
        "assignments": set(),
        "functions": set(),
        "fields": set(),
        "actions": set(),
        "formulas": set(),
    }
    struct_depth = 0
    for line in source.splitlines():
        code = line.split("//", 1)[0]
        constant = RUST_CONST_RE.match(code)
        if constant and STRUCTURAL_NAME_RE.search(constant.group(1)):
            result["assignments"].add(
                f"{constant.group(1)}={_normalize_expression(constant.group(2))}"
            )
        function = RUST_FUNCTION_RE.match(code)
        if function and STRUCTURAL_NAME_RE.search(function.group(1)):
            result["functions"].add(function.group(1))
        starts_struct = bool(re.match(r"^\s*(?:pub\s+)?struct\s+\w+", code))
        if starts_struct:
            struct_depth += code.count("{") - code.count("}")
        field = RUST_FIELD_RE.match(code)
        if struct_depth > 0 and field and STRUCTURAL_NAME_RE.search(field.group(1)):
            result["fields"].add(field.group(1))
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", code):
            if token.lower() in ACTION_NAMES:
                result["actions"].add(token.lower())
        if STRUCTURAL_NAME_RE.search(code) and any(
            operator in code.replace("->", "") for operator in ("+", "-", "*", "/")
        ):
            result["formulas"].add(_normalize_expression(code))
        if struct_depth > 0 and not starts_struct:
            struct_depth += code.count("{") - code.count("}")
    return result


def extract_source_structure(path: str, source: str) -> dict[str, set[str]]:
    if path.endswith(".py"):
        return _python_structure(source)
    if path.endswith(".rs"):
        return _rust_structure(source)
    return {
        "assignments": set(),
        "functions": set(),
        "fields": set(),
        "actions": set(),
        "formulas": set(),
    }


def diff_source_structure(path: str, before: str, after: str) -> dict[str, dict]:
    previous = extract_source_structure(path, before)
    current = extract_source_structure(path, after)
    return {
        kind: {
            "added": sorted(current[kind] - previous[kind]),
            "removed": sorted(previous[kind] - current[kind]),
        }
        for kind in previous
        if current[kind] != previous[kind]
    }


def _structured_patch_changes(path: str, patch: str) -> dict[str, dict]:
    removed = "\n".join(
        line[1:]
        for line in patch.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )
    added = "\n".join(
        line[1:]
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    return diff_source_structure(path, removed, added)


def _analyze_files(files: Iterable[dict]) -> list[dict]:
    hits = []
    for changed in files:
        path = changed["filename"]
        category = _classify_path(path)
        if category == "unrelated":
            continue
        hits.append(
            {
                "path": path,
                "status": changed.get("status", "modified"),
                "category": category,
                "subsystem": _subsystem(path),
                "signal_lines": _interesting_lines(changed.get("patch", ""), path=path),
                "structural_changes": _structured_patch_changes(
                    path, changed.get("patch", "")
                ),
            }
        )
    return hits


def evaluate_corpus(path: Path = CORPUS_FILE) -> dict:
    corpus = json.loads(path.read_text(encoding="utf-8"))
    cases = corpus["cases"]
    relevant = {"ranking", "policy"}
    true_positive = false_positive = false_negative = true_negative = 0
    correct_category = 0
    errors = []
    confusion: dict[str, dict[str, int]] = {}

    for case in cases:
        expected = case["expected_category"]
        predicted = _classify_path(case["path"])
        confusion.setdefault(expected, {})
        confusion[expected][predicted] = confusion[expected].get(predicted, 0) + 1
        if expected == predicted:
            correct_category += 1

        expected_relevant = expected in relevant
        predicted_relevant = predicted in relevant
        if expected_relevant and predicted_relevant:
            true_positive += 1
        elif not expected_relevant and predicted_relevant:
            false_positive += 1
        elif expected_relevant and not predicted_relevant:
            false_negative += 1
        else:
            true_negative += 1
        if expected != predicted:
            errors.append(
                {
                    "id": case["id"],
                    "path": case["path"],
                    "expected": expected,
                    "predicted": predicted,
                }
            )

    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else None
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else None
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {
        "corpus": str(path),
        "source_repository": corpus["source_repository"],
        "reviewed_at": corpus["reviewed_at"],
        "cases": len(cases),
        "category_accuracy": correct_category / len(cases) if cases else None,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "confusion": confusion,
        "counts": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "true_negative": true_negative,
        },
        "errors": errors,
    }


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
                "merge_commit_sha": pr.get("merge_commit_sha"),
                "algorithm_files": _analyze_files(_list_pr_files(pr["number"])),
            }
        )
    return results, "available"


def _deduplicate_pull_requests(
    commits: Iterable[dict], pull_requests: Iterable[dict]
) -> tuple[list[dict], list[dict]]:
    """Drop PR records whose merge commit is already represented as a commit."""
    commit_shas = {
        commit.get("full_sha") for commit in commits if commit.get("full_sha")
    }
    kept = []
    duplicates = []
    for pull_request in pull_requests:
        if (
            pull_request.get("merge_commit_sha")
            and pull_request["merge_commit_sha"] in commit_shas
        ):
            duplicates.append(pull_request)
        else:
            kept.append(pull_request)
    return kept, duplicates


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
    inspected_prs, pr_api_status = merged_prs(since_iso)
    prs, duplicate_prs = _deduplicate_pull_requests(commits, inspected_prs)
    return {
        "checked_at": now.isoformat(),
        "since": since_iso,
        "upstream_head": new_shas[0] if new_shas else last_sha,
        "new_commit_count": len(commits),
        "algorithm_commits": [c for c in commits if c["algorithm_files"]],
        "merged_pr_count": len(inspected_prs),
        "algorithm_pull_requests": [pr for pr in prs if pr["algorithm_files"]],
        "deduplicated_pull_request_count": len(duplicate_prs),
        "category_file_counts": _category_file_counts(commits, prs),
        "pull_request_api": pr_api_status,
    }


def _category_file_counts(
    commits: Iterable[dict], pull_requests: Iterable[dict]
) -> dict[str, int]:
    counts = {"ranking": 0, "policy": 0}
    for change in [*commits, *pull_requests]:
        for changed_file in change.get("algorithm_files", []):
            category = changed_file.get("category", "ranking")
            if category in counts:
                counts[category] += 1
    return counts


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
        label = f"{changed_file.get('category', 'ranking')}/{changed_file.get('subsystem', 'unknown')}"
        lines.append(
            f"- **{changed_file['path']}** ({changed_file['status']}; {label})"
        )
        for signal_line in changed_file["signal_lines"]:
            lines.append(f"  - `{signal_line[:240]}`")
        for kind, values in changed_file.get("structural_changes", {}).items():
            if values["added"]:
                lines.append(f"  - {kind} added: `{', '.join(values['added'])[:240]}`")
            if values["removed"]:
                lines.append(
                    f"  - {kind} removed: `{', '.join(values['removed'])[:240]}`"
                )
    lines.append("")


def _write_markdown(report: dict) -> None:
    lines = [
        f"# Upstream algorithm check — {report['checked_at']}",
        "",
        f"Window start: `{report['since']}`",
        f"New commits on main: {report['new_commit_count']}",
        f"Merged PRs inspected: {report['merged_pr_count']}",
        f"Merged PRs deduplicated against commits: {report.get('deduplicated_pull_request_count', 0)}",
        f"Pull-request API: {report['pull_request_api']}",
        f"Ranking files: {report.get('category_file_counts', {}).get('ranking', 0)}",
        f"Grox policy files: {report.get('category_file_counts', {}).get('policy', 0)}",
        "",
    ]
    if not report["algorithm_commits"] and not report["algorithm_pull_requests"]:
        lines.extend(["No ranking-relevant changes.", ""])

    if report["algorithm_commits"]:
        lines.extend(["## Tracked commits", ""])
        for commit in report["algorithm_commits"]:
            heading = f"`{commit['sha']}` {commit['message']} ({commit['date']})"
            _append_change(lines, commit, heading)

    if report["algorithm_pull_requests"]:
        lines.extend(["## Tracked merged pull requests", ""])
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
    parser.add_argument(
        "--evaluate-corpus",
        action="store_true",
        help="evaluate path classification against the reviewed regression corpus",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=CORPUS_FILE,
        help="classification corpus used with --evaluate-corpus",
    )
    args = parser.parse_args(argv)
    if args.evaluate_corpus:
        report = evaluate_corpus(args.corpus)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(
                f"cases={report['cases']} "
                f"precision={report['precision']:.3f} "
                f"recall={report['recall']:.3f} "
                f"f1={report['f1']:.3f} "
                f"category_accuracy={report['category_accuracy']:.3f}"
            )
            for error in report["errors"]:
                print(
                    f"- {error['path']}: expected={error['expected']} "
                    f"predicted={error['predicted']}"
                )
        return 0
    return run(since=args.since, as_json=args.json)


if __name__ == "__main__":
    sys.exit(main())
