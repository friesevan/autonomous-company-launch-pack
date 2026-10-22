#!/bin/bash
# Stand-in for gh, used by the tests: records each call and never talks to GitHub.
# Canned answers live beside gh_calls.txt in the test home: gh_issues.jsonl and gh_comments.jsonl
# (the inbox's API reads, one JSON object per line, already in the shape its --jq filter makes),
# gh_issue_list.json (issue list), gh_issue_view.json (issue view). GH_FAIL=1 makes every call fail.
D="$(dirname "$0")/../.."
echo "gh $*" >> "$D/gh_calls.txt"
[ "${GH_FAIL:-0}" = 1 ] && exit 1
# GH_FAIL_LABEL=1: creating an issue with a label fails, as when the label doesn't exist yet.
[ "${GH_FAIL_LABEL:-0}" = 1 ] && [ "$1 $2" = "issue create" ] && case "$*" in *--label*) exit 1 ;; esac
case "$1 $2" in
  "auth status") exit 0 ;;
  "issue create") n=$(( $(cat "$D/gh_next_issue" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$D/gh_next_issue"
    echo "https://github.com/test/company/issues/$n"; exit 0 ;;
  "issue comment"|"issue close"|"variable set"|"label create") exit 0 ;;
  "issue list")
    if [ -f "$D/gh_issue_list.json" ]; then
      # Apply the caller's own contains("...") filter, as gh's jq would, so a wrong marker fails here too.
      case "$*" in *--jq*) python3 -c 'import json, re, sys
d = json.load(open(sys.argv[1]))
m = re.search(r"contains\(\"(.*?)\"\)", sys.argv[2])
needle = m.group(1) if m else ""
hits = [i["number"] for i in d if needle and needle in (i.get("body") or "")]
print(hits[0] if hits else "")' "$D/gh_issue_list.json" "$*" ;; *) cat "$D/gh_issue_list.json" ;; esac
      exit 0
    fi
    case "$*" in *--jq*) exit 0 ;; esac
    echo '[{"number":7,"title":"Questions from Report 12","labels":[{"name":"report"}],"createdAt":"2026-11-03T18:10:00Z","url":"https://github.com/test/company/issues/7","comments":[]},{"number":8,"title":"Apple two-factor code needed","labels":[{"name":"urgent"}],"createdAt":"2026-11-04T09:00:00Z","url":"https://github.com/test/company/issues/8","comments":[{}]}]'
    exit 0 ;;
  "issue view") [ -f "$D/gh_issue_view.json" ] && python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["body"])' "$D/gh_issue_view.json"; exit 0 ;;
  "api user") echo "company-bot"; exit 0 ;;
  "api -X")
    case "$*" in
      *issues/comments*) [ -f "$D/gh_comments.jsonl" ] && cat "$D/gh_comments.jsonl" ;;
      *issues*) [ -f "$D/gh_issues.jsonl" ] && cat "$D/gh_issues.jsonl" ;;
    esac
    exit 0 ;;
  *) exit 1 ;;
esac
