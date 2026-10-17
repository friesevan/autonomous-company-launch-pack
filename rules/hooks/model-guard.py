#!/usr/bin/env python3
"""PreToolUse hook for the Agent tool (called Task in older releases).

Enforces the model rules in Tenet 6 when a session starts a worker:
  - Fable only while the week's Fable allowance lasts (ops/run.json: fable_ok).
    Past the allowance the plan bills paid usage credits, which the company never uses.
  - Diaries and small talk ([diary] or [talk] descriptions) run on haiku, and stop
    once their weekly cap is reached (ops/run.json: over_cap).

Exit 2 refuses the call and shows the reason to the session, which can retry
correctly. Anything unexpected (no run.json, unreadable input) allows the call.

Investors own this file.
"""
import json
import os
import sys

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def refuse(reason):
    print(reason, file=sys.stderr)
    sys.exit(2)


def main():
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    if event.get("tool_name") not in ("Agent", "Task"):
        return
    tool_input = event.get("tool_input") or {}
    model = str(tool_input.get("model") or "").lower()
    description = str(tool_input.get("description") or "").strip().lower()
    try:
        with open(os.path.join(ROOT, "ops", "run.json"), encoding="utf-8") as f:
            run = json.load(f)
    except (OSError, json.JSONDecodeError):
        run = {}

    if ("fable" in model or model == "best") and run.get("fable_ok") is False:
        refuse("Fable is not available: this week's Fable allowance is used up or Fable is paused "
               "(ops/run.json). Start this worker with model \"opus\" and effort \"high\" instead.")
    if description.startswith(("[diary]", "[talk]")):
        if "talk" in (run.get("over_cap") or []):
            refuse("This week's small-talk and diary budget is spent (Commandment 25). Skip it.")
        if model != "haiku":
            refuse("Diaries and small talk run on Haiku (Commandment 25). Start this call again "
                   "with model \"haiku\" and effort \"low\".")


if __name__ == "__main__":
    main()
