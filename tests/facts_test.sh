#!/bin/bash
# The report facts file (tools/report_facts.py): one short file with everything a report
# needs, business only, so a report session reads one file. Run through tests/run.sh,
# which builds the throwaway copy this works in.
T="${T:?run tests/run.sh instead}"; R="$T/repo"; cd "$R" || exit 1
export HOME="$T/home" PATH="$T/home/.local/bin:$PATH"
PASS=0; FAIL=0
ok() { if eval "$2"; then PASS=$((PASS+1)); echo "PASS $1"; else FAIL=$((FAIL+1)); echo "FAIL $1"; fi; }
commit_at() { GIT_AUTHOR_DATE="$1" GIT_COMMITTER_DATE="$1" git -c user.name="$2" -c user.email=x@example.com commit -q -m "$3"; }
F=ops/report_facts.md

mkdir -p log reports ops
python3 tools/governor.py set-day1 2026-11-01 >/dev/null
printf '2026-11-03T18:00:00-05:00\n' > reports/last_report.txt
cat > log/events.jsonl <<'EOF'
{"time": "2026-11-03T17:00:00-05:00", "worker": "maya", "type": "commit", "summary": "Before the window", "link": ""}
{"time": "2026-11-03T21:00:00-05:00", "worker": "maya", "type": "build", "summary": "Clean build on the Simulator", "link": ""}
{"time": "2026-11-03T22:00:00-05:00", "worker": "maya", "type": "mood", "summary": "Maya feels great", "link": ""}
{"time": "2026-11-03T22:30:00-05:00", "worker": "ceo", "type": "interview", "summary": "Interviewed Noor", "link": ""}
{"time": "2026-11-04T01:00:00-05:00", "worker": "operator", "type": "message", "summary": "Investor asked for a TestFlight build", "link": ""}
{"time": "2026-11-04T02:00:00-05:00", "worker": "operator", "type": "report", "summary": "Report 6 published", "link": ""}
EOF
printf -- '- [ ] Ship the onboarding\n- [ ] Write the privacy policy\n' > ops/board.md
git add -A && commit_at 2026-11-03T20:00:00-05:00 Operator "ops: evening run"
printf -- '- [x] Ship the onboarding\n- [ ] Write the privacy policy\n' > ops/board.md
git add -A && commit_at 2026-11-03T23:00:00-05:00 Maya "Onboarding screens done"

echo "== evening facts"
ok "builds the facts file" "python3 tools/report_facts.py --kind evening --now 2026-11-04T06:00:00-05:00 | grep -q 'report facts:' && [ -s $F ]"
ok "names the report and the day" "grep -q 'evening report of Day 4' $F"
ok "scoreboard first" "grep -q '^## Scoreboard' $F && grep -q 'Net proceeds' $F"
ok "business events in the window only" "grep -q 'Clean build on the Simulator' $F && ! grep -q 'Before the window' $F"
ok "moods, interviews, and report notices are left to the records" "! grep -q 'Maya feels great' $F && ! grep -q 'Interviewed Noor' $F && ! grep -q 'Report 6 published' $F"
ok "who worked, for the diaries" "awk '/^## Who worked/{f=1;next} /^## /{f=0} f' $F | grep -q maya"
ok "Investor messages" "awk '/^## Investor messages/{f=1;next} /^## /{f=0} f' $F | grep -q 'TestFlight build'"
ok "commits by workers, not the Operator" "grep -q 'Maya: Onboarding screens done' $F && ! grep -q 'ops: evening run' $F"
ok "tasks finished since the last report, and what is open" "grep -q 'Finished since the last report (1): Ship the onboarding' $F && grep -q 'Open (1): Write the privacy policy' $F"
ok "usage in percent, no dollars" "awk '/^## Usage/{f=1;next} /^## /{f=0} f' $F | grep -q 'of the weekly limit' && ! awk '/^## Usage/{f=1;next} /^## /{f=0} f' $F | grep -q '[\$]'"
ok "no week sections on an ordinary evening" "! grep -q '^## The week in usage' $F"

echo "== weekly facts"
ok "weekly adds the week's usage against the caps and the optimizations" "python3 tools/report_facts.py --kind weekly --now 2026-11-07T18:30:00-05:00 >/dev/null && grep -q '^## The week in usage' $F && grep -q '^## Optimizations' $F"

echo "== no previous report"
rm -f reports/last_report.txt
ok "covers the time since Day 1 began" "python3 tools/report_facts.py --kind evening --now 2026-11-01T18:00:00-05:00 >/dev/null && grep -q 'Covers Sun Nov 1, 00:00' $F"

echo; echo "PASS $PASS  FAIL $FAIL"
[ "$FAIL" -eq 0 ]
