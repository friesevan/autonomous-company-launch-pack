#!/bin/bash
# Creates ops/inbox_pending when an allowlisted Investor opened an issue or commented
# since the last check (ops/state.json: inbox_last_check). Plain gh calls, no Claude.
# Silent when gh isn't installed or logged in. The Operator removes the marker
# after it has read and acknowledged the messages. Company-owned.
cd "$(dirname "$0")/.." || exit 0
command -v gh >/dev/null 2>&1 || exit 0
gh auth status >/dev/null 2>&1 || exit 0
REPO="${COMPANY_REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)}"
[ -n "$REPO" ] || exit 0
ME="$(gh api user -q .login 2>/dev/null)"
SINCE="$(python3 -c "import json;print(json.load(open('ops/state.json')).get('inbox_last_check','1970-01-01T00:00:00Z'))" 2>/dev/null || echo 1970-01-01T00:00:00Z)"
ALLOW="$(tr -d '\r' < investors/allowlist.md 2>/dev/null | sed 's/^[[:space:]]*@\{0,1\}//; s/[[:space:]]*$//' | grep -E '^[A-Za-z0-9-]{1,39}$')"
[ -n "$ALLOW" ] || exit 0
AUTHORS="$(
  gh api "repos/$REPO/issues/comments?since=$SINCE&per_page=100" -q '.[].user.login' 2>/dev/null
  gh api "repos/$REPO/issues?since=$SINCE&state=all&per_page=100" -q '.[] | select(.pull_request | not) | .user.login' 2>/dev/null
)"
for u in $AUTHORS; do
  [ "$u" = "$ME" ] && continue
  if grep -qx "$u" <<<"$ALLOW"; then
    touch ops/inbox_pending
    exit 0
  fi
done
exit 0
