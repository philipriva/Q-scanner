#!/usr/bin/env bash
# Publish one scanner list per US session.
#   main      : ONLY the list txt (one file / one commit per session, as before 2026-11-05)
#   scan-meta : the *.txt.meta.json sidecar (hash-bound to the list; read by ExtraScan QQscan)
# Usage: publish_scan.sh <list-prefix> <commit-msg>
# Env: EVENT_NAME (github.event_name), META_BRANCH (default scan-meta)
set -euo pipefail
PREFIX="$1"; MSG="$2"; META_BRANCH="${META_BRANCH:-scan-meta}"; EVENT_NAME="${EVENT_NAME:-}"
out() { if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "$1" >> "$GITHUB_OUTPUT"; else echo "OUT $1"; fi; }
out "pushed=false"; out "file="; out "meta="

LATEST=$(ls -1 "${PREFIX}"*.txt 2>/dev/null | sort | tail -1 || true)
if [ -z "$LATEST" ]; then echo "No ${PREFIX}*.txt produced."; exit 0; fi
if [ -z "$(git status --porcelain -- "$LATEST")" ]; then
  echo "$LATEST unchanged by this run (scan produced nothing new); nothing to publish."; exit 0
fi
META="${LATEST}.meta.json"
if [ ! -f "$META" ]; then
  echo "::error::$LATEST produced without sidecar $META — refuse to publish (fail closed)."; exit 1
fi

HAVE_BRANCH=0
if git fetch -q origin "+refs/heads/${META_BRANCH}:refs/remotes/origin/${META_BRANCH}" 2>/dev/null; then HAVE_BRANCH=1; fi
META_ON_BRANCH=0
if [ "$HAVE_BRANCH" = 1 ] && git cat-file -e "origin/${META_BRANCH}:${META}" 2>/dev/null; then META_ON_BRANCH=1; fi

# One publish per session: a scheduled backup run does not re-commit a list that
# is already on main with its sidecar already published (manual dispatch may).
if git cat-file -e "HEAD:${LATEST}" 2>/dev/null && [ "$META_ON_BRANCH" = 1 ] && [ "$EVENT_NAME" != "workflow_dispatch" ]; then
  echo "$LATEST already published for this session (main + ${META_BRANCH}); backup run is a no-op."
  out "file=$LATEST"; out "meta=$META"; exit 0
fi

# 1) sidecar first → scan-meta branch (so consumers never see a list without its meta for long)
WT=$(mktemp -d)
if [ "$HAVE_BRANCH" = 1 ]; then
  git worktree add -q --detach "$WT" "origin/${META_BRANCH}"
else
  git worktree add -q --detach "$WT" HEAD
  (cd "$WT" && git checkout -q --orphan scan-meta-tmp && git rm -rfq . )
fi
cp "$META" "$WT/$(basename "$META")"
(
  cd "$WT"
  git add "$(basename "$META")"
  if git diff --cached --quiet; then echo "sidecar identical on ${META_BRANCH}"; else
    git commit -q -m "meta: ${LATEST}"
    git push -q origin "HEAD:refs/heads/${META_BRANCH}"
  fi
)
git worktree remove --force "$WT"

# 2) list only → main
git add -- "$LATEST"
if git diff --staged --quiet; then
  echo "$LATEST already identical on main."
else
  git commit -q -m "$MSG"
  for i in 1 2 3; do
    if git push -q; then break; fi
    [ "$i" = 3 ] && { echo "::error::push to main failed"; exit 1; }
    git pull -q --rebase
  done
  out "pushed=true"
fi
out "file=$LATEST"; out "meta=$META"
echo "Published $LATEST (main) + $META (${META_BRANCH})"
