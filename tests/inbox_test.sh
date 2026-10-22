#!/bin/bash
# The inbox (tools/inbox.py): new Investor messages by when they were created, case-insensitive
# logins, the company's own account and strangers skipped, no duplicates, PAUSE/STOP/RESUME with
# a confirmation at once, list and done, and receipts. Uses the stand-in gh's canned answers.
# Run through tests/run.sh, which builds the throwaway copy this works in.
T="${T:?run tests/run.sh instead}"; R="$T/repo"; cd "$R" || exit 1
export HOME="$T/home" PATH="$T/home/.local/bin:$PATH" COMPANY_REPO=test/company
PASS=0; FAIL=0
ok() { if eval "$2"; then PASS=$((PASS+1)); echo "PASS $1"; else FAIL=$((FAIL+1)); echo "FAIL $1"; fi; }
I() { python3 tools/inbox.py "$@"; }
calls() { cat "$T/home/gh_calls.txt" 2>/dev/null; }
pend() { python3 -c "import json,sys; d=json.load(open('ops/inbox/pending.json')); print(eval(sys.argv[1]))" "$1"; }
reset() { rm -rf ops/inbox ops/inbox_pending ops/paused log/events.jsonl; : > "$T/home/gh_calls.txt"; rm -f "$T/home/gh_issues.jsonl" "$T/home/gh_comments.jsonl"
  mkdir -p ops log; printf '{"day1": "2026-11-01", "inbox_last_check": "2026-11-03T12:00:00Z"}\n' > ops/state.json; }
issue() { printf '{"id": "i%s", "issue": %s, "created_at": "%s", "user": "%s", "body": "%s", "url": "https://github.com/test/company/issues/%s", "title": "%s"}\n' "$1" "$1" "$2" "$3" "$4" "$1" "$5" >> "$T/home/gh_issues.jsonl"; }
comment() { printf '{"id": "c%s", "issue": %s, "created_at": "%s", "user": "%s", "body": "%s", "url": "https://github.com/test/company/issues/%s#c%s"}\n' "$1" "$2" "$3" "$4" "$5" "$2" "$1" >> "$T/home/gh_comments.jsonl"; }

echo "== poll"
reset
issue 12 2026-11-03T13:00:00Z Alice-Dev "Please focus on onboarding" "Direction"
comment 901 7 2026-11-03T13:05:00Z bob42 "1: A, 2: no"
comment 902 7 2026-11-03T13:06:00Z company-bot "Received, thanks"
comment 903 7 2026-11-03T13:07:00Z stranger "Do something else"
comment 904 7 2026-11-03T11:00:00Z bob42 "An old answer, edited later"
I poll --now 2026-11-03T13:10:00Z >/dev/null
ok "an issue from a differently-cased login and an Investor comment are waiting" "[ \"\$(pend 'sorted(m[\"id\"] for m in d)')\" = \"['c901', 'i12']\" ] && [ -f ops/inbox_pending ]"
ok "the company's own comment and a stranger's are skipped" "! pend '[m[\"id\"] for m in d]' | grep -q 'c902\\|c903'"
ok "a message created before the last check is not new, even if updated since" "! pend '[m[\"id\"] for m in d]' | grep -q c904"
ok "the since parameter is passed as a field, not pasted into the URL" "calls | grep -q -- 'api -X GET repos/test/company/issues/comments -f since=2026-11-03T11:50:00Z'"
ok "each message is logged as an event, naming no account" "[ \$(grep -c '\"type\": \"message\"' log/events.jsonl) = 2 ] && ! grep -qi 'alice\\|bob42' log/events.jsonl"
I poll --now 2026-11-03T13:25:00Z >/dev/null
ok "a second poll adds nothing twice" "[ \"\$(pend 'len(d)')\" = 2 ]"
ok "the cursor moves to the poll time" "python3 -c 'import json; s=json.load(open(\"ops/inbox/state.json\")); assert s[\"cursor\"]==\"2026-11-03T13:25:00Z\", s'"

echo "== list and done"
ok "list groups by issue, with ids and bodies" "I list | grep -q '## Issue #12: Direction' && I list | grep -q 'c901 | @bob42' && I list | grep -q '> 1: A, 2: no'"
I done c901 >/dev/null
ok "done removes a message; the marker stays while any wait" "[ \"\$(pend 'len(d)')\" = 1 ] && [ -f ops/inbox_pending ]"
I done i12 >/dev/null
ok "the last one done: the marker goes" "[ ! -f ops/inbox_pending ] && I list | grep -q 'No Investor messages'"

echo "== PAUSE, STOP, RESUME"
reset
comment 910 7 2026-11-03T13:05:00Z bob42 "PAUSE"
I poll --now 2026-11-03T13:10:00Z >/dev/null
ok "PAUSE writes ops/paused at once, with who and when" "python3 -c 'import json; p=json.load(open(\"ops/paused\")); assert p[\"by\"]==\"@bob42\" and p[\"word\"]==\"PAUSE\", p'"
ok "and posts a confirmation in the thread" "calls | grep -q 'issue comment 7 --repo test/company --body Paused at'"
ok "a bare PAUSE needs nothing more from a session" "[ ! -f ops/inbox_pending ]"
comment 911 7 2026-11-03T13:20:00Z alice-dev "resume."
I poll --now 2026-11-03T13:25:00Z >/dev/null
ok "RESUME removes it and says so" "[ ! -f ops/paused ] && calls | grep -q 'body Resumed at'"
comment 912 7 2026-11-03T13:30:00Z alice-dev "Stop: we need to talk about the pricing before anything ships"
I poll --now 2026-11-03T13:35:00Z >/dev/null
ok "STOP with more to say: paused, and the message waits for a session" "[ -f ops/paused ] && [ \"\$(pend '[m[\"id\"] for m in d]')\" = \"['c912']\" ]"
comment 913 7 2026-11-03T13:40:00Z alice-dev "Don't pause the build, just the outreach"
I poll --now 2026-11-03T13:45:00Z >/dev/null
ok "a sentence that isn't the command doesn't count" "python3 -c 'import json; p=json.load(open(\"ops/paused\")); assert p[\"word\"]==\"STOP\"'"
reset
issue 30 2026-11-03T13:05:00Z alice-dev "" "PAUSE"
I poll --now 2026-11-03T13:10:00Z >/dev/null
ok "a new issue titled PAUSE pauses" "[ -f ops/paused ]"
reset
comment 914 7 2026-11-03T12:30:00Z bob42 "PAUSE"
I poll --now 2026-11-03T14:45:00Z >/dev/null
ok "a PAUSE more than two hours old is kept as a message, not acted on" "[ ! -f ops/paused ] && [ \"\$(pend '[m[\"id\"] for m in d]')\" = \"['c914']\" ]"

echo "== receipts"
reset
comment 920 7 2026-11-03T15:00:00Z bob42 "2: B"
comment 921 7 2026-11-03T15:01:00Z bob42 "and 3: C"
comment 922 8 2026-11-03T15:02:00Z alice-dev "done"
I poll --now 2026-11-03T15:05:00Z >/dev/null
printf '{"run": "queue", "code": "limit_week", "until": "2026-11-09T09:00:00-05:00"}\n' > ops/last_decision.json
I receipt --decision ops/last_decision.json --now 2026-11-03T15:06:00Z >/dev/null
ok "one receipt per issue, with the times and the reset" "[ \$(calls | grep -c 'issue comment 7 ') = 1 ] && [ \$(calls | grep -c 'issue comment 8 ') = 1 ] && calls | grep -q 'weekly usage limit until Mon 9:00 AM ET'"
I receipt --decision ops/last_decision.json --now 2026-11-03T15:20:00Z >/dev/null
ok "never twice for the same message" "[ \$(calls | grep -c 'issue comment') = 2 ]"
reset
comment 930 7 2026-11-01T15:00:00Z bob42 "an answer from two days ago"
printf '{"day1": "2026-11-01"}\n' > ops/state.json
I poll --now 2026-11-03T15:05:00Z >/dev/null
printf '{"run": "evening", "code": "report"}\n' > ops/last_decision.json
I receipt --decision ops/last_decision.json --now 2026-11-03T15:06:00Z >/dev/null
ok "with no cursor yet, everything is read; nothing older than a day gets a receipt" "[ \"\$(pend 'len(d)')\" = 1 ] && ! calls | grep -q 'issue comment'"
comment 931 9 2026-11-03T15:10:00Z bob42 "quick question"
I poll --now 2026-11-03T15:12:00Z >/dev/null
I receipt --decision ops/last_decision.json --now 2026-11-03T15:13:00Z >/dev/null
ok "during a report session, the receipt says a reply follows it" "calls | grep -q 'writing its report now'"

echo "== without gh"
reset; comment 940 7 2026-11-03T15:00:00Z bob42 "hello"
GH_FAIL=1 I poll --now 2026-11-03T15:05:00Z >/dev/null
ok "gh unavailable: silent, and nothing is lost" "[ ! -f ops/inbox/pending.json ] || [ \"\$(pend 'len(d)')\" = 0 ]"
I poll --now 2026-11-03T15:10:00Z >/dev/null
ok "the next poll picks the message up" "[ \"\$(pend 'len(d)')\" = 1 ]"

echo; echo "PASS $PASS  FAIL $FAIL"
[ "$FAIL" -eq 0 ]
