#!/usr/bin/env bash
# Bulk-create analysis issues in YOUR repo with GitHub CLI.
# Usage: ./create_issues.sh <owner/repo>
set -euo pipefail
REPO="${1:?usage: ./create_issues.sh <owner/repo>}"

gh label create analysis \
  --repo "$REPO" \
  --color 5319E7 \
  --description "Research and validation task" 2>/dev/null || true

for f in "$(dirname "$0")"/[0-9]*.md; do
  title=$(head -1 "$f" | sed 's/^# //')
  if gh issue list --repo "$REPO" --state all --limit 1000 --json title --jq '.[].title' \
    | grep -Fxq "$title"; then
    echo "Skipping existing: $title"
    continue
  fi
  echo "Creating: $title"
  gh issue create --repo "$REPO" --title "$title" --label analysis --body-file "$f"
done
