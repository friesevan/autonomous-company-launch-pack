#!/bin/bash
# The watchdog (rules/watchdog.sh, run by .github/workflows/watchdog.yml on GitHub's servers):
# nothing to watch before Day 1, an alert for a missing, stale, or future heartbeat, never two for
# one outage, and a "back online" close when the heartbeat returns. Uses the stand-in gh.
# Run through tests/run.sh, which builds the throwaway copy this works in.
T="${T:?run tests/run.sh instead}"; R="$T/repo"; cd "$R" || exit 1
export HOME="$T/home" PATH="$T/home/.local/bin:$PATH" ALLOWLIST=investors/allowlist.md STATE_JSON="$T/state.json"
PASS=0; FAIL=0
ok() { if eval "$2"; then PASS=$((PASS+1)); echo "PASS $1"; else FAIL=$((FAIL+1)); echo "FAIL $1"; fi; }
calls() { cat "$T/home/gh_calls.txt" 2>/dev/null; }
NOW=$(python3 -c 'import datetime as d; print(int(d.datetime.fromisoformat("2026-11-03T15:00:00+00:00").timestamp()))')
W() { NOW=$NOW bash rules/watchdog.sh 2>&1; }
reset() { : > "$T/home/gh_calls.txt"; rm -f "$T/home/gh_issue_list.json" "$T/home/gh_issue_view.json"; }
open_issue() {  # an open watchdog issue, opened when the heartbeat stopped at $1
  printf '[{"number": 41, "body": "stopped\\n<!-- company-watchdog since=%s -->"}]\n' "$1" > "$T/home/gh_issue_list.json"
  printf '{"body": "stopped\\n<!-- company-watchdog since=%s -->"}\n' "$1" > "$T/home/gh_issue_view.json"
}

echo "== before Day 1"
reset; printf '{"day1": null}\n' > "$STATE_JSON"
ok "no heartbeat and no Day 1: nothing to watch" "HEARTBEAT_AT= W | grep -q 'nothing to watch' && ! calls | grep -q 'issue create'"
ok "a stale heartbeat set by hand before Day 1 (the setup test): still nothing" "HEARTBEAT_AT=2026-11-03T10:00:00Z W | grep -q 'nothing to watch' && ! calls | grep -q 'issue create'"

echo "== the company is running"
reset; printf '{"day1": "2026-11-01"}\n' > "$STATE_JSON"
ok "a fresh heartbeat (10 minutes): nothing to do" "HEARTBEAT_AT=2026-11-03T14:50:00Z W | grep -q 'heartbeat fresh' && ! calls | grep -q 'issue create'"
reset
ok "a stale heartbeat (an hour): one Emergency" "HEARTBEAT_AT=2026-11-03T14:00:00Z W | grep -q opened && [ \$(calls | grep -c 'issue create --label emergency') = 1 ]"
ok "it says since when, in Eastern time, and @mentions both Investors" "calls | grep -q 'no heartbeat from the Mac mini since Tue Nov 3, 9:00 AM ET' && calls | grep -q '@alice-dev @bob42'"
ok "it lists the likely causes and the FileVault unlock over SSH" "calls | grep -q 'FileVault password screen' && calls | grep -q 'ssh <account>@<mac-name>.local'"
ok "it carries the hidden marker with the last heartbeat" "calls | grep -q 'company-watchdog since='"
reset; open_issue "$((NOW - 3600))"
ok "still down with the issue open: no second issue" "HEARTBEAT_AT=2026-11-03T14:00:00Z W | grep -q 'still down' && ! calls | grep -q 'issue create'"
reset; open_issue "$((NOW - 7200))"
ok "the heartbeat returns: the issue closes with how long it was out" "HEARTBEAT_AT=2026-11-03T14:55:00Z W | grep -q 'back online' && calls | grep -q 'issue close 41 --comment The heartbeat is back' && calls | grep -q 'out for about 2 hours'"
reset
ok "no heartbeat at all after Day 1: an Emergency" "HEARTBEAT_AT= W >/dev/null; calls | grep -q 'no heartbeat from the Mac mini at all'"
reset
ok "a heartbeat set in the future: an Emergency" "HEARTBEAT_AT=2026-11-04T15:00:00Z W >/dev/null; calls | grep -q 'set in the future'"
reset
ok "the emergency label missing: a plain issue titled EMERGENCY" "GH_FAIL_LABEL=1 HEARTBEAT_AT=2026-11-03T14:00:00Z W >/dev/null; calls | grep -q 'issue create --title EMERGENCY: The company has stopped'"

echo "== test mode"
reset
ok "TEST=true opens and closes a test issue" "TEST=true W | grep -q 'test issue' && calls | grep -q 'issue create --label emergency --title Watchdog test' && calls | grep -q 'issue close'"

echo "== the workflow"
Y=.github/workflows/watchdog.yml
ok "runs every 30 minutes and by hand, off the top of the hour" "grep -q 'cron: \"8,38 \* \* \* \*\"' $Y && grep -q 'workflow_dispatch' $Y"
ok "only writes issues, and skips the Launch Pack itself" "grep -q 'issues: write' $Y && grep -q 'contents: read' $Y && grep -q \"github.repository != 'friesevan/autonomous-company-launch-pack'\" $Y"
ok "reads the heartbeat variable and runs this script from the repository" "grep -q 'vars.HEARTBEAT_AT' $Y && grep -q 'bash rules/watchdog.sh' $Y"
ok "the Mac sets the heartbeat with gh, in the background of every tick" "grep -q 'gh variable set HEARTBEAT_AT' tools/heartbeat.sh && grep -q 'tools/heartbeat.sh' tools/supervisor.sh"

echo; echo "PASS $PASS  FAIL $FAIL"
[ "$FAIL" -eq 0 ]
