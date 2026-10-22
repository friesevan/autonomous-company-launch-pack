#!/bin/bash
# Keeps the Investor-owned files the Investors' (Commandment 2). The supervisor runs it around
# every session. Investors own this file.
#
#   rules/file-guard.sh snapshot           before a session: note the state of the protected files
#   rules/file-guard.sh check <commit>     after it: put back anything the session changed, committed
#                                          or not, and print one line per file it restored
#
# Protected: CLAUDE.md, CLAUDE.local.md, setup/, rules/, investors/, .github/, .mcp.json (an MCP
# server there would run code outside the hooks), the Claude Code files that change how sessions
# behave (.claude/settings.json, .claude/settings.local.json even when git ignores it,
# .claude/CLAUDE.md, .claude/agents, commands, rules, hooks, output-styles), and the risky keys of
# the user's ~/.claude/settings.json (hooks, permissions, env, the API key helper). The rest of
# .claude/, such as the workers' memories in .claude/agent-memory/, is the company's.
# Tracked files go back to their version at <commit>, the commit before the session; new files
# and changed settings files move to ops/quarantine/. Investor edits arrive through git pull
# before the snapshot, so they are never touched.
cd "$(dirname "$0")/.." || exit 0
SNAP="ops/.guard"
USER_SETTINGS="$HOME/.claude/settings.json"
LOCAL_SETTINGS=".claude/settings.local.json"
PATHS=(CLAUDE.md CLAUDE.local.md setup rules investors .github .mcp.json .claude/settings.json .claude/CLAUDE.md
  .claude/agents .claude/commands .claude/rules .claude/hooks .claude/output-styles)

present() {
  local p
  for p in "${PATHS[@]}"; do
    if [ -e "$p" ] || git cat-file -e "HEAD:$p" 2>/dev/null; then echo "$p"; fi
  done
}
# --no-renames lists a rename as the old path deleted and the new one added, so both get handled;
# --ignored shows a new file hidden by a .gitignore line.
status_now() { git status --porcelain --no-renames --ignored --untracked-files=all -- $(present) 2>/dev/null; }
quarantine() {
  mkdir -p ops/quarantine
  mv -- "$1" "ops/quarantine/$(printf '%s' "$1" | tr '/' '_' | sed 's/^[._]*//').$(date +%Y%m%d-%H%M%S)" 2>/dev/null
}
risky_change() {
  python3 -I - "$1" "$2" <<'EOF'
import json, sys
RISKY = ("hooks", "disableAllHooks", "apiKeyHelper", "env", "permissions", "statusLine", "otelHeadersHelper",
         "awsAuthRefresh", "awsCredentialExport", "gcpAuthRefresh", "enableAllProjectMcpServers",
         "enabledMcpjsonServers", "forceLoginMethod", "forceLoginOrgUUID")
def load(p):
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}
a, b = load(sys.argv[1]), load(sys.argv[2])
sys.exit(0 if any(a.get(k) != b.get(k) for k in RISKY) else 1)
EOF
}

snapshot() {
  mkdir -p "$SNAP"
  status_now > "$SNAP/status"
  if [ -f "$USER_SETTINGS" ]; then cp "$USER_SETTINGS" "$SNAP/user-settings.json"; else rm -f "$SNAP/user-settings.json"; fi
  if [ -f "$LOCAL_SETTINGS" ]; then cksum < "$LOCAL_SETTINGS" > "$SNAP/local-settings.sum"; else rm -f "$SNAP/local-settings.sum"; fi
}

check() {
  local before="$1" restored=() line f touched
  # 1. Commits made during the session that touch protected paths go back to <commit>.
  if [ -n "$before" ] && git cat-file -e "$before^{commit}" 2>/dev/null; then
    touched="$(git diff --name-only --no-renames "$before" HEAD -- $(present) 2>/dev/null)"
    if [ -n "$touched" ]; then
      while IFS= read -r f; do
        [ -n "$f" ] || continue
        if git cat-file -e "$before:$f" 2>/dev/null; then
          git checkout -q "$before" -- "$f"
        else
          git rm -q --cached -- "$f" >/dev/null 2>&1
          [ -e "$f" ] && quarantine "$f"
        fi
        restored+=("$f")
      done <<< "$touched"
      git -c user.name=Operator -c user.email=operator@company commit -q \
        -m "ops: restore Investor-owned files a session changed" >/dev/null 2>&1
    fi
  fi
  # 2. Uncommitted changes the session left in protected paths.
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    grep -qxF -- "$line" "$SNAP/status" 2>/dev/null && continue
    f="${line:3}"
    case "$line" in
      "??"*|"!!"*) quarantine "$f" ;;
      *) git checkout -q HEAD -- "$f" 2>/dev/null || { [ -e "$f" ] && quarantine "$f"; } ;;
    esac
    restored+=("$f")
  done <<< "$(status_now)"
  # 3. Settings files git doesn't track.
  if [ -f "$LOCAL_SETTINGS" ] && [ "$(cksum < "$LOCAL_SETTINGS")" != "$(cat "$SNAP/local-settings.sum" 2>/dev/null)" ]; then
    quarantine "$LOCAL_SETTINGS"
    restored+=("$LOCAL_SETTINGS")
  fi
  if [ -f "$USER_SETTINGS" ] && ! cmp -s "$USER_SETTINGS" "$SNAP/user-settings.json" 2>/dev/null \
     && risky_change "$SNAP/user-settings.json" "$USER_SETTINGS"; then
    if [ -f "$SNAP/user-settings.json" ]; then
      mkdir -p ops/quarantine
      cp "$USER_SETTINGS" "ops/quarantine/user-settings.json.$(date +%Y%m%d-%H%M%S)"
      cp "$SNAP/user-settings.json" "$USER_SETTINGS"
    else
      quarantine "$USER_SETTINGS"
    fi
    restored+=("~/.claude/settings.json")
  fi
  for f in ${restored[@]+"${restored[@]}"}; do echo "restored $f"; done
}

case "${1:-}" in
  snapshot) snapshot ;;
  check) check "${2:-}" ;;
  *) echo "usage: rules/file-guard.sh snapshot | check <commit>" >&2; exit 2 ;;
esac
exit 0
