#!/bin/bash
# One tiny real Claude session with the supervisor's own flags, to check what the run loop depends
# on: the Claude Code version, the subscription login (not an API key), auto mode, the company's
# hooks (the SessionStart mark), and CLAUDE.md (the model answers from it with no tools). About a
# cent of Haiku usage. The Investors run it from Terminal before Day 1; the supervisor runs it
# again whenever the Claude Code version changes, and pauses the company if it fails.
#   tools/smoke_test.sh     exit 0 when every check passes; 1 when a check fails, with a fix for each;
#                           2 when no session could run at all (a network blip, an overloaded API):
#                           nothing is known yet, so the supervisor tries again at the next tick
# Company-owned.
set -u
cd "$(dirname "$0")/.." || exit 1
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
MIN_VERSION="2.1.293"
unset CLAUDECODE ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
export DISABLE_AUTOUPDATER=1 CLAUDE_CODE_STARTUP_FAILURE_RESULTS=1   # the same environment as the supervisor
mkdir -p ops/runs
OUT="ops/runs/smoke-$(date +%Y%m%d-%H%M%S).jsonl"
VERSION="$("$CLAUDE_BIN" --version 2>/dev/null | head -1)"
rm -f ops/.hooks_ok
"$CLAUDE_BIN" -p 'SMOKE TEST. Using only what you were given at startup, reply with only the number of the Commandment titled "Break the law." in CLAUDE.md.' \
  --model haiku --effort low --max-turns 2 --max-budget-usd 0.25 --tools "" \
  --permission-mode auto --permission-prompts none --forward-subagent-text \
  --no-session-persistence --output-format stream-json --verbose < /dev/null > "$OUT" 2>&1
code=$?
python3 -I - "$OUT" "$code" "$VERSION" "$MIN_VERSION" <<'EOF'
import json, os, re, sys
path, code, version, minimum = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
objs = []
with open(path, encoding="utf-8", errors="replace") as f:
    for line in f:
        line = line.strip()
        if line.startswith("{"):
            try:
                objs.append(json.loads(line))
            except ValueError:
                pass
init = next((o for o in objs if o.get("type") == "system" and o.get("subtype") == "init"), {})
result = next((o for o in reversed(objs) if o.get("type") == "result"), {})
answer = str(result.get("result") or "").strip()
nums = lambda v: tuple(int(x) for x in re.findall(r"\d+", v)[:3])
ran = bool(result) and not result.get("is_error") and code == 0
said = " ".join([answer] + [str(e) for e in result.get("errors") or []])
logged_out = re.search(r"not logged in|run /login|authentication_failed|invalid api key", said, re.I) is not None
version_ok = bool(version) and nums(version) >= nums(minimum)
if not ran and not logged_out and version_ok:
    print("INCONCLUSIVE no session could run (exit %d), so nothing was checked; output: %s" % (code, path))
    sys.exit(2)
checks = [
    (version_ok, f"Claude Code {version or 'not found'} (needs {minimum} or later)",
     "install or update Claude Code: curl -fsSL https://claude.ai/install.sh | bash"),
    (ran, "a session ran",
     "run `claude` in Terminal in this folder, type /login, and sign in with the company's Claude account; output: " + path),
    (init.get("apiKeySource") in (None, "", "none", "oauth"), f"billed to the subscription (key source: {init.get('apiKeySource')})",
     "remove ANTHROPIC_API_KEY and any apiKeyHelper from the shell profile, ~/.claude/settings.json, and the launchd job"),
    (init.get("permissionMode") == "auto", f"auto mode (got {init.get('permissionMode')})",
     "auto mode must be available to this account and Claude Code version; run `claude doctor`"),
    (os.path.exists(os.path.join("ops", ".hooks_ok")), "the company's hooks ran",
     "Claude Code skipped the project hooks: run `claude doctor`, and check that .claude/settings.json is intact"),
    (re.search(r"\b6\b", answer) is not None, "CLAUDE.md loaded (answer: " + repr(answer[:40]) + ")",
     "Claude Code didn't load CLAUDE.md: it may be running in --bare mode; check `claude doctor`"),
]
for ok, name, fix in checks:
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "\n     fix: " + fix))
sys.exit(0 if all(ok for ok, _, _ in checks) else 1)
EOF
