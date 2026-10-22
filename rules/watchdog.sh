#!/bin/bash
# The watchdog's check. .github/workflows/watchdog.yml runs it on GitHub's servers every 30
# minutes, never on the Mac, so it works when the Mac can't. Investors own this file.
#
# When the company's heartbeat (the repository variable HEARTBEAT_AT, set by the Mac every 15
# minutes) is older than 45 minutes, missing after Day 1, or set in the future, it opens one
# Emergency issue that @mentions both Investors. When the heartbeat is fresh again, it comments
# and closes that issue. It never opens a second issue for the same outage.
#
#   HEARTBEAT_AT   the last heartbeat, ISO 8601 (the workflow passes vars.HEARTBEAT_AT)
#   STATE_JSON     ops/state.json from the repository, to know whether Day 1 has started
#   ALLOWLIST      investors/allowlist.md, whom to @mention
#   TEST=true      open and close a test issue, so both Investors see a notification arrive
#   NOW            the current time in epoch seconds (tests); GH_REPO and GH_TOKEN for gh
set -u
STALE_MINUTES=45
MARK="<!-- company-watchdog"   # the issue body carries "<!-- company-watchdog since=<epoch> -->"
now="${NOW:-$(date -u +%s)}"

epoch() {
  python3 -c 'import sys, datetime as d
print(int(d.datetime.fromisoformat(sys.argv[1].strip().replace("Z", "+00:00")).timestamp()))' "$1" 2>/dev/null
}
eastern() {
  python3 -c 'import sys, datetime as d, zoneinfo
t = d.datetime.fromtimestamp(int(sys.argv[1]), zoneinfo.ZoneInfo("America/New_York"))
print("%s %s %d, %d:%s ET" % (t.strftime("%a"), t.strftime("%b"), t.day, int(t.strftime("%I")), t.strftime("%M %p")))' "$1"
}
duration() {
  local m=$(( $1 / 60 ))
  if [ "$m" -lt 90 ]; then echo "$m minutes"; else echo "$(( (m + 30) / 60 )) hours"; fi
}
mentions() {
  tr -d '\r' < "${ALLOWLIST:-investors/allowlist.md}" 2>/dev/null | sed 's/^[[:space:]]*@\{0,1\}//; s/[[:space:]]*$//' \
    | grep -E '^[A-Za-z0-9-]{1,39}$' | sed 's/^/@/' | tr '\n' ' '
}
create() {  # create <title> <body>: an Emergency issue, or a plain one if the label is missing
  gh issue create --label emergency --title "$1" --body "$2" 2>/dev/null \
    || gh issue create --title "EMERGENCY: $1" --body "$2"
}

if [ "${TEST:-false}" = true ]; then
  url="$(create "Watchdog test: you can ignore this" "This is a test of the company's watchdog, which runs on GitHub every 30 minutes and opens an issue like this when the Mac mini stops checking in. If you got a notification, the alerts reach you. This issue closes itself.

$(mentions)")"
  gh issue close "${url##*/}" --comment "Test complete; closed automatically." >/dev/null
  echo "test issue: $url"
  exit 0
fi

open_issue="$(gh issue list --state open --limit 400 --json number,body \
  --jq "[.[] | select(.body | contains(\"$MARK\"))][0].number // empty" 2>/dev/null)"
day1="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("day1") or "")' "${STATE_JSON:-ops/state.json}" 2>/dev/null)"
beat=""
[ -n "${HEARTBEAT_AT:-}" ] && beat="$(epoch "$HEARTBEAT_AT")"

problem=""
# Before Day 1 nothing runs yet, so a quiet heartbeat (say, one set by hand to test) means nothing.
if [ -z "$day1" ]; then echo "Day 1 hasn't started: nothing to watch"; exit 0; fi
if [ -z "$beat" ]; then
  problem="The company has started (Day 1 was $day1) but the watchdog has no heartbeat from the Mac mini at all."
elif [ "$beat" -gt $(( now + 600 )) ]; then
  problem="The company's heartbeat is set in the future ($HEARTBEAT_AT), so the watchdog can't tell whether the Mac mini is running."
elif [ $(( now - beat )) -ge $(( STALE_MINUTES * 60 )) ]; then
  problem="The Mac mini last checked in at $(eastern "$beat"), $(duration $(( now - beat ))) ago. Its run loop sends a heartbeat every 15 minutes, so the company has probably stopped: no sessions, reports, or replies until someone looks."
fi

if [ -z "$problem" ]; then
  if [ -n "$open_issue" ]; then
    since="$(gh issue view "$open_issue" --json body --jq .body 2>/dev/null | sed -n 's/.*company-watchdog since=\([0-9]*\).*/\1/p' | head -1)"
    out=""
    [ -n "$since" ] && [ "$beat" -gt "$since" ] && out=" The company was out for about $(duration $(( beat - since )))."
    gh issue close "$open_issue" --comment "The heartbeat is back: the Mac mini checked in at $(eastern "$beat").$out The company picks up where it left off; its next report covers the gap." >/dev/null
    echo "back online; closed #$open_issue"
  else
    echo "heartbeat fresh: $HEARTBEAT_AT"
  fi
  exit 0
fi

if [ -n "$open_issue" ]; then
  echo "still down; #$open_issue is open"
  exit 0
fi
title="The company has stopped: no heartbeat from the Mac mini"
[ -n "$beat" ] && [ "$beat" -le "$now" ] && title="$title since $(eastern "$beat")"
body="$problem

Likely causes, most common first:

1. **A restart or a power cut.** The Mac waits at the FileVault password screen. Type the password at the Mac, or, from a computer on the same network, run \`ssh <account>@<mac-name>.local\` and enter the account password (macOS 26 or later, with Remote Login on).
2. **No network.** Check the Mac's Ethernet or Wi-Fi.
3. **The company's GitHub token expired.** Create a new one for the machine user (Setup Guide, section 4), then run \`gh auth login\` on the Mac.
4. **The run loop stopped.** On the Mac, in the company folder, run \`tail -50 ops/runs/supervisor.log\`, and \`tools/install-launchd.sh\` to start it again.

This issue closes itself when the heartbeat returns. The watchdog runs on GitHub every 30 minutes (Actions tab, Watchdog).

$(mentions)
<!-- company-watchdog since=${beat:-0} -->"
url="$(create "$title" "$body")"
echo "opened $url"
exit 0
