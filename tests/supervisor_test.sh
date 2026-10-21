#!/bin/bash
# The run loop end to end: stream-json accounting, limits, log-outs, retries,
# Fable allowance, caps, the model guard, and the report sessions.
# Run through tests/run.sh, which builds the throwaway copy this works in.
T="${T:?run tests/run.sh instead}"; R="$T/repo"; cd "$R" || exit 1
export CLAUDE_BIN="$T/bin/claude" FAKE_ARGS="$T/args.txt" FAKE_COUNT="$T/count.txt" HOME="$T/home"
export PATH="$T/home/.local/bin:$PATH"
PASS=0; FAIL=0
ok() { if eval "$2"; then PASS=$((PASS+1)); echo "PASS $1"; else FAIL=$((FAIL+1)); echo "FAIL $1"; fi; }
j() { python3 -c "import json,sys; d=json.load(open('$1')); r=eval(sys.argv[1]); print(' '.join(map(str,r)) if isinstance(r,tuple) else r)" "$2"; }
reset() { rm -f ops/usage.json ops/state.json ops/run.json ops/inbox_pending ops/board.md "$FAKE_COUNT" ops/.auth_alerted; rm -rf ops/runs; mkdir -p ops/runs log
  python3 tools/governor.py set-day1 2026-11-01 >/dev/null; python3 tools/governor.py set-budget 150 >/dev/null; printf -- "- [ ] build the thing\n" > ops/board.md; }
tick() { GOVERNOR_NOW="$1" FAKE_MODE="${2:-normal}" tools/supervisor.sh >/dev/null 2>&1; echo $?; }
last() { python3 -c "import json; print(json.load(open('ops/usage.json'))['runs'][-1]$1)"; }

mkdir -p personnel/agents/former
printf -- "---\ndescription: Maya, iOS engineer.\nmodel: fable\n---\n# Maya\nPersona.\n" > personnel/agents/maya.md
printf -- "---\ndescription: CEO.\n---\n# Ceo\nPersona.\n" > personnel/agents/ceo.md
printf -- "---\ndescription: Olga, designer.\n---\n# Olga\nLeft on Day 9.\n" > personnel/agents/former/olga.md
mkdir -p personnel/candidates
printf -- "---\ndescription: Noor, candidate for iOS engineer.\nround: 2026-11-02-ios-engineer\nstatus: candidate\n---\n# Noor\nDossier.\n" > personnel/candidates/noor.md

echo "== work tick: stream-json accounting"
reset
tick 2026-11-03T10:00:00-05:00 >/dev/null
ok "work session ran with sonnet/medium" "grep -qx sonnet $FAKE_ARGS && grep -qx medium $FAKE_ARGS"
ok "stream-json + verbose + max budget passed" "grep -qx stream-json $FAKE_ARGS && grep -qx -- --verbose $FAKE_ARGS && grep -qx -- --max-budget-usd $FAKE_ARGS"
ok "run.json carries fable_ok and over_cap" "[ \"\$(j ops/run.json 'd[\"fable_ok\"], d[\"over_cap\"], d[\"max_budget_usd\"] > 0')\" = 'True [] True' ]"
ok "cost recorded 0.65" "[ \"\$(last \"['cost_usd']\")\" = 0.65 ]"
ok "categories split project/meetings/hiring/talk" "python3 -c \"import json; c=json.load(open('ops/usage.json'))['runs'][-1]['cats']; assert set(c)=={'project','meetings','hiring','talk'}, c; assert abs(sum(c.values())-0.65)<1e-3\""
ok "fable call counted as project, not meetings" "python3 -c \"import json; c=json.load(open('ops/usage.json'))['runs'][-1]['cats']; assert c['project']>c['meetings']>c['talk']\""
ok "[hiring] interview counted as hiring, not meetings" "python3 -c \"import json; c=json.load(open('ops/usage.json'))['runs'][-1]['cats']; assert c['hiring']>0 and c['hiring']!=c['meetings'], c\""
ok "models from modelUsage scaled to cost" "python3 -c \"import json; m=json.load(open('ops/usage.json'))['runs'][-1]['models']; assert set(m)=={'sonnet','fable','haiku'}; assert abs(sum(m.values())-0.65)<1e-3\""
ok "result .json written beside the stream" "ls ops/runs/*-work.json >/dev/null && ls ops/runs/*-work.jsonl >/dev/null && [ \"\$(j \$(ls ops/runs/*-work.json) 'd[\"total_cost_usd\"]')\" = 0.65 ]"
ok "workers default to sonnet, persona model ignored" "[ \"\$(j ops/agents.json 'd[\"maya\"][\"model\"], d[\"maya\"][\"effort\"], \"olga\" in d')\" = 'sonnet medium False' ]"
ok "candidates are not workers: personnel/candidates/ is not assembled" "[ \"\$(j ops/agents.json '\"noor\" in d')\" = False ]"
ok "jsonl is git-ignored" "git check-ignore -q \$(ls ops/runs/*.jsonl | head -1)"

echo "== success text that mentions a limit is not a limit hit"
reset; tick 2026-11-03T10:00:00-05:00 normal_mentions_limit >/dev/null
ok "no pause" "[ \"\$(j ops/usage.json 'd[\"rate_limit_until\"]')\" = None ] && [ \"\$(last \"['limited']\")\" = False ]"

echo "== no total_cost_usd: falls back to modelUsage costUSD"
reset; tick 2026-11-03T10:00:00-05:00 no_total >/dev/null
ok "cost = 0.602" "[ \"\$(last \"['cost_usd']\")\" = 0.602 ]"

echo "== weekly limit hit"
reset; tick 2026-11-03T10:00:00-05:00 limit >/dev/null
ok "paused 24h, no retry" "[ \"\$(last \"['limited']\")\" = True ] && [ \"\$(cat $FAKE_COUNT)\" = 1 ] && j ops/usage.json 'd[\"rate_limit_until\"]' | grep -q 2026-11-04T10"
ok "next tick queues" "python3 tools/governor.py decide --now 2026-11-03T12:00:00-05:00 | grep -q '\"run\": \"queue\"'"

echo "== Fable limit hit pauses Fable only"
reset; tick 2026-11-03T10:00:00-05:00 fable_limit >/dev/null
ok "fable blocked, sessions not paused" "[ \"\$(j ops/usage.json 'd[\"rate_limit_until\"], d[\"fable_blocked_until\"] is not None')\" = 'None True' ]"
ok "next decision: work with fable_ok false" "python3 tools/governor.py decide --now 2026-11-03T10:15:00-05:00 | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d[\"run\"]==\"work\" and d[\"fable_ok\"] is False'"

echo "== logged out"
reset; tick 2026-11-03T10:00:00-05:00 auth >/dev/null
ok "auth_failed, no retry" "[ \"\$(last \"['auth_failed']\")\" = True ] && [ \"\$(cat $FAKE_COUNT)\" = 1 ]"
ok "emergency issue sent through gh (stub)" "grep -q 'issue create --label emergency --title Claude Code is logged out' $T/home/gh_calls.txt && grep -q 'sent the logged-out alert' ops/runs/supervisor.log"
ok "the alert @mentions the allowlisted usernames only" "grep -q '@alice-dev @bob42' $T/home/gh_calls.txt && ! grep -q '@Only' $T/home/gh_calls.txt"
ok "within the hour: queue" "python3 tools/governor.py decide --now 2026-11-03T10:30:00-05:00 | grep -q 'logged out'"
ok "after an hour: tries again" "python3 tools/governor.py decide --now 2026-11-03T11:05:00-05:00 | grep -q '\"run\": \"work\"'"
tick 2026-11-03T11:06:00-05:00 auth >/dev/null
ok "no second alert within 12 hours" "[ \$(grep -c 'issue create' $T/home/gh_calls.txt) = 1 ]"
tick 2026-11-03T12:10:00-05:00 normal >/dev/null
ok "a good run clears the flag" "[ \"\$(j ops/usage.json 'd[\"auth_failed_at\"]')\" = None ]"

echo "== crash retries once; budget cap does not"
reset; tick 2026-11-03T10:00:00-05:00 crash >/dev/null
ok "crash: two attempts" "[ \"\$(cat $FAKE_COUNT)\" = 2 ]"
reset; tick 2026-11-03T10:00:00-05:00 budget >/dev/null
ok "budget cap: one attempt, still counts as a work run" "[ \"\$(cat $FAKE_COUNT)\" = 1 ] && [ \"\$(j ops/state.json 'd[\"last_work_at\"] is not None')\" = True ]"

echo "== Fable allowance"
reset
python3 -c 'import json; u=json.load(open("ops/usage.json")); u["models"]={"2026-11-02":{"fable":75.1}}; u["days"]={"2026-11-02":80}; json.dump(u,open("ops/usage.json","w"))'
ok "half of \$150 spent on Fable: fable_ok false" "python3 tools/governor.py decide --now 2026-11-03T10:00:00-05:00 | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d[\"fable_ok\"] is False and d[\"fable_allowance_usd\"]==75.0, d'"
python3 -c 'import json; u=json.load(open("ops/usage.json")); u["models"]={"2026-10-26":{"fable":75.1}}; json.dump(u,open("ops/usage.json","w"))'
ok "last week's Fable doesn't count" "python3 tools/governor.py decide --now 2026-11-03T10:00:00-05:00 | grep -q '\"fable_ok\": true'"

echo "== caps"
reset
python3 -c 'import json; u=json.load(open("ops/usage.json")); u["cats"]={"2026-11-02":{"project":18.0,"reports":0.6,"meetings":0.5,"talk":0.9}}; u["days"]={"2026-11-02":20.0}; json.dump(u,open("ops/usage.json","w"))'
ok "talk at 4.5% is over its 1% cap; others fine" "python3 tools/governor.py decide --now 2026-11-03T10:00:00-05:00 | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d[\"over_cap\"]==[\"talk\"], d[\"over_cap\"]'"
python3 -c 'import json; u=json.load(open("ops/usage.json")); u["cats"]={"2026-11-02":{"project":18.0,"reports":0.6,"meetings":0.5,"hiring":0.9,"talk":0.0}}; u["days"]={"2026-11-02":20.0}; u["caps"]={"reports":0.05,"meetings":0.04,"talk":0.01}; json.dump(u,open("ops/usage.json","w"))'
ok "hiring at 4.5% is over its 3% cap, even when a saved caps block predates the category" "python3 tools/governor.py decide --now 2026-11-03T10:00:00-05:00 | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d[\"over_cap\"]==[\"hiring\"], d[\"over_cap\"]'"
ok "status shows the hiring cap" "python3 tools/governor.py status --now 2026-11-03T10:00:00-05:00 | grep -q 'hiring 4.5% (cap 3%)'"
python3 -c 'import json; u=json.load(open("ops/usage.json")); u["cats"]={"2026-11-03":{"talk":0.5}}; u["days"]={}; json.dump(u,open("ops/usage.json","w"))'
ok "too little data: no flags" "python3 tools/governor.py decide --now 2026-11-03T10:00:00-05:00 | grep -q '\"over_cap\": \[\]'"

echo "== model guard hook"
H=rules/hooks/model-guard.py
hk() { printf '%s' "$2" > ops/run.json; printf '%s' "$1" | CLAUDE_PROJECT_DIR="$R" $H >/dev/null 2>&1; echo $?; }
ok "fable allowed when fable_ok" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"fable\",\"description\":\"Pitch\"}}' '{\"fable_ok\":true,\"over_cap\":[]}') = 0 ]"
ok "fable refused when not" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"fable\",\"description\":\"Pitch\"}}' '{\"fable_ok\":false,\"over_cap\":[]}') = 2 ]"
ok "best counts as fable" "[ \$(hk '{\"tool_name\":\"Task\",\"tool_input\":{\"model\":\"best\"}}' '{\"fable_ok\":false}') = 2 ]"
ok "opus allowed when fable is not" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"opus\"}}' '{\"fable_ok\":false}') = 0 ]"
ok "diary on sonnet refused" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"sonnet\",\"description\":\"[diary] Maya\"}}' '{\"fable_ok\":true,\"over_cap\":[]}') = 2 ]"
ok "diary without a model refused" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"description\":\"[talk] Maya and Ceo\"}}' '{\"fable_ok\":true,\"over_cap\":[]}') = 2 ]"
ok "diary on haiku allowed" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"haiku\",\"description\":\"[Diary] Maya\"}}' '{\"fable_ok\":true,\"over_cap\":[]}') = 0 ]"
ok "diary refused when talk is over cap" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"haiku\",\"description\":\"[diary] Maya\"}}' '{\"fable_ok\":true,\"over_cap\":[\"talk\"]}') = 2 ]"
ok "[hiring] interview on sonnet allowed" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"sonnet\",\"description\":\"[hiring] interview Noor\"}}' '{\"fable_ok\":true,\"over_cap\":[]}') = 0 ]"
ok "other tools untouched" "[ \$(hk '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"ls\"}}' '{\"fable_ok\":false}') = 0 ]"
rm -f ops/run.json
ok "no run.json (interactive Day 1): allowed" "[ \$(printf '%s' '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"fable\"}}' | CLAUDE_PROJECT_DIR=$R $H >/dev/null 2>&1; echo \$?) = 0 ]"
ok "garbage input: allowed" "[ \$(printf 'xx' | $H >/dev/null 2>&1; echo \$?) = 0 ]"

echo "== report sessions"
reset
tick 2026-11-01T18:05:00-05:00 >/dev/null
ok "Day 1 evening: sonnet low, 20 turns, facts file built first" "[ -f ops/report_facts.md ] && grep -qx sonnet $FAKE_ARGS && grep -qx low $FAKE_ARGS && grep -qx 20 $FAKE_ARGS && [ \"\$(j ops/run.json 'd[\"run\"]')\" = evening ]"
ok "evening cost counted as reports, not project" "python3 -c \"import json; c=json.load(open('ops/usage.json'))['runs'][-1]['cats']; assert 'reports' in c and 'project' not in c, c\""
reset; python3 tools/governor.py set-day1 2026-10-26 >/dev/null
tick 2026-11-01T18:05:00-05:00 >/dev/null
ok "Day 7 evening is weekly: sonnet medium 30" "[ \"\$(j ops/run.json 'd[\"run\"], d[\"weekly\"]')\" = 'weekly True' ] && grep -qx medium $FAKE_ARGS && grep -qx 30 $FAKE_ARGS"
ok "weekly sets last_evening" "[ \"\$(j ops/state.json 'd[\"last_evening_date\"]')\" = 2026-11-01 ]"
reset; python3 tools/governor.py set-day1 2026-10-03 >/dev/null
tick 2026-11-01T18:05:00-05:00 >/dev/null
ok "Day 30 is final: opus high 70" "[ \"\$(j ops/run.json 'd[\"run\"]')\" = final ] && grep -qx opus $FAKE_ARGS && grep -qx high $FAKE_ARGS && grep -qx 70 $FAKE_ARGS"
ok "Day 30 includes former workers" "[ \"\$(j ops/agents.json '\"olga\" in d, d[\"olga\"][\"description\"].startswith(\"Former\")')\" = 'True True' ]"
tick 2026-11-02T10:00:00-05:00 >/dev/null
ok "next work run drops former workers again" "[ \"\$(j ops/agents.json '\"olga\" in d')\" = False ]"
reset
python3 -c 'import json; s=json.load(open("ops/state.json")); s["last_evening_at"]="2026-11-02T18:05:00-05:00"; s["last_evening_date"]="2026-11-02"; json.dump(s,open("ops/state.json","w"))'
echo '{"time":"2026-11-02T23:00:00-05:00","worker":"maya","type":"commit","summary":"x"}' > log/events.jsonl
tick 2026-11-03T06:05:00-05:00 >/dev/null
ok "active night: morning on haiku low 12" "[ \"\$(j ops/run.json 'd[\"run\"]')\" = morning ] && grep -qx haiku $FAKE_ARGS && grep -qx 12 $FAKE_ARGS"
rm -f log/events.jsonl

echo "== status and stdin"
ok "status text" "python3 tools/governor.py status --now 2026-11-03T10:00:00-05:00 | grep -q 'Last 7 days by category'"
ok "status --json" "python3 tools/governor.py status --json --now 2026-11-03T10:00:00-05:00 | python3 -c 'import json,sys; d=json.load(sys.stdin); assert \"all_time_by_model_usd\" in d and \"shares_7d\" in d'"
ok "claude gets /dev/null as stdin" "grep -q '< /dev/null' tools/supervisor.sh"

echo; echo "PASS $PASS  FAIL $FAIL"
[ "$FAIL" -eq 0 ]
