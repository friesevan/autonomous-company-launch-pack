#!/bin/bash
# Quiet Xcode wrapper: runs xcodebuild, keeps the full log on disk, prints only what
# matters (errors, warnings, failing tests, the final status), at most 40 lines.
#   tools/xc.sh -scheme App -destination 'platform=iOS Simulator,name=iPhone 16' build
#   tools/xc.sh -scheme App -destination '...' test
# Exit status is xcodebuild's. Company-owned.
cd "$(dirname "$0")/.." || exit 1
mkdir -p ops/runs
TS="$(date +%Y%m%d-%H%M%S)"
LOG="ops/runs/xcodebuild-$TS.log"
xcodebuild "$@" 2>&1 | tee "$LOG" >/dev/null
STATUS=${PIPESTATUS[0]}
grep -E "error:|warning:|Test Case .* (failed|passed) \(|Test Suite .* (failed|passed)|Executed [0-9]+ test|\*\* (BUILD|TEST|ARCHIVE|EXPORT) [A-Z]+ \*\*|fatal error|Command .* failed" "$LOG" \
  | grep -vE "Test Case .* passed \(" \
  | awk '!seen[$0]++' | head -40 > "$LOG.summary"
if [ -s "$LOG.summary" ]; then cat "$LOG.summary"; else tail -5 "$LOG"; fi
rm -f "$LOG.summary"
echo "exit $STATUS; full log: $LOG ($(wc -l < "$LOG" | tr -d ' ') lines)"
exit "$STATUS"
