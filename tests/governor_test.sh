#!/bin/bash
# The governor's decisions and figures without the supervisor: the plan's meter and calibration,
# the plan by now and its reasons, API-credit overflow and its caps, inbox sessions, the hold and
# the pause, dry runs, outages, and the report's usage block.
# Run through tests/run.sh, which builds the throwaway copy this works in.
T="${T:?run tests/run.sh instead}"; R="$T/repo"; cd "$R" || exit 1
export HOME="$T/home" PATH="$T/home/.local/bin:$PATH"
PASS=0; FAIL=0
ok() { if eval "$2"; then PASS=$((PASS+1)); echo "PASS $1"; else FAIL=$((FAIL+1)); echo "FAIL $1"; fi; }
G() { python3 tools/governor.py "$@"; }
dec() { G decide --now "$1" ${3:-} | python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1]))" "$2"; }
st() { G status --json --now "$1" | python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1]))" "$2"; }
setu() { python3 -c "import json,sys; u=json.load(open('ops/usage.json')); exec(sys.argv[1]); json.dump(u,open('ops/usage.json','w'))" "$1"; }
sets() { python3 -c "import json,sys; u=json.load(open('ops/state.json')); exec(sys.argv[1]); json.dump(u,open('ops/state.json','w'))" "$1"; }
u() { python3 -c "import json,sys; d=json.load(open('ops/usage.json')); print(eval(sys.argv[1]))" "$1"; }
reset() { rm -f ops/usage.json ops/state.json ops/inbox_pending ops/ticks.jsonl ops/paused ops/hold log/events.jsonl; mkdir -p ops/runs log
  G set-day1 2026-11-01 >/dev/null; G set-budget 140 >/dev/null; printf -- "- [ ] build the thing\n" > ops/board.md; }
meter_run() {  # meter_run <file> <session%> <week%> <fable%> [credits_on]
  python3 - "$@" <<'EOF'
import json, sys
path, s, w, f = sys.argv[1:5]
credits = len(sys.argv) > 5 and sys.argv[5] == "on"
limits = [{"kind": "session", "group": "session", "percent": float(s), "resets_at": "2026-11-03T20:00:00Z"},
          {"kind": "weekly_all", "group": "weekly", "percent": float(w), "resets_at": "2026-11-08T14:00:00Z"},
          {"kind": "weekly_scoped", "group": "weekly", "percent": float(f), "resets_at": "2026-11-08T14:00:00Z",
           "scope": {"model": {"display_name": "Fable"}}}]
lines = [{"type": "system", "subtype": "init"},
         {"type": "assistant", "usage_report": {"rate_limits": {"limits": limits, "extra_usage": {"is_enabled": credits}}},
          "message": {"id": "u", "content": []}},
         {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0, "local_command": "usage"}]
open(path, "w").write("\n".join(json.dumps(l) for l in lines) + "\n")
EOF
}
N=2026-11-03T10:00:00-05:00

echo "== the meter"
reset
meter_run "$T/m1.jsonl" 10 20 5
G meter "$T/m1.jsonl" --now $N >/dev/null
ok "a reading anchors the week to the plan's reset" "[ \"\$(u 'd[\"week_anchor\"]')\" = 2026-11-01T09:00:00-05:00 ]"
ok "status reads the meter" "[ \"\$(st 2026-11-03T10:05:00-05:00 'd[\"plan\"][\"source\"], d[\"plan\"][\"week\"][\"actual_pct\"], d[\"plan\"][\"five_hour\"][\"actual_pct\"], d[\"plan\"][\"fable\"][\"actual_pct\"]')\" = \"('meter', 20.0, 10.0, 5.0)\" ]"
setu 'u["plan_cost_total"] = u.get("plan_cost_total", 0) + 28.0; u["fable_cost_total"] = 7.0'
meter_run "$T/m2.jsonl" 30 40 15
G meter "$T/m2.jsonl" --now 2026-11-03T14:00:00-05:00 >/dev/null
ok "two readings calibrate the weekly budget: \$28 over 20 points = \$140" "[ \"\$(u 'd[\"weekly_budget_usd\"]')\" = 140.0 ]"
ok "and the 5-hour and Fable budgets" "[ \"\$(u 'd[\"five_hour_budget_usd\"], d[\"fable_budget_usd\"]')\" = '(140.0, 70.0)' ]"
ok "meter --due: not again within 10 minutes" "! G meter --due --now 2026-11-03T14:05:00-05:00 && G meter --due --now 2026-11-03T14:15:00-05:00"
meter_run "$T/m3.jsonl" 100 41 15
G meter "$T/m3.jsonl" --now 2026-11-03T14:30:00-05:00 >/dev/null
ok "at 100% of the 5-hour window: paused until its reset, before any session" "[ \"\$(u 'd[\"rate_limit_until\"], d[\"rate_limit_kind\"]')\" = \"('2026-11-03T15:00:00-05:00', 'session')\" ]"
ok "the decision queues with the limit's code" "[ \"\$(dec 2026-11-03T14:35:00-05:00 'd[\"run\"], d[\"code\"], d[\"until\"]')\" = \"('queue', 'limit_5h', '2026-11-03T15:00:00-05:00')\" ]"
meter_run "$T/m4.jsonl" 2 41 100
G meter "$T/m4.jsonl" --now 2026-11-03T14:50:00-05:00 >/dev/null
ok "the window reopens early: the pause ends; Fable at 100% is blocked" "[ \"\$(u 'd[\"rate_limit_until\"], d[\"fable_blocked_until\"] is not None')\" = '(None, True)' ]"
meter_run "$T/m5.jsonl" 2 41 20 on
G meter "$T/m5.jsonl" --now 2026-11-03T15:10:00-05:00 >/dev/null
ok "Fable under 98% again: unblocked; usage credits on: flagged" "[ \"\$(u 'd[\"fable_blocked_until\"], d[\"credits_on_at\"] is not None')\" = '(None, True)' ]"
printf '{"type":"result","subtype":"success","is_error":false,"total_cost_usd":0.004,"result":"I am not sure what /usage means"}\n' > "$T/m6.jsonl"
G meter "$T/m6.jsonl" --now 2026-11-03T15:30:00-05:00 >/dev/null
ok "no usage report: backs off 6 hours, and counts anything it spent" "[ \"\$(u 'd[\"meter_failed_at\"] is not None')\" = True ] && ! G meter --due --now 2026-11-03T20:00:00-05:00 && G meter --due --now 2026-11-03T21:40:00-05:00"

echo "== the plan by now, and why"
reset
G set-anchor 2026-11-01T00:00:00-04:00 >/dev/null
setu 'u["days"]={"2026-11-01":10,"2026-11-02":10}'
python3 - <<'EOF'
import json, datetime as dt
lines = []
t = dt.datetime.fromisoformat("2026-11-02T00:00:00-05:00")
for i in range(32):          # 8 hours at the 5-hour limit
    lines.append({"at": (t + dt.timedelta(minutes=15 * i)).isoformat(), "run": "queue", "code": "limit_5h", "billing": "plan"})
for i in range(32, 48):      # 4 hours of work
    lines.append({"at": (t + dt.timedelta(minutes=15 * i)).isoformat(), "run": "work", "code": "work", "billing": "plan"})
for i in range(48, 56):      # 2 hours on API credits
    lines.append({"at": (t + dt.timedelta(minutes=15 * i)).isoformat(), "run": "work", "code": "work", "billing": "api"})
open("ops/ticks.jsonl", "w").write("".join(json.dumps(l) + "\n" for l in lines))
EOF
ok "behind: the plan by now, the points, and the status" "[ \"\$(st $N 'd[\"plan\"][\"week\"][\"status\"], d[\"plan\"][\"week\"][\"plan_pct\"] > d[\"plan\"][\"week\"][\"actual_pct\"]')\" = \"('behind', True)\" ]"
ok "why: the hours lost to the 5-hour limit, and the hours on credits" "st $N '\" \".join(d[\"plan\"][\"reasons\"])' | grep -q '8 h this week at the 5-hour limit' && st $N '\" \".join(d[\"plan\"][\"reasons\"])' | grep -q '2 h this week ran on API credits'"
ok "hours by state" "[ \"\$(st $N 'd[\"plan\"][\"hours\"][\"limit_5h\"], d[\"plan\"][\"hours\"][\"work\"], d[\"plan\"][\"hours\"][\"overflow\"]')\" = '(8.0, 4.0, 2.0)' ]"
ok "a gap between ticks is offline time" "st $N 'd[\"plan\"][\"hours\"].get(\"offline\", 0) > 1'"
ok "report-usage: the plan-by-now column and the pace line" "G report-usage --now $N | grep -q 'Plan by now' && G report-usage --now $N | grep -q 'points behind the week'"
ok "the board is empty: said so" "printf '' > ops/board.md; st $N '\" \".join(d[\"plan\"][\"reasons\"])' | grep -q 'no open tasks'"

echo "== API-credit overflow"
reset; G mark-limit 12 --now $N >/dev/null
ok "a limit without a key: queue" "[ \"\$(dec $N 'd[\"run\"], d[\"code\"]')\" = \"('queue', 'limit_5h')\" ]"
ok "a limit with a key: a work session on credits, Fable off, capped at the weekly overflow cap" "[ \"\$(dec $N 'd[\"run\"], d[\"billing\"], d[\"fable_ok\"], d[\"max_budget_usd\"] <= 50' --api-ready)\" = \"('work', 'api', False, True)\" ]"
sets 'u["last_evening_date"]="2026-11-02"'
ok "a report due during a limit runs on credits too" "[ \"\$(dec 2026-11-03T18:05:00-05:00 'd[\"run\"], d[\"billing\"]' --api-ready)\" = \"('evening', 'api')\" ]"
setu 'u["api_days"]={"2026-11-02":30.0,"2026-11-03":19.8}'
ok "the week's overflow cap used: queue, and why" "[ \"\$(dec $N 'd[\"run\"]' --api-ready)\" = queue ] && dec $N 'd[\"reason\"]' --api-ready | grep -q 'overflow cap'"
setu 'u["api_days"]={"2026-10-02":195.0}'
ok "last cycle's spend doesn't count" "[ \"\$(dec $N 'd[\"billing\"]' --api-ready)\" = api ]"
setu 'u["api_days"]={"2026-11-01":100.0,"2026-11-02":95.0}'
ok "down to the reserve this cycle: queue, and why" "[ \"\$(dec $N 'd[\"run\"]' --api-ready)\" = queue ] && dec $N 'd[\"reason\"]' --api-ready | grep -q 'reserve'"
setu 'u["api_days"]={}'
printf '{"api_overflow": false}\n' > investors/billing.json
ok "the Investors' switch off: queue" "[ \"\$(dec $N 'd[\"run\"]' --api-ready)\" = queue ] && dec $N 'd[\"reason\"]' --api-ready | grep -q 'switched off'"
git checkout -q -- investors/billing.json 2>/dev/null || printf '{"api_overflow": true, "monthly_credits_usd": 200, "reserve_usd": 10, "weekly_cap_usd": 50, "cycle_day": 1}\n' > investors/billing.json
setu 'u["api_mismatch_at"]="2026-11-02T10:00:00-05:00"'
ok "after a key-source mismatch: overflow off for a week" "[ \"\$(dec $N 'd[\"run\"]' --api-ready)\" = queue ]"
ok "status shows the credits as percentages" "[ \"\$(st $N 'd[\"api\"][\"enabled\"], \"month_pct\" in d[\"api\"]')\" = '(True, True)' ]"

echo "== inbox sessions, the hold, the pause"
reset; touch ops/inbox_pending; setu 'u["days"]={"2026-11-03":30}'
ok "a message waits and today's share is spent: a short inbox session" "[ \"\$(dec $N 'd[\"run\"], d[\"effort\"], d[\"max_turns\"], d[\"inbox_only\"]')\" = \"('inbox', 'low', 15, True)\" ]"
sets 'u["last_inbox_at"]="2026-11-03T09:50:00-05:00"'
ok "at most every 20 minutes" "[ \"\$(dec $N 'd[\"run\"]')\" = queue ] && [ \"\$(dec 2026-11-03T10:15:00-05:00 'd[\"run\"]')\" = inbox ]"
reset; touch ops/inbox_pending; printf '' > ops/board.md; sets 'u["last_work_at"]="2026-11-03T09:50:00-05:00"'
ok "a message waits and the board is empty: an inbox session, not a skip" "[ \"\$(dec $N 'd[\"run\"]')\" = inbox ]"
reset; touch ops/hold
ok "the Day 1 hold: nothing runs" "[ \"\$(dec $N 'd[\"run\"], d[\"code\"]')\" = \"('hold', 'hold')\" ]"
ok "a dry run looks past it, and logs nothing" "rm -f ops/ticks.jsonl; [ \"\$(dec $N 'd[\"run\"]' --dry-run)\" = work ] && [ ! -f ops/ticks.jsonl ]"
rm -f ops/hold; printf '{"by": "@bob42", "word": "STOP"}\n' > ops/paused
ok "paused by an Investor: nothing runs, even with a message waiting" "touch ops/inbox_pending; [ \"\$(dec $N 'd[\"run\"], d[\"code\"]')\" = \"('hold', 'paused')\" ] && dec $N 'd[\"reason\"]' | grep -q 'RESUME'"

echo "== outages"
reset
G decide --now 2026-11-03T10:00:00-05:00 >/dev/null
G decide --now 2026-11-03T10:15:00-05:00 >/dev/null
ok "consecutive ticks: no outage" "! grep -q outage log/events.jsonl 2>/dev/null"
G decide --now 2026-11-03T13:15:00-05:00 >/dev/null
ok "a 3-hour gap: an outage event for the next report" "grep -q '\"type\": \"outage\"' log/events.jsonl && grep -q 'about 3 h' log/events.jsonl"

echo "== record: limits, credits, key sources"
reset
printf '%s\n' '{"type":"system","subtype":"init","apiKeySource":"none","permissionMode":"auto"}' \
  '{"type":"assistant","error":"rate_limit","message":{"id":"a","content":[]}}' \
  '{"type":"result","subtype":"error_during_execution","is_error":true,"errors":["429"],"api_error_status":429,"terminal_reason":"api_error","total_cost_usd":0.01}' > "$T/r1.jsonl"
G record "$T/r1.jsonl" --type work --exit 1 --now $N >/dev/null
ok "an assistant rate_limit error with a 429: a limit, paused 5 hours" "[ \"\$(u 'd[\"runs\"][-1][\"limited\"], d[\"rate_limit_until\"]')\" = \"(True, '2026-11-03T15:00:00-05:00')\" ]"
reset
printf '%s\n' '{"type":"system","subtype":"init","apiKeySource":"/login managed key","permissionMode":"default"}' \
  '{"type":"result","subtype":"success","is_error":false,"result":"ok","total_cost_usd":0.2}' > "$T/r2.jsonl"
G record "$T/r2.jsonl" --type work --exit 0 --now $N >/dev/null
ok "a plan run on a Console key: a mismatch; not in auto mode: flagged" "[ \"\$(u 'd[\"runs\"][-1][\"billing_mismatch\"], d[\"runs\"][-1][\"mode_ok\"], d[\"api_mismatch_at\"] is not None')\" = '(True, False, True)' ]"
reset
G record "$T/r2.jsonl" --type work --exit 143 --now $N >/dev/null
ok "exit 143 (stopped by the time limit): timed out, not retried" "[ \"\$(u 'd[\"runs\"][-1][\"timed_out\"], d[\"runs\"][-1][\"retry\"]')\" = '(True, False)' ]"

echo; echo "PASS $PASS  FAIL $FAIL"
[ "$FAIL" -eq 0 ]
