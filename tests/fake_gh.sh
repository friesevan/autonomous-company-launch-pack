#!/bin/bash
# Stand-in for gh, used by the tests: records each call and never talks to GitHub.
echo "gh $*" >> "$(dirname "$0")/../../gh_calls.txt"
case "$1 $2" in
  "auth status") exit 0 ;;
  "issue create") echo "https://github.com/test/company/issues/1"; exit 0 ;;
  *) exit 1 ;;
esac
