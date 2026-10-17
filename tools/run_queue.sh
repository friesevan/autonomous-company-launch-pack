#!/bin/bash
# Runs the no-Claude queue: every *.sh or *.py in ops/queue/, in name order, then
# moves it to ops/queue/done/. The supervisor calls this when the usage governor
# says no Claude session may start. Each item is one script with a clear name;
# its output goes to ops/runs/queue-<time>.log for the next session to read.
# Company-owned.
cd "$(dirname "$0")/.." || exit 1
mkdir -p ops/queue/done ops/runs
TS="$(date +%Y%m%d-%H%M%S)"
LOG="ops/runs/queue-$TS.log"
shopt -s nullglob
ran=0
for f in ops/queue/*.sh ops/queue/*.py; do
  ran=1
  echo "== $f ($(date '+%F %T'))" >>"$LOG"
  case "$f" in
    *.py) python3 -I "$f" >>"$LOG" 2>&1 ;;
    *) bash "$f" >>"$LOG" 2>&1 ;;
  esac
  echo "exit $?" >>"$LOG"
  mv "$f" "ops/queue/done/$(basename "$f").$TS"
done
[ "$ran" = 1 ] && echo "queue: see $LOG" || echo "queue: empty"
