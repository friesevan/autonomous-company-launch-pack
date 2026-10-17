#!/bin/bash
# PreToolUse hook: refuse shell commands that delete or move the company's
# permanent records or the Investors' files. Records are archived, never
# deleted (Operations Guide, section 3). Investors own this file.
#
# Reads the hook event JSON on stdin. Exit 2 blocks the call and shows the
# message on stderr to Claude. Exit 0 lets the normal permission flow decide.

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$cmd" ] && exit 0

protected='(^|[[:space:]/"'\''])(log|story|reports|rules|setup|investors)(/|[[:space:]"'\'']|$)|(^|[[:space:]/"'\''])(CLAUDE\.md|amendments\.md)([[:space:]"'\'']|$)'
destructive='(^|[;&|[:space:]])(rm|rmdir|unlink|shred|mv|git[[:space:]]+rm|git[[:space:]]+mv|git[[:space:]]+clean|git[[:space:]]+filter-branch|git[[:space:]]+filter-repo)([[:space:]]|$)|[[:space:]]-delete([[:space:]]|$)'

if printf '%s' "$cmd" | grep -Eq "$destructive" && printf '%s' "$cmd" | grep -Eq "$protected"; then
  echo "Blocked by protect-records: log/, story/, reports/, rules/, setup/, investors/, CLAUDE.md and amendments.md are never deleted or moved. Archive instead, or ask the Investors." >&2
  exit 2
fi
exit 0
