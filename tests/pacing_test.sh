#!/bin/bash
# Tenet 7 pacing: pace flags, backlog sessions, the reserve, the last day of the
# week, self-calibration from limit hits and fully spent weeks, the week anchor.
# Run through tests/run.sh, which builds the throwaway copy this works in.
T="${T:?run tests/run.sh instead}"; R="$T/repo"; cd "$R" || exit 1
export CLAUDE_BIN="$T/bin/claude" FAKE_ARGS="$T/args.txt" FAKE_COUNT="$T/count.txt" HOME="$T/home"
export PATH="$T/home/.local/bin:$PATH" SECURITY_BIN=false COMPANY_REPO=test/company
PASS=0; FAIL=0
ok() { if eval "$2"; then PASS=$((PASS+1)); echo "PASS $1"; else FAIL=$((FAIL+1)); echo "FAIL $1"; fi; }
G() { python3 tools/governor.py "$@"; }
dec() { G decide --now "$1" | python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1]))" "$2"; }
setu() { python3 -c "import json,sys; u=json.load(open('ops/usage.json')); exec(sys.argv[1]); json.dump(u,open('ops/usage.json','w'))" "$1"; }
sets() { python3 -c "import json,sys; u=json.load(open('ops/state.json')); exec(sys.argv[1]); json.dump(u,open('ops/state.json','w'))" "$1"; }
reset() { rm -f ops/usage.json ops/state.json ops/run.json ops/inbox_pending ops/ticks.jsonl "$FAKE_COUNT"; rm -rf ops/runs; mkdir -p ops/runs log
  G set-day1 2026-11-01 >/dev/null; G set-budget 140 >/dev/null; printf -- "- [ ] build the thing\n" > ops/board.md; }
N=2026-11-03T10:00:00-05:00

echo "== pace flags"
reset; setu 'u["days"]={"2026-11-01":5,"2026-11-02":5}'
ok "behind: upgrade" "[ \"\$(dec $N 'd[\"upgrade\"], d[\"pace_ratio\"]')\" = '(True, 0.25)' ]"
reset; setu 'u["days"]={"2026-11-01":20,"2026-11-02":20}; u["models"]={"2026-11-01":{"fable":10},"2026-11-02":{"fable":10}}'
ok "on pace: no flags" "[ \"\$(dec $N 'd[\"upgrade\"]')\" = 'False' ]"
reset; setu 'u["days"]={"2026-11-01":20,"2026-11-02":20}; u["models"]={"2026-11-01":{"fable":1}}'
ok "Fable behind alone: nothing pushed (Fable is a ceiling)" "[ \"\$(dec $N 'd[\"upgrade\"], \"fable_push\" in d, d[\"fable_ok\"]')\" = '(False, False, True)' ]"
reset
ok "first day of the week: no flags yet" "[ \"\$(dec 2026-11-01T15:00:00-05:00 'd[\"upgrade\"], d[\"pace_ratio\"]')\" = '(False, None)' ]"

echo "== backlog instead of idle"
reset; : > ops/board.md; setu 'u["days"]={"2026-11-01":5,"2026-11-02":5}'; sets 'u["last_work_at"]="2026-11-03T09:50:00-05:00"'
ok "empty board, behind: backlog session" "[ \"\$(dec $N 'd[\"run\"], d[\"backlog\"]')\" = \"('work', True)\" ]"
sets 'u["last_work_at"]="2026-11-03T10:15:00-05:00"'
ok "still empty right after a refill: waiting on the Investors, the queue runs" "[ \"\$(dec 2026-11-03T10:20:00-05:00 'd[\"run\"], d[\"code\"]')\" = \"('queue', 'blocked')\" ]"
ok "after 30 minutes: refill again" "[ \"\$(dec 2026-11-03T10:35:00-05:00 'd[\"run\"], d[\"backlog\"]')\" = \"('work', True)\" ]"
reset; : > ops/board.md; setu 'u["days"]={"2026-11-01":20,"2026-11-02":20}'; sets 'u["last_work_at"]="2026-11-03T09:50:00-05:00"'
ok "empty board, on pace: refilled too, never idle" "[ \"\$(dec $N 'd[\"run\"], d[\"backlog\"]')\" = \"('work', True)\" ]"
printf -- '- [b] price test (waiting on #4)\n' > ops/board.md
ok "a board with only tasks waiting on the Investors counts as empty" "[ \"\$(dec 2026-11-03T11:30:00-05:00 'd[\"backlog\"]')\" = True ]"

echo "== the daily share and the reserve"
reset; setu 'u["days"]={"2026-11-03":26}'
ok "before the evening report: share 28, 90% = 25.2, so queue" "[ \"\$(dec 2026-11-03T17:00:00-05:00 'd[\"run\"]')\" = queue ]"
sets 'u["last_evening_date"]="2026-11-03"; u["last_evening_at"]="2026-11-03T18:05:00-05:00"'
ok "after it: work on the rest of the share" "[ \"\$(dec 2026-11-03T19:00:00-05:00 'd[\"run\"], d[\"pacing\"][\"reserve_fraction\"]')\" = \"('work', 0.0)\" ]"
ok "session cap: at least a quarter of the share (7.0)" "[ \"\$(dec 2026-11-03T19:00:00-05:00 'd[\"max_budget_usd\"]')\" = 7.0 ]"
reset; G set-anchor 2026-11-01T00:00:00-05:00 >/dev/null; setu 'u["days"]={"2026-11-01":20,"2026-11-02":20,"2026-11-03":20,"2026-11-04":20,"2026-11-05":20,"2026-11-06":10,"2026-11-07":15}'
ok "last day: the share is everything left (30), not half of it" "[ \"\$(dec 2026-11-07T15:00:00-05:00 'd[\"pacing\"][\"today_share_usd\"], d[\"run\"]')\" = \"(30.0, 'work')\" ]"

echo "== limit hits calibrate"
reset; G set-anchor 2026-11-01T00:00:00-05:00 >/dev/null; setu 'u["days"]={"2026-11-01":40,"2026-11-02":40,"2026-10-30":99}'
GOVERNOR_NOW=$N FAKE_MODE=limit tools/supervisor.sh >/dev/null 2>&1
ok "weekly hit: budget = this plan week's spend (80.01)" "[ \"\$(python3 -c 'import json; u=json.load(open(\"ops/usage.json\")); print(u[\"weekly_budget_usd\"], u[\"limit_hits\"][-1][\"kind\"])')\" = '80.01 weekly' ]"
reset; setu 'u["models"]={"2026-11-02":{"fable":30.0}}'
GOVERNOR_NOW=$N FAKE_MODE=fable_limit tools/supervisor.sh >/dev/null 2>&1
ok "Fable hit: Fable budget = Fable spend (30.0), weekly unchanged" "[ \"\$(python3 -c 'import json; u=json.load(open(\"ops/usage.json\")); print(u[\"fable_budget_usd\"], u[\"weekly_budget_usd\"], u[\"rate_limit_until\"])')\" = '30.0 140.0 None' ]"

echo "== weeks close and probe upward"
reset; setu 'u["days"]={"2026-11-0%d"%i:20 for i in range(1,8)}; u["models"]={"2026-11-0%d"%i:{"fable":10} for i in range(1,8)}'
G decide --now 2026-11-08T10:00:00-05:00 >/dev/null
ok "full week spent, no hit: both budgets +10%" "[ \"\$(python3 -c 'import json; u=json.load(open(\"ops/usage.json\")); w=u[\"weeks\"][-1]; print(u[\"weekly_budget_usd\"], u[\"fable_budget_usd\"], len(u[\"weeks\"]), w[\"spent_usd\"])')\" = '154.0 77.0 1 140.0' ]"
G decide --now 2026-11-08T11:00:00-05:00 >/dev/null
ok "closed only once" "[ \"\$(python3 -c 'import json; u=json.load(open(\"ops/usage.json\")); print(len(u[\"weeks\"]), u[\"weekly_budget_usd\"])')\" = '1 154.0' ]"
reset; setu 'u["days"]={"2026-11-0%d"%i:20 for i in range(1,8)}; u["limit_hits"]=[{"at":"2026-11-07T20:00:00-05:00","kind":"weekly","spend_7d_usd":140}]'
G decide --now 2026-11-08T10:00:00-05:00 >/dev/null
ok "week that hit its limit: no raise" "[ \"\$(python3 -c 'import json; u=json.load(open(\"ops/usage.json\")); print(u[\"weekly_budget_usd\"], u[\"weeks\"][-1][\"weekly_limit_hit\"])')\" = '140.0 True' ]"
reset; setu 'u["days"]={"2026-11-0%d"%i:10 for i in range(1,8)}'
G decide --now 2026-11-08T10:00:00-05:00 >/dev/null
ok "half-spent week: no raise" "[ \"\$(python3 -c 'import json; u=json.load(open(\"ops/usage.json\")); print(u[\"weekly_budget_usd\"])')\" = '140.0' ]"
reset; G decide --now 2026-11-01T10:00:00-05:00 >/dev/null
ok "Day 1: nothing to close" "[ \"\$(python3 -c 'import json; u=json.load(open(\"ops/usage.json\")); print(len(u.get(\"weeks\",[])))')\" = 0 ]"

echo "== status and anchor"
ok "status shows pace and weeks" "G status --now $N | grep -q 'Pace (finished days'"
reset; G set-anchor 2026-11-02T09:00:00-05:00 >/dev/null
ok "anchored week starts at the reset" "[ \"\$(dec 2026-11-04T10:00:00-05:00 'd[\"pacing\"][\"week_start\"]')\" = 2026-11-02T09:00:00-05:00 ]"

echo; echo "PASS $PASS  FAIL $FAIL"
[ "$FAIL" -eq 0 ]
