#!/bin/bash
# The supervisor: one tick of the run loop. launchd runs it every 15 minutes.
# Plain bash; it never calls Claude itself. Company-owned (Commandment 3).
#
#   tools/supervisor.sh            one tick
#   CLAUDE_BIN=/path/to/claude     override the claude binary (tests use a stand-in)
#   GOVERNOR_NOW=ISO               pretend it is another time (tests)
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
LOCK="ops/.lock"
LOG="ops/runs/supervisor.log"
mkdir -p ops/runs ops/queue
NOW_ARGS=()
[ -n "${GOVERNOR_NOW:-}" ] && NOW_ARGS=(--now "$GOVERNOR_NOW")

log() { printf '%s %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG" >&2; }

# 1. Lock. A lock older than three hours is from a crashed run.
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +180 2>/dev/null)" ]; then
    rm -rf "$LOCK" && mkdir "$LOCK" || exit 0
    log "removed a stale lock"
  else
    log "another run is in progress"; exit 0
  fi
fi
trap 'rm -rf "$LOCK"' EXIT

# 2. Sync, so Investor edits to the fixed files take effect.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1 && git remote get-url origin >/dev/null 2>&1; then
  git pull --ff-only -q 2>>"$LOG" || log "git pull failed; continuing with the local copy"
fi

# 3. New Investor messages? (plain gh call; silent when gh isn't set up)
[ -x tools/inbox_check.sh ] && tools/inbox_check.sh 2>>"$LOG"

# 4. Decide. The governor checks limits, due reports, the daily share, and idle time.
DECISION="$(python3 -I tools/governor.py decide ${NOW_ARGS[@]+"${NOW_ARGS[@]}"})" || { log "governor failed"; exit 1; }
RUN="$(printf '%s' "$DECISION" | jq -r .run)"
REASON="$(printf '%s' "$DECISION" | jq -r .reason)"
log "$RUN: $REASON"
case "$RUN" in
  skip) exit 0 ;;
  queue) [ -x tools/run_queue.sh ] && tools/run_queue.sh; [ -x tools/site_publish.sh ] && tools/site_publish.sh >>"$LOG" 2>&1; exit 0 ;;
esac

# 5. Prepare the session: the run record it reads, the workers it can call, and for a
#    report the one facts file it reads instead of the repository (tools/report_facts.py).
printf '%s\n' "$DECISION" > ops/run.json
case "$RUN" in
  morning|evening|weekly|final)
    python3 -I tools/report_facts.py --kind "$RUN" ${NOW_ARGS[@]+"${NOW_ARGS[@]}"} >>"$LOG" 2>&1 \
      || log "report_facts failed; the report session will read the records itself" ;;
esac
FORMER=(); [ "$RUN" = final ] && FORMER=(--include-former)
python3 -I rules/build_agents.py ${FORMER[@]+"${FORMER[@]}"} >>"$LOG" 2>&1 || log "build_agents: no workers yet"
MODEL="$(printf '%s' "$DECISION" | jq -r .model)"
EFFORT="$(printf '%s' "$DECISION" | jq -r .effort)"
TURNS="$(printf '%s' "$DECISION" | jq -r .max_turns)"
PROMPT="ops/prompts/$(printf '%s' "$DECISION" | jq -r .prompt)"
[ -f "$PROMPT" ] || { log "missing prompt $PROMPT"; exit 1; }
command -v "$CLAUDE_BIN" >/dev/null 2>&1 || { log "claude not found on PATH"; exit 1; }
AGENTS=()
[ -s ops/agents.json ] && AGENTS=(--agents ops/agents.json)

# 6. Run one headless session. Nobody is here to answer prompts, so anything that
#    would ask is denied and the session continues. stream-json lets the governor
#    split the cost between project work, reports, meetings, and small talk;
#    --max-budget-usd stops a runaway session; stdin is closed so Claude Code
#    doesn't wait for piped input.
BUDGET="$(printf '%s' "$DECISION" | jq -r .max_budget_usd)"
ENTRY=""
run_session() {
  local base code
  base="ops/runs/$(date +%Y%m%d-%H%M%S)-$RUN"
  "$CLAUDE_BIN" -p "$(cat "$PROMPT")" ${AGENTS[@]+"${AGENTS[@]}"} \
    --model "$MODEL" --effort "$EFFORT" --max-turns "$TURNS" --max-budget-usd "$BUDGET" \
    --permission-mode auto --permission-prompts none \
    --no-session-persistence --output-format stream-json --verbose \
    < /dev/null > "$base.jsonl" 2>>"$LOG"
  code=$?
  ENTRY="$(python3 -I tools/governor.py record "$base.jsonl" --type "$RUN" --exit "$code" \
    --result-out "$base.json" ${NOW_ARGS[@]+"${NOW_ARGS[@]}"} 2>>"$LOG")"
  printf '%s\n' "$ENTRY" >> "$LOG"
  return $code
}
field() { printf '%s' "$ENTRY" | jq -r ".$1 // false" 2>/dev/null; }

# A logged-out Claude Code stops the whole company: an Emergency (Commandment 53), sent at
# once at any hour (at most every 12 hours). The governor retries hourly.
alert_logged_out() {
  local mark="ops/.auth_alerted" who body
  [ -n "$(find "$mark" -mmin -720 2>/dev/null)" ] && return 0
  if ! command -v gh >/dev/null 2>&1 || ! gh auth status >/dev/null 2>&1; then
    log "Claude Code is logged out and gh is unavailable for an alert"; return 0
  fi
  who="$(tr -d '\r' < investors/allowlist.md 2>/dev/null | sed 's/^[[:space:]]*@\{0,1\}//; s/[[:space:]]*$//' | grep -E '^[A-Za-z0-9-]{1,39}$' | sed 's/^/@/' | tr '\n' ' ')"
  body="Claude Code on the Mac mini is logged out, so no Claude sessions can run. The supervisor keeps running builds and queued scripts, and retries every hour.

To fix it: on the Mac mini, in the company's macOS account, open Terminal, run \`claude\`, type \`/login\`, and sign in with the company's Claude account. Work resumes within an hour.

$who"
  { gh issue create --label emergency --title "Claude Code is logged out on the Mac mini" --body "$body" \
    || gh issue create --title "EMERGENCY: Claude Code is logged out on the Mac mini" --body "$body"; } >>"$LOG" 2>&1 \
    && touch "$mark" && log "sent the logged-out alert"
}

run_session
CODE=$?
if [ "$(field retry)" = "true" ]; then
  log "session failed (exit $CODE); retrying once"
  run_session; CODE=$?
fi
[ "$(field auth_failed)" = "true" ] && alert_logged_out
find ops/runs -name '*.jsonl' -mtime +7 -exec rm -f {} + 2>/dev/null

# 7. Commit anything the session left behind, as the Operator, and push. Then
#    rebuild the public site from the records (no Claude) and push that too.
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  git add -A
  git -c user.name=Operator -c user.email=operator@company commit -q -m "ops: $RUN run $(date +%Y-%m-%d\ %H:%M)" \
    && { git remote get-url origin >/dev/null 2>&1 && git push -q 2>>"$LOG" || true; }
fi
[ -x tools/site_publish.sh ] && tools/site_publish.sh >>"$LOG" 2>&1
exit "$CODE"
