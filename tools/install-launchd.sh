#!/bin/bash
# Installs the LaunchAgent that runs tools/supervisor.sh every 15 minutes in the
# company's macOS account. No sudo. Run again after moving the repository.
#   tools/install-launchd.sh              install or refresh
#   tools/install-launchd.sh --uninstall  stop the loop and remove the agent
#   tools/install-launchd.sh --render     print the plist that would be installed
# Company-owned.
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
LABEL="com.company.supervisor"
TEMPLATE="ops/launchd/$LABEL.plist.template"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SAFE_PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
render() { sed -e "s#__REPO__#$ROOT#g" -e "s#__PATH__#$SAFE_PATH#g" "$TEMPLATE"; }
case "${1:-}" in
  --render) render; exit 0 ;;
  --uninstall)
    launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null
    rm -f "$PLIST"; echo "removed $PLIST"; exit 0 ;;
esac
mkdir -p "$HOME/Library/LaunchAgents" ops/runs
render > "$PLIST"
plutil -lint "$PLIST" >/dev/null || { echo "plist invalid"; exit 1; }
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null
launchctl bootstrap "gui/$(id -u)" "$PLIST" && echo "installed $PLIST (every 15 min)"
