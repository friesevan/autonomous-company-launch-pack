#!/bin/bash
# The security posture check, run by the supervisor every tick (no Claude). Investors own this file.
#
# Reads the firewall, FileVault, System Integrity Protection, Gatekeeper, and automatic security
# updates; keeps the current state in ops/posture.json and every change in log/posture.jsonl;
# and prints "off <name>" when a protection that any earlier check saw on turns off, for the
# supervisor to raise as an Emergency. A protection that was never on is reported in the
# posture file and the facts for the next report, not as an Emergency. Silent outside macOS.
cd "$(dirname "$0")/.." || exit 0
[ "$(uname -s)" = Darwin ] || exit 0
state() {
  case "$1" in
    *[Dd]isabled*|*"is Off"*|*"State = 0"*) echo off ;;
    *[Ee]nabled*|*"is On"*|*"State = 1"*|*"State = 2"*) echo on ;;
    *) echo unknown ;;
  esac
}
fw="$(state "$(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null)")"
fv="$(state "$(fdesetup status 2>/dev/null)")"
sip="$(state "$(csrutil status 2>/dev/null)")"
case "$(spctl --status 2>/dev/null)" in
  *"assessments enabled"*) gk=on ;;
  *"assessments disabled"*) gk=off ;;
  *) gk=unknown ;;
esac
case "$(defaults read /Library/Preferences/com.apple.SoftwareUpdate CriticalUpdateInstall 2>/dev/null)" in
  1) su=on ;;
  0) su=off ;;
  *) su=unknown ;;
esac
python3 -I - "$fw" "$fv" "$sip" "$gk" "$su" <<'EOF'
import datetime, json, os, sys
names = ["firewall", "filevault", "sip", "gatekeeper", "security_updates"]
cur = dict(zip(names, sys.argv[1:]))
path = os.path.join("ops", "posture.json")
try:
    with open(path, encoding="utf-8") as f:
        prev = json.load(f)
except (OSError, ValueError):
    prev = {}
# A protection counts as "was on" if any check ever saw it on, so a step through "unknown" or a
# missing ops/posture.json doesn't hide the change.
if not isinstance(prev, dict):
    prev = {}
ever = set(prev.get("ever_on") or []) | {n for n in names if prev.get(n) == "on"}
try:
    with open(os.path.join("log", "posture.jsonl"), encoding="utf-8") as f:
        for line in f:
            try:
                ever |= {n for n, v in json.loads(line).items() if v == "on"}
            except (ValueError, AttributeError):
                pass
except OSError:
    pass
for n in names:
    if n in ever and cur[n] == "off" and prev.get(n) != "off":
        print("off " + n)
ever = (ever | {n for n in names if cur[n] == "on"}) & set(names)
if {n: prev.get(n) for n in names} != cur or sorted(ever) != sorted(prev.get("ever_on") or []):
    os.makedirs("log", exist_ok=True)
    with open(os.path.join("log", "posture.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), **cur}) + "\n")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({**cur, "ever_on": sorted(ever)}, f, indent=1)
        f.write("\n")
EOF
exit 0
