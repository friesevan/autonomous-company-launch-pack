#!/bin/bash
# SessionStart hook: marks that this session loaded the company's hooks. The supervisor removes the
# mark before every session and checks it after; a session that ran turns without it means Claude
# Code skipped the hooks (and probably CLAUDE.md), so the company pauses itself and opens an
# Emergency. The mark is written only when every guard the settings name is in place, so a deleted
# or renamed guard stops the company the same way. Prints nothing: SessionStart output would go
# into the session's context. Investors own this file.
root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
for f in protect-records.sh security-guard.py model-guard.py config-guard.py; do
  [ -s "$root/rules/hooks/$f" ] || exit 0
done
mkdir -p "$root/ops" 2>/dev/null
date '+%F %T' > "$root/ops/.hooks_ok" 2>/dev/null
exit 0
