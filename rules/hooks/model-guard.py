#!/usr/bin/env python3
"""PreToolUse hook for the Agent tool (called Task in older releases).

Enforces the model rules in Tenet 6 when a session starts a worker:
  - Fable only while the week's Fable allowance lasts (ops/run.json: fable_ok).
    Past the allowance the plan bills paid usage credits, which the company never uses.
  - Never Fable in a session billed to the plan's API credits (ops/run.json: billing "api").
  - Diaries and small talk ([diary] or [talk] descriptions) run on haiku, and stop
    once their weekly cap is reached (ops/run.json: over_cap).
  - In the company's own work and inbox sessions (COMPANY_RUN=1), a product worker call
    names its kind of work, so the usage page can say where the product's usage goes:
    the description starts with [research], [design], [build], [test], [release],
    [review], [tools], or [plan]. A call with a cap tag ([meeting], [hiring], [diary],
    [talk], [report], [testimony]) needs no kind tag.

Exit 2 refuses the call and shows the reason to the session, which can retry
correctly. Anything unexpected (no run.json, unreadable input) allows the call.

Investors own this file.
"""
import json
import os
import re
import sys

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAP_TAGS = ("meeting", "hiring", "diary", "talk", "report", "testimony")
KINDS = ("research", "design", "build", "test", "release", "review", "tools", "plan")


def refuse(reason):
    print(reason, file=sys.stderr)
    sys.exit(2)


def tags(description):
    lead = re.match(r"^((?:\[[a-z]+\]\s*)+)", description)
    return re.findall(r"\[([a-z]+)\]", lead.group(1)) if lead else []


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

    # The supervisor also passes the billing and the Fable allowance in the environment, so the guard
    # still knows them if ops/run.json goes missing; in a company session that knows neither, Fable
    # is refused rather than allowed.
    company = os.environ.get("COMPANY_RUN") == "1"
    billing = os.environ.get("COMPANY_BILLING") or run.get("billing")
    env_ok = os.environ.get("COMPANY_FABLE_OK")
    fable_ok = (env_ok.strip().lower() == "true") if env_ok else run.get("fable_ok")
    wants_fable = "fable" in model or model == "best"
    if wants_fable and billing == "api":
        refuse("Fable never runs on API credits (Tenet 6), and this session is billed to them while the plan's "
               "limit resets. Start this worker with model \"opus\" and effort \"high\" instead.")
    if wants_fable and (fable_ok is False or (company and fable_ok is None)):
        refuse("Fable is not available: this week's Fable allowance is used up or Fable is paused "
               "(ops/run.json). Start this worker with model \"opus\" and effort \"high\" instead.")
    if description.startswith(("[diary]", "[talk]")):
        if "talk" in (run.get("over_cap") or []):
            refuse("This week's small-talk and diary budget is spent (Commandment 25). Skip it.")
        if model != "haiku":
            refuse("Diaries and small talk run on Haiku (Commandment 25). Start this call again "
                   "with model \"haiku\" and effort \"low\".")
    found = tags(description)
    if (os.environ.get("COMPANY_RUN") == "1" and run.get("run") in ("work", "inbox")
            and not any(t in CAP_TAGS for t in found) and not any(t in KINDS for t in found)):
        refuse("Start the description with the kind of work, so the usage page can show where the product's "
               "usage goes: [research], [design], [build], [test], [release], [review], [tools], or [plan], "
               "for example \"[build] onboarding screen\". Overhead calls start with their cap tag instead "
               "([meeting], [hiring], [diary], [talk], [report], [testimony]).")


if __name__ == "__main__":
    main()
