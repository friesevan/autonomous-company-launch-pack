#!/bin/bash
# The heartbeat: tells the watchdog on GitHub (.github/workflows/watchdog.yml) that the company
# is alive, by setting the company repository's variable HEARTBEAT_AT to the current time. The
# supervisor runs it at the start of every tick and every 10 minutes during a long session. It
# never takes more than about 20 seconds, and it is silent when gh isn't set up. Company-owned.
#
# The machine user's token needs read and write access to Variables (Setup Guide, section 4).
cd "$(dirname "$0")/.." || exit 0
command -v gh >/dev/null 2>&1 || exit 0
REPO="${COMPANY_REPO:-$(git remote get-url origin 2>/dev/null | sed -E 's#^(https://|ssh://git@|git@)github\.com[:/]##; s#\.git$##')}"
case "$REPO" in
  */*) ;;
  *) exit 0 ;;
esac
gh variable set HEARTBEAT_AT --repo "$REPO" --body "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null 2>&1 &
pid=$!
( sleep 20; kill "$pid" 2>/dev/null ) &
watcher=$!
wait "$pid"
code=$?
pkill -P "$watcher" 2>/dev/null
kill "$watcher" 2>/dev/null
exit "$code"
