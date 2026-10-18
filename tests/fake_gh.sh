#!/bin/bash
# Stand-in for gh, used by the tests: records each call and never talks to GitHub.
echo "gh $*" >> "$(dirname "$0")/../../gh_calls.txt"
case "$1 $2" in
  "auth status") exit 0 ;;
  "issue create") echo "https://github.com/test/company/issues/1"; exit 0 ;;
  "issue list") echo '[{"number":7,"title":"Questions from Report 12","labels":[{"name":"report"}],"createdAt":"2026-11-03T18:10:00Z","url":"https://github.com/test/company/issues/7","comments":[]},{"number":8,"title":"Apple two-factor code needed","labels":[{"name":"urgent"}],"createdAt":"2026-11-04T09:00:00Z","url":"https://github.com/test/company/issues/8","comments":[{}]}]'; exit 0 ;;
  *) exit 1 ;;
esac
