#!/bin/bash
# Runs the launch pack's tests in a throwaway copy of this repository, with a
# stand-in claude and a stand-in gh, so nothing talks to Anthropic or GitHub
# and no usage is spent.
#   tests/run.sh
set -u
SRC="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d "${TMPDIR:-/tmp}/launch-pack-tests.XXXXXX")" || exit 1
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/home/.local/bin" "$T/repo"
(cd "$SRC" && tar --exclude ./.git --exclude ./tests -cf - .) | (cd "$T/repo" && tar -xf -)
cp "$SRC/tests/fake_claude.py" "$T/bin/claude"
cp "$SRC/tests/fake_gh.sh" "$T/home/.local/bin/gh"
chmod +x "$T/bin/claude" "$T/home/.local/bin/gh"
printf 'alice-dev\nbob42\n' >> "$T/repo/investors/allowlist.md"
(cd "$T/repo" && git init -q && git add -A && git -c user.name=test -c user.email=test@example.com commit -qm init) || exit 1
export T
status=0
echo "== portrait_test.py"
python3 "$SRC/tests/portrait_test.py" > "$T/portrait_test.log" 2>&1 || status=1
grep -E "^(FAIL|PASS [0-9]+  FAIL)" "$T/portrait_test.log" || { echo "no summary line; last output:"; tail -20 "$T/portrait_test.log"; status=1; }
for suite in supervisor_test.sh pacing_test.sh site_test.sh hiring_test.sh facts_test.sh; do
  echo "== $suite"
  log="$T/$suite.log"
  bash "$SRC/tests/$suite" > "$log" 2>&1 || status=1
  grep -E "^(FAIL|PASS [0-9]+  FAIL)" "$log" || { echo "no summary line; last output:"; tail -20 "$log"; status=1; }
done
[ "$status" -eq 0 ] && echo "All tests passed." || echo "Some tests failed."
exit "$status"
