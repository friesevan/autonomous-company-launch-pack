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
# XCTest ("Test Case '...' failed (0.1 seconds)") and Swift Testing ("Test foo() failed after 0.1 seconds",
# "Test run with 12 tests failed after ..."), in any case.
grep -iE "error:|warning:|test case .* (failed|passed) \(|test suite .* (failed|passed)|executed [0-9]+ test|test run with [0-9]+ tests? .*(passed|failed)|test .* failed after|\*\* (BUILD|TEST|ARCHIVE|EXPORT) [A-Z]+ \*\*|fatal error|command .* failed" "$LOG" \
  | grep -viE "test case .* passed \(" \
  | awk '!seen[$0]++' | head -40 > "$LOG.summary"
if [ -s "$LOG.summary" ]; then cat "$LOG.summary"; else tail -5 "$LOG"; fi
rm -f "$LOG.summary"
echo "exit $STATUS; full log: $LOG ($(wc -l < "$LOG" | tr -d ' ') lines)"
exit "$STATUS"
