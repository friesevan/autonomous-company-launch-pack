#!/bin/bash
# The supervisor: one tick of the run loop. launchd runs it every 15 minutes.
# Plain bash. It starts Claude only for the session the governor picks and to read the plan's
# own usage meter (a local /usage command: no model call, no usage). Company-owned (Commandment 3).
#
#   tools/supervisor.sh             one tick
#   tools/supervisor.sh --dry-run   decide and print the session it would start, then stop: no
#                                   Claude session, no commits, no alerts, no replies (Day 1 uses it)
#   CLAUDE_BIN=/path/to/claude      override the claude binary (tests use a stand-in)
#   GOVERNOR_NOW=ISO                pretend it is another time (tests)
#   SECURITY_BIN=/usr/bin/security  the Keychain tool (tests use a stand-in)
#   SESSION_MINUTES=150             stop a session that runs longer than this (SESSION_SECONDS for tests)
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
export CLAUDE_BIN="${CLAUDE_BIN:-claude}"
SECURITY_BIN="${SECURITY_BIN:-/usr/bin/security}"
SESSION_MINUTES="${SESSION_MINUTES:-150}"
SESSION_SECONDS="${SESSION_SECONDS:-$((SESSION_MINUTES * 60))}"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
LOCK="ops/.lock"
LOG="ops/runs/supervisor.log"
mkdir -p ops/runs ops/queue
NOW_ARGS=()
[ -n "${GOVERNOR_NOW:-}" ] && NOW_ARGS=(--now "$GOVERNOR_NOW")

# Plan sessions bill the subscription login, never a key in the environment. Auto-updates stay
# off: a new Claude Code release could change what -p does (Ops Guide, section 3). Commands a
# session runs never see a credential. A session that can't start still writes a result.
unset CLAUDECODE ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
export PYTHONDONTWRITEBYTECODE=1 DISABLE_AUTOUPDATER=1 CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1 CLAUDE_CODE_STARTUP_FAILURE_RESULTS=1 COMPANY_RUN=1

log() { printf '%s %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG" >&2; }
j() { printf '%s' "$1" | jq -r "$2" 2>/dev/null; }

# Background helpers. macOS has no timeout command: a watcher sends SIGTERM, then SIGKILL.
stop_bg() { pkill -P "$1" 2>/dev/null; kill "$1" 2>/dev/null; wait "$1" 2>/dev/null; return 0; }
# run_limited <seconds> <command...>; with PID_FILE set, the command's process ID is written there.
run_limited() {
  local secs="$1" pid watcher code
  shift
  "$@" &
  pid=$!
  [ -n "${PID_FILE:-}" ] && echo "$pid" > "$PID_FILE"
  ( sleep "$secs"; kill -TERM "$pid" 2>/dev/null; sleep 30; kill -KILL "$pid" 2>/dev/null ) &
  watcher=$!
  wait "$pid"; code=$?
  stop_bg "$watcher"
  return "$code"
}

# 0. Heartbeat for the watchdog on GitHub (.github/workflows/watchdog.yml), which raises an
#    Emergency after 45 quiet minutes: the Mac off, offline, stuck at the FileVault screen.
# Helper scripts run through their interpreter, so a lost execute bit can't silently skip one.
heartbeat() { [ "$DRY" = 0 ] && [ -f tools/heartbeat.sh ] && bash tools/heartbeat.sh >/dev/null 2>&1; return 0; }
heartbeat

# 1. Lock. A lock whose process is gone (a crash, a restart) is stale at once; one without a
#    process ID after three hours, and any after six.
take_lock() { mkdir "$LOCK" 2>/dev/null && echo $$ > "$LOCK/pid"; }
if [ "$DRY" = 0 ] && ! take_lock; then
  pid="$(cat "$LOCK/pid" 2>/dev/null)"
  if { [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; } \
     || { [ -z "$pid" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +180 2>/dev/null)" ]; } \
     || [ -n "$(find "$LOCK" -maxdepth 0 -mmin +360 2>/dev/null)" ]; then
    rm -rf "$LOCK"; take_lock || exit 0
    log "removed a stale lock"
  else
    log "another run is in progress"; exit 0
  fi
fi
[ "$DRY" = 0 ] && trap 'rm -rf "$LOCK"' EXIT

# Emergencies (Commandment 53) go out at once, at any hour; each kind at most every 12 hours.
mentions() {
  tr -d '\r' < investors/allowlist.md 2>/dev/null | sed 's/^[[:space:]]*@\{0,1\}//; s/[[:space:]]*$//' \
    | grep -E '^[A-Za-z0-9-]{1,39}$' | sed 's/^/@/' | tr '\n' ' '
}
alert() {
  local kind="$1" title="$2" body="$3" mark="ops/.alerted_$1"
  if [ "$DRY" = 1 ]; then log "dry run: would send the $kind alert"; return 0; fi
  [ -n "$(find "$mark" -mmin -720 2>/dev/null)" ] && return 0
  if ! command -v gh >/dev/null 2>&1 || ! gh auth status >/dev/null 2>&1; then
    log "$kind: gh is unavailable for an alert"; return 0
  fi
  body="$body

$(mentions)"
  { gh issue create --label emergency --title "$title" --body "$body" \
    || gh issue create --title "EMERGENCY: $title" --body "$body"; } >>"$LOG" 2>&1 \
    && touch "$mark" && log "sent the $kind alert"
}

# Three failed ticks in a row (failed sessions, the governor, git sync) mean no work is getting
# done: an Emergency. Log-outs and plan limits have their own handling and don't count.
FAILS="ops/.fail_count"
tick_failed() {
  [ "$DRY" = 1 ] && return 0
  local n
  n=$(( $(cat "$FAILS" 2>/dev/null || echo 0) + 1 ))
  echo "$n" > "$FAILS"
  printf '%s %s\n' "$(date '+%F %T')" "$1" >> ops/.fail_reasons
  tail -n 5 ops/.fail_reasons > ops/.fail_reasons.tmp && mv ops/.fail_reasons.tmp ops/.fail_reasons
  log "failed tick $n in a row: $1"
  [ "$n" -ge 3 ] && alert failing "The company's runs keep failing on the Mac mini" "The last $n ticks of the run loop failed, so no work is getting done. The most recent reasons:

\`\`\`
$(cat ops/.fail_reasons 2>/dev/null)
\`\`\`

The run loop keeps trying every 15 minutes. To look: on the Mac mini, in the company folder, run \`tail -50 ops/runs/supervisor.log\` and \`python3 tools/governor.py status\`. If git sync fails, the company's copy and GitHub have diverged: \`git status\` shows it. Reply here with what you found or changed; the company reads it at its next session."
  return 0
}
tick_ok() { rm -f "$FAILS" ops/.fail_reasons; }

# 2. Sync, so Investor edits to the fixed files take effect. Sessions never pull (the security
#    guard refuses it), so this is the one place GitHub's changes come in. Local commits are
#    replayed on top; where a local change and GitHub's conflict, GitHub's lines win.
SYNC_OK=1
keep_github_version() {  # resolve files left unmerged (by a conflicting autostash) to the GitHub version
  local unmerged
  unmerged="$(git diff --name-only --diff-filter=U 2>/dev/null)"
  [ -n "$unmerged" ] || return 0
  while IFS= read -r f; do [ -n "$f" ] && git checkout -q HEAD -- "$f" 2>/dev/null; done <<< "$unmerged"
  git reset -q 2>/dev/null
  log "git pull: kept the GitHub version of $(printf '%s ' $unmerged); the local change is in git stash"
}
sync_repo() {
  { git rev-parse --is-inside-work-tree && git remote get-url origin; } >/dev/null 2>&1 || return 0
  if git pull --rebase --autostash -q 2>>"$LOG"; then keep_github_version; return 0; fi
  git rebase --abort >/dev/null 2>&1
  keep_github_version
  # A conflicting local commit: replay it again with GitHub's side winning each conflicting hunk.
  if git pull --rebase --autostash -X ours -q 2>>"$LOG"; then
    keep_github_version
    log "git pull: a local commit conflicted with GitHub; GitHub's lines were kept"
    return 0
  fi
  git rebase --abort >/dev/null 2>&1
  keep_github_version
  SYNC_OK=0
  log "git pull failed; continuing with the local copy"
}
push_if_ahead() {
  git remote get-url origin >/dev/null 2>&1 || return 0
  [ "$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo 1)" = 0 ] && return 0
  git push -q 2>>"$LOG" || { SYNC_OK=0; log "git push failed"; }
}
[ "$DRY" = 0 ] && sync_repo

# 3. Security posture, no Claude: an Emergency when a protection that was on is off now.
if [ "$DRY" = 0 ] && [ -f rules/posture.sh ]; then
  OFF="$(bash rules/posture.sh 2>>"$LOG" | sed -n 's/^off //p' | tr '\n' ' ')"
  [ -n "$OFF" ] && alert posture "A security setting was switched off on the Mac mini" "These protections were on before and are off now: $OFF

The company must never weaken the Mac's security (Commandment 2). If one of you changed it, reply here to say so. Otherwise, turn it back on in System Settings, and reply PAUSE to stop the company while you look: the run log (\`ops/runs/supervisor.log\`) and \`log/sudo.log\` show what ran."
fi

# 4. New Investor messages, no Claude. PAUSE, STOP, and RESUME take effect here.
[ "$DRY" = 0 ] && [ -f tools/inbox.py ] && python3 -I tools/inbox.py poll ${NOW_ARGS[@]+"${NOW_ARGS[@]}"} >>"$LOG" 2>&1

# 5. The plan's own meter: exact percentages and reset times, at no cost.
if [ "$DRY" = 0 ] && command -v "$CLAUDE_BIN" >/dev/null 2>&1 \
   && python3 -I tools/governor.py meter --due ${NOW_ARGS[@]+"${NOW_ARGS[@]}"}; then
  run_limited 120 "$CLAUDE_BIN" -p "/usage" --model haiku --max-turns 1 --max-budget-usd 0.05 --tools "" \
    --no-session-persistence --output-format stream-json --verbose < /dev/null > ops/runs/meter.jsonl 2>>"$LOG"
  METER="$(python3 -I tools/governor.py meter ops/runs/meter.jsonl ${NOW_ARGS[@]+"${NOW_ARGS[@]}"} 2>>"$LOG")"
  printf 'meter %s\n' "$METER" >> "$LOG"
  [ "$(j "$METER" '.credits_on')" = true ] && alert credits "Usage credits are switched on for the company's Claude plan" "The plan's usage meter reports usage credits as enabled. At a usage limit, Claude would then bill real money instead of pausing, which the Commandments forbid without your approval (Spending rules). On claude.ai, signed in as the company's account, open Settings > Usage and turn usage credits off. Reply here when done."
fi

# 6. Can API credits carry on while a plan limit pauses work? The Investors' switch and a key.
API_ARGS=()
api_ready() {
  python3 -I -c 'import json, sys
sys.exit(0 if json.load(open("investors/billing.json", encoding="utf-8")).get("api_overflow") is True else 1)' 2>/dev/null \
    || return 1
  "$SECURITY_BIN" find-generic-password -s company-api-credits -a company >/dev/null 2>&1
}
api_ready && API_ARGS=(--api-ready)

# 7. Decide. The governor checks pauses, limits, due reports, the daily share, and idle time.
DRY_ARGS=()
[ "$DRY" = 1 ] && DRY_ARGS=(--dry-run)
DECISION="$(python3 -I tools/governor.py decide ${NOW_ARGS[@]+"${NOW_ARGS[@]}"} ${API_ARGS[@]+"${API_ARGS[@]}"} \
  ${DRY_ARGS[@]+"${DRY_ARGS[@]}"})" || { log "governor failed"; tick_failed "the governor failed"; exit 1; }
RUN="$(j "$DECISION" .run)"
REASON="$(j "$DECISION" .reason)"
BILLING="$(j "$DECISION" '.billing // "plan"')"
log "$RUN: $REASON"
[ "$DRY" = 0 ] && printf '%s\n' "$DECISION" > ops/last_decision.json

# Messages that no session will answer this tick get a receipt, once each (no Claude).
if [ "$DRY" = 0 ] && [ -f ops/inbox_pending ] && [ -f tools/inbox.py ]; then
  case "$RUN" in
    work|inbox) ;;
    *) python3 -I tools/inbox.py receipt --decision ops/last_decision.json ${NOW_ARGS[@]+"${NOW_ARGS[@]}"} >>"$LOG" 2>&1 ;;
  esac
fi

case "$RUN" in
  skip|hold)
    [ "$DRY" = 1 ] && { echo "dry run: $RUN: $REASON"; exit 0; }
    # A pause the supervisor itself set is re-sent every 12 hours until someone answers it, in
    # case its first alert didn't go out (the heartbeat keeps the watchdog quiet meanwhile).
    if [ -f ops/paused ] && grep -q '"by": "the supervisor"' ops/paused 2>/dev/null \
       && [ -z "$(find ops -maxdepth 1 \( -name .alerted_hooks -o -name .alerted_version \) -mmin -720 2>/dev/null)" ]; then
      alert paused "The company is paused and waiting for you" "The supervisor paused the company: $(sed -n 's/.*"reason": "\([^"]*\)".*/\1/p' ops/paused). Nothing runs until one of you comments RESUME on any issue. The earlier emergency issue, if it reached you, says what to check."
    fi
    if [ "$SYNC_OK" = 1 ]; then tick_ok; else tick_failed "git sync failed"; fi
    exit 0 ;;
  queue)
    [ "$DRY" = 1 ] && { echo "dry run: queue (no Claude session): $REASON"; exit 0; }
    [ -f tools/run_queue.sh ] && bash tools/run_queue.sh
    push_if_ahead
    [ -f tools/site_publish.sh ] && bash tools/site_publish.sh >>"$LOG" 2>&1
    if [ "$SYNC_OK" = 1 ]; then tick_ok; else tick_failed "git sync failed"; fi
    exit 0 ;;
esac

# 8. Prepare the session: the run record it reads, the workers it can call, and for a report
#    the one facts file it reads instead of the repository (tools/report_facts.py).
MODEL="$(j "$DECISION" .model)"
EFFORT="$(j "$DECISION" .effort)"
TURNS="$(j "$DECISION" .max_turns)"
BUDGET="$(j "$DECISION" .max_budget_usd)"
PROMPT="ops/prompts/$(j "$DECISION" .prompt)"
[ -f "$PROMPT" ] || { log "missing prompt $PROMPT"; tick_failed "missing prompt $PROMPT"; exit 1; }
command -v "$CLAUDE_BIN" >/dev/null 2>&1 || { log "claude not found on PATH"; tick_failed "claude not found on PATH"; exit 1; }
AGENTS=()
[ -s ops/agents.json ] && AGENTS=(--agents ops/agents.json)
# Credit sessions take their key from the Keychain through rules/api-settings.json, never from
# the environment, and never run Fable (the model guard refuses it when billing is api).
SETTINGS=()
[ "$BILLING" = api ] && SETTINGS=(--settings rules/api-settings.json)
FLAGS=(--model "$MODEL" --effort "$EFFORT" --max-turns "$TURNS" --max-budget-usd "$BUDGET"
  --permission-mode auto --permission-prompts none --forward-subagent-text
  --no-session-persistence --output-format stream-json --verbose)

if [ "$DRY" = 1 ]; then
  echo "dry run: would start a $RUN session on the $([ "$BILLING" = api ] && echo "API credits" || echo "plan"): $REASON"
  echo "  $CLAUDE_BIN -p \"\$(cat $PROMPT)\" ${AGENTS[*]+${AGENTS[*]}} ${SETTINGS[*]+${SETTINGS[*]}} ${FLAGS[*]}"
  echo "  claude auth: $("$CLAUDE_BIN" auth status --text 2>&1 | head -3 | tr '\n' ' ')"
  exit 0
fi

# A new Claude Code version is checked before it runs a plan session: the smoke test runs one tiny
# real session and confirms the login, auto mode, the hooks, and CLAUDE.md. A broken check pauses
# the company; a session that couldn't run at all (a network blip, an overloaded API) is retried at
# the next tick. Sessions on API credits wait for a plan session to check the version.
VERSION="$("$CLAUDE_BIN" --version 2>/dev/null | head -1)"
if [ "$BILLING" = plan ] && [ -n "$VERSION" ] && [ "$VERSION" != "$(cat ops/claude_version 2>/dev/null)" ] \
   && [ -f tools/smoke_test.sh ]; then
  CLAUDE_BIN="$CLAUDE_BIN" run_limited 300 bash tools/smoke_test.sh >>"$LOG" 2>&1
  SMOKE=$?
  if [ "$SMOKE" = 0 ]; then
    echo "$VERSION" > ops/claude_version
    log "Claude Code is $VERSION; the smoke test passed"
  elif [ "$SMOKE" = 1 ]; then
    printf '{"by": "the supervisor", "at": "%s", "reason": "Claude Code %s failed its smoke test"}\n' "$(date '+%F %T')" "$VERSION" > ops/paused
    alert version "The company paused itself: Claude Code $VERSION failed its smoke test" "Claude Code on the Mac mini is now $VERSION, and the smoke test that runs before a new version's first session failed, so the company paused itself. The failing checks are at the end of \`ops/runs/supervisor.log\`.

To fix it, on the Mac mini in the company folder: run \`tools/smoke_test.sh\` and follow the fix it prints. If the new version itself is the problem, reinstall the last good one (\`curl -fsSL https://claude.ai/install.sh | bash -s <version>\`). Then comment RESUME here."
    exit 0
  else
    tick_failed "the smoke test for Claude Code $VERSION couldn't run a session; retrying next tick"
    exit 0
  fi
fi

printf '%s\n' "$DECISION" > ops/run.json
case "$RUN" in
  morning|evening|weekly|final)
    python3 -I tools/report_facts.py --kind "$RUN" ${NOW_ARGS[@]+"${NOW_ARGS[@]}"} >>"$LOG" 2>&1 \
      || log "report_facts failed; the report session will read the records itself" ;;
esac
FORMER=(); [ "$RUN" = final ] && FORMER=(--include-former)
python3 -I rules/build_agents.py ${FORMER[@]+"${FORMER[@]}"} >>"$LOG" 2>&1 || log "build_agents: no workers yet"
[ -s ops/agents.json ] && AGENTS=(--agents ops/agents.json)

# 9. Run one headless session. Nobody is here to answer prompts, so anything that would ask is
#    denied and the session continues. stream-json (with the workers' messages forwarded) lets
#    the governor split the cost by category, kind of work, and model; --max-budget-usd stops a
#    runaway session; a session past SESSION_MINUTES is stopped; stdin is closed so Claude Code
#    doesn't wait for piped input. The SessionStart hook marks ops/.hooks_ok.
ENTRY=""
HEAD_BEFORE="$(git rev-parse -q --verify HEAD 2>/dev/null)"
[ -f rules/file-guard.sh ] && bash rules/file-guard.sh snapshot 2>>"$LOG"
# The hooks also learn the billing and the Fable allowance from the environment, so they still
# refuse Fable on API credits if ops/run.json goes missing.
export COMPANY_BILLING="$BILLING" COMPANY_FABLE_OK="$(j "$DECISION" '.fable_ok')"
run_session() {
  local base code
  base="ops/runs/$(date +%Y%m%d-%H%M%S)-$RUN"
  rm -f ops/.hooks_ok
  STARTED="$(date +%s)"
  PID_FILE=ops/.session_pid run_limited "$SESSION_SECONDS" "$CLAUDE_BIN" -p "$(cat "$PROMPT")" ${AGENTS[@]+"${AGENTS[@]}"} \
    ${SETTINGS[@]+"${SETTINGS[@]}"} "${FLAGS[@]}" < /dev/null > "$base.jsonl" 2>>"$LOG"
  code=$?
  rm -f ops/.session_pid
  ENTRY="$(python3 -I tools/governor.py record "$base.jsonl" --type "$RUN" --exit "$code" --billing "$BILLING" \
    --started "$STARTED" --result-out "$base.json" ${NOW_ARGS[@]+"${NOW_ARGS[@]}"} 2>>"$LOG")"
  printf '%s\n' "$ENTRY" >> "$LOG"
  return $code
}
field() { printf '%s' "$ENTRY" | jq -r ".$1 // false" 2>/dev/null; }

# A long session keeps the heartbeat going (launchd starts no new tick while this one runs), and
# the inbox too: a PAUSE or STOP that arrives mid-session stops the session within minutes.
KEEPER_SECONDS="${KEEPER_SECONDS:-300}"
(
  while sleep "$KEEPER_SECONDS"; do
    [ -f tools/heartbeat.sh ] && bash tools/heartbeat.sh >/dev/null 2>&1
    [ -f tools/inbox.py ] && python3 -I tools/inbox.py poll >>"$LOG" 2>&1
    if [ -f ops/paused ] && [ -f ops/.session_pid ]; then
      kill -TERM "$(cat ops/.session_pid)" 2>/dev/null && log "an Investor paused the company: stopping the session"
    fi
  done
) &
KEEPER=$!
run_session
CODE=$?
# A failed session is retried once, unless it was paused or ran on API credits (a retry would
# spend the credits' cap a second time).
if [ "$(field retry)" = "true" ] && [ ! -f ops/paused ] && [ "$BILLING" = plan ]; then
  log "session failed (exit $CODE); retrying once"
  run_session; CODE=$?
fi
stop_bg "$KEEPER"
find ops/runs -name '*.jsonl' -mtime +7 -exec rm -f {} + 2>/dev/null

# 10. After the session: what needs a person.
if [ "$(field auth_failed)" = "true" ] && [ "$BILLING" = plan ]; then
  alert logged-out "Claude Code is logged out on the Mac mini" "Claude Code on the Mac mini is logged out, so no Claude sessions can run. The supervisor keeps running builds and queued scripts, and retries every hour.

To fix it: on the Mac mini, in the company's macOS account, open Terminal, run \`claude\`, type \`/login\`, and sign in with the company's Claude account. Work resumes within an hour."
fi
if [ "$(field billing_mismatch)" = "true" ]; then
  alert billing "A Claude session was billed to an API key instead of the plan" "The last session reported its key source as \`$(field api_key_source)\` instead of the subscription login, so it may have spent API credits or real money. API-credit overflow is off for 7 days. To check: on the Mac mini, run \`claude auth status\`, and look for an \`apiKeyHelper\` or \`ANTHROPIC_API_KEY\` in ~/.claude/settings.json, the shell profile, or the launchd job. Reply here when it's fixed."
fi
TURNS_RAN="$(field turns)"
if [ "$TURNS_RAN" -gt 0 ] 2>/dev/null && [ ! -f ops/.hooks_ok ]; then
  printf '{"by": "the supervisor", "at": "%s", "reason": "a session ran without the company hooks"}\n' "$(date '+%F %T')" > ops/paused
  alert hooks "The company paused itself: a session ran without its safety hooks" "Claude Code ran the last session without the company's hooks (the SessionStart mark is missing). Without them, the model, security, and record guards are off, and CLAUDE.md may not have loaded either. A Claude Code update can cause this: its docs say the minimal --bare mode will become the default for -p. The company is paused until you check.

To check, on the Mac mini in the company folder: \`claude --version\`, \`claude doctor\`, and \`tools/smoke_test.sh\`. If an update caused it, reinstall the last good version (\`curl -fsSL https://claude.ai/install.sh | bash -s <version>\`). Then comment RESUME here."
fi
SESSION_BAD=0
if [ -f ops/paused ] && ! grep -q '"by": "the supervisor"' ops/paused 2>/dev/null; then
  log "the session ended for an Investor's pause"
else
  [ "$(field retry)" = "true" ] && SESSION_BAD=1
  [ "$(field timed_out)" = "true" ] && SESSION_BAD=1 && log "the session ran past $((SESSION_SECONDS / 60)) minutes and was stopped"
  [ "$(field mode_ok)" = "false" ] && SESSION_BAD=1 && log "the session ran in permission mode $(field permission_mode), not auto"
fi

# 11. Investor-owned files change only through GitHub. Anything the session changed there,
#     committed or not, goes back, and the Investors hear about it. So does an amendment that
#     doesn't quote an Investor message word for word (rules/amendment-check.py).
if [ -f rules/file-guard.sh ]; then
  RESTORED="$(bash rules/file-guard.sh check "$HEAD_BEFORE" 2>>"$LOG")"
  if [ -f rules/amendment-check.py ]; then
    AMENDED="$(python3 -I rules/amendment-check.py "$HEAD_BEFORE" 2>>"$LOG")"
    RESTORED="$(printf '%s\n%s\n' "$RESTORED" "$AMENDED" | sed '/^$/d')"
  fi
  if [ -n "$RESTORED" ]; then
    log "file guard: $(printf '%s' "$RESTORED" | tr '\n' ' ')"
    alert tamper "A session changed Investor-owned files; the supervisor put them back" "The last $RUN session changed files that only the Investors edit (Commandment 2). The supervisor restored them from GitHub; new files and settings files are kept in \`ops/quarantine/\` for you to look at:

\`\`\`
$RESTORED
\`\`\`

If you meant to change one of these, edit it on github.com; the next tick pulls it. To see what the session did, read the run log in \`ops/runs/\`. Reply PAUSE to stop the company while you look."
  fi
fi

# 12. Commit anything the session left behind, as the Operator, and push. Then rebuild the
#     public site from the records (no Claude) and push that too.
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  git add -A
  git -c user.name=Operator -c user.email=operator@company commit -q -m "ops: $RUN run $(date +%Y-%m-%d\ %H:%M)"
fi
push_if_ahead
[ -f tools/site_publish.sh ] && bash tools/site_publish.sh >>"$LOG" 2>&1
if [ "$SESSION_BAD" = 1 ]; then
  tick_failed "the $RUN session failed (exit $CODE, $(field subtype), $(field terminal_reason))"
elif [ "$SYNC_OK" = 0 ]; then
  tick_failed "git sync failed (pull or push)"
else
  tick_ok
fi
exit "$CODE"
