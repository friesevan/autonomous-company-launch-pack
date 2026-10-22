#!/bin/bash
# The run loop end to end: stream-json accounting, limits, log-outs, retries, the Fable allowance,
# caps, the model guard, the report sessions, and the guards around a session: the dry run, the
# hold and the pause, the heartbeat, the meter, the smoke test, API-credit overflow, the hooks
# canary, the file guard, the time limit, failure alerts, and receipts.
# Run through tests/run.sh, which builds the throwaway copy this works in.
T="${T:?run tests/run.sh instead}"; R="$T/repo"; cd "$R" || exit 1
export CLAUDE_BIN="$T/bin/claude" FAKE_ARGS="$T/args.txt" FAKE_COUNT="$T/count.txt" HOME="$T/home"
export PATH="$T/home/.local/bin:$PATH" SECURITY_BIN=false COMPANY_REPO=test/company
PASS=0; FAIL=0
ok() { if eval "$2"; then PASS=$((PASS+1)); echo "PASS $1"; else FAIL=$((FAIL+1)); echo "FAIL $1"; fi; }
j() { python3 -c "import json,sys; d=json.load(open('$1')); r=eval(sys.argv[1]); print(' '.join(map(str,r)) if isinstance(r,tuple) else r)" "$2"; }
reset() { rm -f ops/usage.json ops/state.json ops/run.json ops/inbox_pending ops/board.md "$FAKE_COUNT" ops/.alerted_* \
    ops/.fail_count ops/.fail_reasons ops/ticks.jsonl ops/paused ops/hold ops/last_decision.json
  rm -rf ops/runs ops/inbox ops/.guard ops/quarantine ops/.lock; mkdir -p ops/runs log
  python3 tools/governor.py set-day1 2026-11-01 >/dev/null; python3 tools/governor.py set-budget 150 >/dev/null; printf -- "- [ ] build the thing\n" > ops/board.md; }
tick() { GOVERNOR_NOW="$1" FAKE_MODE="${2:-normal}" tools/supervisor.sh >/dev/null 2>&1; echo $?; }
last() { python3 -c "import json; print(json.load(open('ops/usage.json'))['runs'][-1]$1)"; }
calls() { cat "$T/home/gh_calls.txt" 2>/dev/null; }

mkdir -p personnel/agents/former
printf -- "---\ndescription: Maya, iOS engineer.\nmodel: fable\ntools: Read, Grep, Bash\n---\n# Maya\nPersona.\n" > personnel/agents/maya.md
printf -- "---\ndescription: CEO.\n---\n# Ceo\nPersona.\n" > personnel/agents/ceo.md
printf -- "---\ndescription: Olga, designer.\n---\n# Olga\nLeft on Day 9.\n" > personnel/agents/former/olga.md
mkdir -p personnel/candidates
printf -- "---\ndescription: Noor, candidate for iOS engineer.\nround: 2026-11-02-ios-engineer\nstatus: candidate\n---\n# Noor\nDossier.\n" > personnel/candidates/noor.md
git add -A >/dev/null 2>&1 && git -c user.name=test -c user.email=t@example.com commit -qm fixtures >/dev/null 2>&1

echo "== the first tick: heartbeat and smoke test"
reset; : > "$T/home/gh_calls.txt"; rm -f ops/claude_version
tick 2026-11-03T10:00:00-05:00 >/dev/null
ok "heartbeat sent to the company repository" "calls | grep -q 'variable set HEARTBEAT_AT --repo test/company'"
ok "a new Claude Code version is smoke-tested once, before its first session" "grep -q 'the smoke test passed' ops/runs/supervisor.log && [ \"\$(cat ops/claude_version)\" = '2.1.300 (Claude Code)' ] && [ \"\$(cat $FAKE_COUNT)\" = 1 ]"
ok "no usage report from /usage: the meter backs off" "[ \"\$(j ops/usage.json 'd[\"meter_failed_at\"] is not None')\" = True ]"
ok "the tick is logged" "grep -q '\"code\": \"work\"' ops/ticks.jsonl"

echo "== work tick: stream-json accounting"
reset
tick 2026-11-03T10:00:00-05:00 >/dev/null
ok "work session ran with sonnet/medium" "grep -qx sonnet $FAKE_ARGS && grep -qx medium $FAKE_ARGS"
ok "stream-json, verbose, forwarded worker text, max budget passed" "grep -qx stream-json $FAKE_ARGS && grep -qx -- --verbose $FAKE_ARGS && grep -qx -- --forward-subagent-text $FAKE_ARGS && grep -qx -- --max-budget-usd $FAKE_ARGS"
ok "run.json carries fable_ok, over_cap, and the plan billing" "[ \"\$(j ops/run.json 'd[\"fable_ok\"], d[\"over_cap\"], d[\"max_budget_usd\"] > 0, d[\"billing\"]')\" = 'True [] True plan' ]"
ok "cost recorded 0.65" "[ \"\$(last \"['cost_usd']\")\" = 0.65 ]"
ok "categories split project/meetings/hiring/talk" "python3 -c \"import json; c=json.load(open('ops/usage.json'))['runs'][-1]['cats']; assert set(c)=={'project','meetings','hiring','talk'}, c; assert abs(sum(c.values())-0.65)<1e-3\""
ok "fable call counted as project, not meetings" "python3 -c \"import json; c=json.load(open('ops/usage.json'))['runs'][-1]['cats']; assert c['project']>c['meetings']>c['talk']\""
ok "[hiring] interview counted as hiring, not meetings" "python3 -c \"import json; c=json.load(open('ops/usage.json'))['runs'][-1]['cats']; assert c['hiring']>0 and c['hiring']!=c['meetings'], c\""
ok "product work split by kind: design, build, and the Operator's own turns" "python3 -c \"import json; r=json.load(open('ops/usage.json'))['runs'][-1]; k=r['kinds']; assert set(k)=={'design','build','operations'}, k; assert abs(sum(k.values())-r['cats']['project'])<1e-3\""
ok "kinds stored by day" "python3 -c \"import json; k=json.load(open('ops/usage.json'))['kinds']['2026-11-03']; assert k['build']>0\""
ok "models from modelUsage scaled to cost" "python3 -c \"import json; m=json.load(open('ops/usage.json'))['runs'][-1]['models']; assert set(m)=={'sonnet','fable','haiku'}; assert abs(sum(m.values())-0.65)<1e-3\""
ok "the key source and permission mode are recorded" "[ \"\$(python3 -c \"import json; r=json.load(open('ops/usage.json'))['runs'][-1]; print(r['api_key_source'], r['permission_mode'])\")\" = 'none auto' ]"
ok "result .json written beside the stream" "ls ops/runs/*-work.json >/dev/null && ls ops/runs/*-work.jsonl >/dev/null && [ \"\$(j \$(ls ops/runs/*-work.json) 'd[\"total_cost_usd\"]')\" = 0.65 ]"
ok "workers default to sonnet, persona model ignored" "[ \"\$(j ops/agents.json 'd[\"maya\"][\"model\"], d[\"maya\"][\"effort\"], \"olga\" in d')\" = 'sonnet medium False' ]"
ok "a persona's tools become a JSON array" "[ \"\$(j ops/agents.json 'd[\"maya\"][\"tools\"]')\" = \"['Read', 'Grep', 'Bash']\" ]"
ok "candidates are not workers: personnel/candidates/ is not assembled" "[ \"\$(j ops/agents.json '\"noor\" in d')\" = False ]"
ok "jsonl is git-ignored" "git check-ignore -q \$(ls ops/runs/*.jsonl | head -1)"
reset; tick 2026-11-03T10:00:00-05:00 untagged >/dev/null
ok "untagged worker calls count as other" "python3 -c \"import json; k=json.load(open('ops/usage.json'))['runs'][-1]['kinds']; assert 'other' in k and 'build' not in k, k\""

echo "== success text that mentions a limit is not a limit hit"
reset; tick 2026-11-03T10:00:00-05:00 normal_mentions_limit >/dev/null
ok "no pause" "[ \"\$(j ops/usage.json 'd[\"rate_limit_until\"]')\" = None ] && [ \"\$(last \"['limited']\")\" = False ]"

echo "== no total_cost_usd: falls back to modelUsage costUSD"
reset; tick 2026-11-03T10:00:00-05:00 no_total >/dev/null
ok "cost = 0.602" "[ \"\$(last \"['cost_usd']\")\" = 0.602 ]"

echo "== weekly limit hit"
reset; tick 2026-11-03T10:00:00-05:00 limit >/dev/null
ok "unanchored: paused 24h, no retry" "[ \"\$(last \"['limited']\")\" = True ] && [ \"\$(cat $FAKE_COUNT)\" = 1 ] && j ops/usage.json 'd[\"rate_limit_until\"]' | grep -q 2026-11-04T10"
ok "next tick queues" "python3 tools/governor.py decide --now 2026-11-03T12:00:00-05:00 | grep -q '\"run\": \"queue\"'"
reset; python3 tools/governor.py set-anchor 2026-11-02T09:00:00-05:00 >/dev/null; tick 2026-11-03T10:00:00-05:00 limit >/dev/null
ok "anchored: paused until the plan's weekly reset, not 24 hours" "[ \"\$(j ops/usage.json 'd[\"rate_limit_until\"], d[\"rate_limit_kind\"]')\" = '2026-11-09T09:00:00-05:00 weekly' ]"
reset; FAKE_RESETS=1798300800 tick 2026-11-03T10:00:00-05:00 limit_event >/dev/null
ok "a rejected rate_limit_event: paused until the reset it names" "[ \"\$(j ops/usage.json 'd[\"rate_limit_until\"]')\" = 2026-12-26T11:00:00-05:00 ] && [ \"\$(cat $FAKE_COUNT)\" = 1 ]"

echo "== Fable limit hit pauses Fable only"
reset; tick 2026-11-03T10:00:00-05:00 fable_limit >/dev/null
ok "fable blocked, sessions not paused" "[ \"\$(j ops/usage.json 'd[\"rate_limit_until\"], d[\"fable_blocked_until\"] is not None')\" = 'None True' ]"
ok "next decision: work with fable_ok false" "python3 tools/governor.py decide --now 2026-11-03T10:15:00-05:00 | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d[\"run\"]==\"work\" and d[\"fable_ok\"] is False'"

echo "== logged out"
reset; : > "$T/home/gh_calls.txt"; tick 2026-11-03T10:00:00-05:00 auth >/dev/null
ok "auth_failed, no retry" "[ \"\$(last \"['auth_failed']\")\" = True ] && [ \"\$(cat $FAKE_COUNT)\" = 1 ]"
ok "emergency issue sent through gh (stub)" "calls | grep -q 'issue create --label emergency --title Claude Code is logged out' && grep -q 'sent the logged-out alert' ops/runs/supervisor.log"
ok "the alert @mentions the allowlisted usernames only" "calls | grep -q '@alice-dev @bob42' && ! calls | grep -q '@Only'"
ok "within the hour: queue" "python3 tools/governor.py decide --now 2026-11-03T10:30:00-05:00 | grep -q 'logged out'"
ok "after an hour: tries again" "python3 tools/governor.py decide --now 2026-11-03T11:05:00-05:00 | grep -q '\"run\": \"work\"'"
tick 2026-11-03T11:06:00-05:00 auth >/dev/null
ok "no second alert within 12 hours" "[ \$(calls | grep -c 'issue create') = 1 ]"
tick 2026-11-03T12:10:00-05:00 normal >/dev/null
ok "a good run clears the flag" "[ \"\$(j ops/usage.json 'd[\"auth_failed_at\"]')\" = None ]"

echo "== crash retries once; budget cap does not; three failed ticks alert"
reset; tick 2026-11-03T10:00:00-05:00 crash >/dev/null
ok "crash: two attempts" "[ \"\$(cat $FAKE_COUNT)\" = 2 ]"
reset; tick 2026-11-03T10:00:00-05:00 budget >/dev/null
ok "budget cap: one attempt, still counts as a work run" "[ \"\$(cat $FAKE_COUNT)\" = 1 ] && [ \"\$(j ops/state.json 'd[\"last_work_at\"] is not None')\" = True ]"
reset; : > "$T/home/gh_calls.txt"
for t in 10:00 10:15 10:30 10:45; do tick 2026-11-03T$t:00-05:00 crash >/dev/null; done
ok "three failed ticks in a row: one emergency" "[ \$(calls | grep -c 'keep failing') = 1 ]"
tick 2026-11-03T11:00:00-05:00 >/dev/null
ok "a good tick clears the count" "[ ! -f ops/.fail_count ]"

echo "== the time limit"
reset; SESSION_SECONDS=2 FAKE_SLEEP=20 tick 2026-11-03T10:00:00-05:00 slow >/dev/null
ok "a session past its time limit is stopped, not retried" "[ \"\$(last \"['timed_out']\")\" = True ] && [ \"\$(cat $FAKE_COUNT)\" = 1 ] && grep -q 'was stopped' ops/runs/supervisor.log"
reset; rm -f "$T/home/gh_comments.jsonl"
KEEPER_SECONDS=1 FAKE_SLEEP=20 tick 2026-11-03T10:00:00-05:00 pause_mid >/dev/null
ok "a PAUSE during a session stops it within the keeper's check, with no retry" "[ -f ops/paused ] && grep -q 'stopping the session' ops/runs/supervisor.log && ! grep -q 'retrying once' ops/runs/supervisor.log"
rm -f ops/paused "$T/home/gh_comments.jsonl"
reset
tick 2026-11-01T18:05:00-05:00 noreport >/dev/null
ok "a report session that writes no report: not counted done" "[ \"\$(j ops/state.json 'd.get(\"last_evening_date\")')\" = None ]"
tick 2026-11-01T18:20:00-05:00 noreport >/dev/null
ok "the second try counts, so it never loops" "[ \"\$(j ops/state.json 'd.get(\"last_evening_date\")')\" = 2026-11-01 ]"

echo "== dry run, hold, pause, lock"
reset; : > "$T/home/gh_calls.txt"; rm -f ops/ticks.jsonl
OUT="$(GOVERNOR_NOW=2026-11-03T10:00:00-05:00 tools/supervisor.sh --dry-run 2>/dev/null)"
ok "dry run: prints the session and its command, starts nothing" "printf '%s' \"\$OUT\" | grep -q 'would start a work session on the plan' && printf '%s' \"\$OUT\" | grep -q -- '--permission-mode auto' && [ ! -f $FAKE_COUNT ] && [ ! -f ops/run.json ]"
ok "dry run: shows the login, logs no tick, sends no heartbeat" "printf '%s' \"\$OUT\" | grep -q 'claude auth: Logged in' && [ ! -f ops/ticks.jsonl ] && ! calls | grep -q 'variable set'"
touch ops/hold
ok "a dry run looks past the Day 1 hold" "GOVERNOR_NOW=2026-11-03T10:00:00-05:00 tools/supervisor.sh --dry-run 2>/dev/null | grep -q 'would start a work session'"
tick 2026-11-03T10:00:00-05:00 >/dev/null
ok "a real tick with the hold set starts nothing, but still sends the heartbeat" "[ ! -f $FAKE_COUNT ] && grep -q 'hold: ops/hold is set' ops/runs/supervisor.log && calls | grep -q 'variable set'"
rm -f ops/hold; printf '{"by": "@alice-dev"}\n' > ops/paused
tick 2026-11-03T10:15:00-05:00 >/dev/null
ok "paused by an Investor: no session and no queued jobs" "[ ! -f $FAKE_COUNT ] && grep -q 'hold: paused by @alice-dev' ops/runs/supervisor.log"
rm -f ops/paused; mkdir -p ops/.lock; echo 999999 > ops/.lock/pid
tick 2026-11-03T10:30:00-05:00 >/dev/null
ok "a lock whose process is gone is taken over at once" "grep -q 'removed a stale lock' ops/runs/supervisor.log && [ \"\$(cat $FAKE_COUNT)\" = 1 ]"
mkdir -p ops/.lock; echo $$ > ops/.lock/pid
tick 2026-11-03T10:45:00-05:00 >/dev/null
ok "a live lock stops the tick" "grep -q 'another run is in progress' ops/runs/supervisor.log && [ \"\$(cat $FAKE_COUNT)\" = 1 ]"
rm -rf ops/.lock

echo "== the meter"
reset
export FAKE_METER='{"session": 20, "week": 40, "week_reset": "2026-11-08T14:00:00Z", "fable": 10, "fable_reset": "2026-11-08T14:00:00Z"}'
tick 2026-11-03T10:00:00-05:00 >/dev/null
ok "exact percentages, and the week anchored to the plan's reset" "[ \"\$(j ops/usage.json 'd[\"meter\"][\"limits\"][1][\"percent\"], d[\"week_anchor\"]')\" = '40.0 2026-11-01T09:00:00-05:00' ]"
ok "status: the plan by now, from the meter" "python3 tools/governor.py status --json --now 2026-11-03T10:05:00-05:00 | python3 -c 'import json,sys; p=json.load(sys.stdin)[\"plan\"]; assert p[\"source\"]==\"meter\" and p[\"week\"][\"actual_pct\"]==40.0 and p[\"week\"][\"status\"]==\"ahead\", p'"
reset; export FAKE_METER='{"session": 100, "session_reset": "2026-11-03T17:00:00Z", "week": 55, "week_reset": "2026-11-08T14:00:00Z"}'
tick 2026-11-03T10:00:00-05:00 >/dev/null
ok "at the 5-hour limit: no session, paused until the meter's reset" "[ ! -f $FAKE_COUNT ] && [ \"\$(j ops/usage.json 'd[\"rate_limit_until\"], d[\"rate_limit_kind\"]')\" = '2026-11-03T12:00:00-05:00 session' ]"
export FAKE_METER='{"session": 3, "session_reset": "2026-11-03T22:00:00Z", "week": 56, "week_reset": "2026-11-08T14:00:00Z"}'
tick 2026-11-03T10:20:00-05:00 >/dev/null
ok "the plan reopens early: the pause ends and work resumes" "[ \"\$(j ops/usage.json 'd[\"rate_limit_until\"]')\" = None ] && [ \"\$(cat $FAKE_COUNT)\" = 1 ]"
reset; : > "$T/home/gh_calls.txt"; export FAKE_METER='{"session": 5, "week": 10, "credits_on": true}'
tick 2026-11-03T10:00:00-05:00 >/dev/null
ok "usage credits switched on: an emergency" "calls | grep -q 'Usage credits are switched on'"
unset FAKE_METER

echo "== API-credit overflow"
reset; python3 tools/governor.py mark-limit 5 --now 2026-11-03T10:00:00-05:00 >/dev/null
SECURITY_BIN=true tick 2026-11-03T10:30:00-05:00 >/dev/null
ok "a plan limit with credits ready: a session on API credits, through the key helper, never Fable" "grep -qx -- --settings $FAKE_ARGS && grep -qx rules/api-settings.json $FAKE_ARGS && [ \"\$(j ops/run.json 'd[\"billing\"], d[\"fable_ok\"]')\" = 'api False' ]"
ok "credit spend is kept out of the plan's pacing" "[ \"\$(j ops/usage.json 'd[\"api_days\"][\"2026-11-03\"], \"2026-11-03\" in d[\"days\"]')\" = '0.65 False' ]"
SECURITY_BIN=true tick 2026-11-03T10:45:00-05:00 credits_out >/dev/null
ok "credits used up: overflow off until the next cycle" "[ \"\$(j ops/usage.json 'd[\"api_exhausted_until\"]')\" = 2026-12-01T00:00:00-05:00 ]"
ok "then a limit tick queues" "python3 tools/governor.py decide --api-ready --now 2026-11-03T11:00:00-05:00 | grep -q '\"run\": \"queue\"'"
reset; python3 tools/governor.py mark-limit 5 --now 2026-11-03T10:00:00-05:00 >/dev/null
tick 2026-11-03T10:30:00-05:00 >/dev/null
ok "no key in the Keychain: a limit just queues" "[ ! -f $FAKE_COUNT ]"
reset; : > "$T/home/gh_calls.txt"; tick 2026-11-03T10:00:00-05:00 api_key >/dev/null
ok "a plan session billed to an API key: an emergency, and overflow off" "calls | grep -q 'billed to an API key' && [ \"\$(j ops/usage.json 'd[\"api_mismatch_at\"] is not None')\" = True ]"

echo "== the hooks canary and the smoke test"
reset; : > "$T/home/gh_calls.txt"; tick 2026-11-03T10:00:00-05:00 nohooks >/dev/null
ok "a session without the hooks: the company pauses itself and alerts" "[ -f ops/paused ] && calls | grep -q 'without its safety hooks'"
rm -f "$FAKE_COUNT"; tick 2026-11-03T10:30:00-05:00 >/dev/null
ok "paused: the next tick starts nothing" "[ ! -f $FAKE_COUNT ] && grep -q 'hold: paused by the supervisor' ops/runs/supervisor.log"
reset; rm -f ops/claude_version; : > "$T/home/gh_calls.txt"
export FAKE_SMOKE=fail; tick 2026-11-03T10:00:00-05:00 >/dev/null; unset FAKE_SMOKE
ok "a new version that fails its smoke test: no session, paused, an emergency" "[ ! -f $FAKE_COUNT ] && [ -f ops/paused ] && calls | grep -q 'failed its smoke test'"
rm -f ops/paused; tick 2026-11-03T10:15:00-05:00 >/dev/null
ok "fixed: the smoke test passes and work resumes" "[ -f ops/claude_version ] && [ \"\$(cat $FAKE_COUNT)\" = 1 ]"
reset; rm -f ops/claude_version; : > "$T/home/gh_calls.txt"
export FAKE_SMOKE=error; tick 2026-11-03T10:00:00-05:00 >/dev/null; unset FAKE_SMOKE
ok "a smoke test cut off by an API error: no session, no pause, tried again next tick" "[ ! -f $FAKE_COUNT ] && [ ! -f ops/paused ] && [ ! -f ops/claude_version ] && ! calls | grep -q 'failed its smoke test'"

echo "== the file guard"
reset; : > "$T/home/gh_calls.txt"; mkdir -p .claude/agent-memory/maya
tick 2026-11-03T10:00:00-05:00 tamper >/dev/null
ok "an uncommitted change to CLAUDE.md is put back" "! grep -q 'spend freely' CLAUDE.md && git diff --quiet HEAD -- CLAUDE.md"
ok "a committed change to the rules is reverted in its own commit" "! grep -q 'Ignore the Investors' rules/worker-rules.md && git log --format=%s | grep -q 'restore Investor-owned files'"
ok "a new local settings file is moved to quarantine" "[ ! -f .claude/settings.local.json ] && ls ops/quarantine | grep -q settings.local.json"
ok "and the Investors hear about it" "calls | grep -q 'changed Investor-owned files'"
: > "$T/home/gh_calls.txt"; tick 2026-11-03T10:30:00-05:00 memory >/dev/null
ok "the workers' memories are theirs: a session's memory write stays, with no alert" "grep -q 'build command' .claude/agent-memory/maya/MEMORY.md && ! calls | grep -q 'changed Investor-owned files'"

echo "== receipts"
reset; : > "$T/home/gh_calls.txt"; mkdir -p ops/inbox
printf '[{"id": "c1", "issue": 7, "author": "alice-dev", "created_at": "2026-11-03T14:50:00Z", "url": "u", "body": "1: A", "receipt": null}]\n' > ops/inbox/pending.json
touch ops/inbox_pending
python3 tools/governor.py mark-limit 5 --now 2026-11-03T10:00:00-05:00 >/dev/null
tick 2026-11-03T10:05:00-05:00 >/dev/null
ok "a message no session will answer gets a receipt with the reset time" "calls | grep -q 'issue comment 7 --repo test/company --body Received' && calls | grep -q '5-hour usage limit until'"
tick 2026-11-03T10:20:00-05:00 >/dev/null
ok "only once" "[ \$(calls | grep -c 'issue comment 7') = 1 ]"

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
hk() { printf '%s' "$2" > ops/run.json; printf '%s' "$1" | CLAUDE_PROJECT_DIR="$R" COMPANY_RUN="${3:-}" $H >/dev/null 2>&1; echo $?; }
ok "fable allowed when fable_ok" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"fable\",\"description\":\"Pitch\"}}' '{\"fable_ok\":true,\"over_cap\":[]}') = 0 ]"
ok "fable refused when not" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"fable\",\"description\":\"Pitch\"}}' '{\"fable_ok\":false,\"over_cap\":[]}') = 2 ]"
ok "fable refused on API credits, even with allowance left" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"fable\",\"description\":\"[plan] Pitch\"}}' '{\"fable_ok\":true,\"billing\":\"api\"}') = 2 ]"
ok "best counts as fable" "[ \$(hk '{\"tool_name\":\"Task\",\"tool_input\":{\"model\":\"best\"}}' '{\"fable_ok\":false}') = 2 ]"
ok "opus allowed when fable is not" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"opus\"}}' '{\"fable_ok\":false}') = 0 ]"
ok "diary on sonnet refused" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"sonnet\",\"description\":\"[diary] Maya\"}}' '{\"fable_ok\":true,\"over_cap\":[]}') = 2 ]"
ok "diary without a model refused" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"description\":\"[talk] Maya and Ceo\"}}' '{\"fable_ok\":true,\"over_cap\":[]}') = 2 ]"
ok "diary on haiku allowed" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"haiku\",\"description\":\"[Diary] Maya\"}}' '{\"fable_ok\":true,\"over_cap\":[]}') = 0 ]"
ok "diary refused when talk is over cap" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"haiku\",\"description\":\"[diary] Maya\"}}' '{\"fable_ok\":true,\"over_cap\":[\"talk\"]}') = 2 ]"
ok "[hiring] interview on sonnet allowed" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"sonnet\",\"description\":\"[hiring] interview Noor\"}}' '{\"fable_ok\":true,\"over_cap\":[]}') = 0 ]"
ok "a company work session refuses an untagged worker call" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"sonnet\",\"description\":\"onboarding screen\"}}' '{\"run\":\"work\",\"fable_ok\":true}' 1) = 2 ]"
ok "a kind tag, or a cap tag, is enough" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"sonnet\",\"description\":\"[build] onboarding\"}}' '{\"run\":\"work\"}' 1) = 0 ] && [ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"sonnet\",\"description\":\"[meeting] review\"}}' '{\"run\":\"inbox\"}' 1) = 0 ]"
ok "outside company sessions (Day 1 at the keyboard), untagged calls pass" "[ \$(hk '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"sonnet\",\"description\":\"set up\"}}' '{\"run\":\"work\"}') = 0 ]"
ok "other tools untouched" "[ \$(hk '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"ls\"}}' '{\"fable_ok\":false}') = 0 ]"
rm -f ops/run.json
ok "no run.json (interactive Day 1): allowed" "[ \$(printf '%s' '{\"tool_name\":\"Agent\",\"tool_input\":{\"model\":\"fable\"}}' | CLAUDE_PROJECT_DIR=$R $H >/dev/null 2>&1; echo \$?) = 0 ]"
ok "garbage input: allowed" "[ \$(printf 'xx' | $H >/dev/null 2>&1; echo \$?) = 0 ]"

echo "== report sessions"
reset
tick 2026-11-01T18:05:00-05:00 >/dev/null
ok "Day 1 evening: sonnet low, 20 turns, facts file built first" "[ -f ops/report_facts.md ] && grep -qx sonnet $FAKE_ARGS && grep -qx low $FAKE_ARGS && grep -qx 20 $FAKE_ARGS && [ \"\$(j ops/run.json 'd[\"run\"]')\" = evening ]"
ok "evening cost counted as reports, not project, and no kinds" "python3 -c \"import json; r=json.load(open('ops/usage.json'))['runs'][-1]; assert 'reports' in r['cats'] and 'project' not in r['cats'] and not r['kinds'], r\""
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
ok "status --json" "python3 tools/governor.py status --json --now 2026-11-03T10:00:00-05:00 | python3 -c 'import json,sys; d=json.load(sys.stdin); assert \"all_time_by_model_usd\" in d and \"shares_7d\" in d and \"plan\" in d and \"api\" in d and \"week_models\" in d'"
ok "claude gets /dev/null as stdin" "grep -q '< /dev/null' tools/supervisor.sh"
ok "no key ever reaches a plan session's environment, and the env scrub (which turns auto mode off) is never set" "grep -q 'unset CLAUDECODE ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN' tools/supervisor.sh && ! grep -q '^export.*CLAUDE_CODE_SUBPROCESS_ENV_SCRUB' tools/supervisor.sh tools/smoke_test.sh"

echo; echo "PASS $PASS  FAIL $FAIL"
[ "$FAIL" -eq 0 ]
