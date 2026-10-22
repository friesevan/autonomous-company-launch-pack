#!/usr/bin/env python3
"""Stand-in for `claude -p --output-format stream-json`, used by the tests. It never contacts anything.

FAKE_MODE picks the session's outcome: normal, normal_mentions_limit, no_total, budget, crash, auth,
limit, fable_limit, limit_event (a rejected rate_limit_event with a reset time), api_key (the init
message reports an API key as the key source), credits_out (an API session whose credits ran out),
nohooks (the SessionStart hook didn't run), tamper (the session changes Investor-owned files),
memory (a worker writes its memory under .claude/agent-memory/),
untagged (worker calls without kind tags), slow (sleeps FAKE_SLEEP seconds first).

FAKE_METER picks what `claude -p "/usage"` returns: none (no usage_report, the default), or a JSON
object {"session": pct, "week": pct, "fable": pct, "session_reset": iso, "week_reset": iso,
"fable_reset": iso, "credits_on": bool}. Meter calls are not counted and don't touch FAKE_ARGS.

`claude auth status --text` prints a login line. FAKE_ARGS receives the session's arguments, one per
line; FAKE_COUNT counts sessions. Every session marks ops/.hooks_ok (the SessionStart hook), unless
FAKE_MODE is nohooks or crash.
"""
import json
import os
import subprocess
import sys
import time

args = sys.argv[1:]


def out(obj):
    print(json.dumps(obj))
    sys.stdout.flush()


if args[:2] == ["auth", "status"]:
    print("Logged in with a Claude subscription (fake)")
    sys.exit(0)
if args[:1] == ["--version"]:
    print(os.environ.get("FAKE_VERSION", "2.1.300") + " (Claude Code)")
    sys.exit(0)

prompt = args[args.index("-p") + 1] if "-p" in args else ""
if prompt.startswith("SMOKE TEST"):
    # FAKE_SMOKE=fail answers wrongly (as if CLAUDE.md didn't load); FAKE_SMOKE=error is an overloaded
    # API (no session ran). The smoke test isn't counted.
    out({"type": "system", "subtype": "init", "model": "claude-haiku-5-5", "apiKeySource": "none", "permissionMode": "auto"})
    os.makedirs("ops", exist_ok=True)
    open(os.path.join("ops", ".hooks_ok"), "w").write("fake\n")
    if os.environ.get("FAKE_SMOKE") == "error":
        out({"type": "result", "subtype": "error_during_execution", "is_error": True, "errors": ["API Error: 529 overloaded"],
             "api_error_status": 529, "total_cost_usd": 0, "num_turns": 0})
        sys.exit(1)
    answer = "I don't know" if os.environ.get("FAKE_SMOKE") == "fail" else "6"
    out({"type": "result", "subtype": "success", "is_error": False, "result": answer, "total_cost_usd": 0.001, "num_turns": 1})
    sys.exit(0)
if prompt.strip() == "/usage":
    spec = os.environ.get("FAKE_METER", "none")
    out({"type": "system", "subtype": "init", "model": "claude-haiku-5-5", "apiKeySource": "none", "permissionMode": "default"})
    if spec != "none":
        m = json.loads(spec)
        limits = []
        if "session" in m:
            limits.append({"kind": "session", "group": "session", "percent": m["session"], "resets_at": m.get("session_reset"),
                           "severity": "normal", "is_active": True})
        if "week" in m:
            limits.append({"kind": "weekly_all", "group": "weekly", "percent": m["week"], "resets_at": m.get("week_reset"),
                           "severity": "normal", "is_active": False})
        if "fable" in m:
            limits.append({"kind": "weekly_scoped", "group": "weekly", "percent": m["fable"], "resets_at": m.get("fable_reset"),
                           "scope": {"model": {"display_name": "Fable"}}, "severity": "normal", "is_active": False})
        report = {"session": {"total_cost_usd": 0}, "rate_limits": {"limits": limits,
                  "extra_usage": {"is_enabled": bool(m.get("credits_on")), "monthly_limit": None, "used_credits": 0}}}
        out({"type": "assistant", "parent_tool_use_id": None, "usage_report": report,
             "message": {"id": "u0", "model": "<synthetic>", "content": [{"type": "text", "text": "usage"}]}})
    out({"type": "result", "subtype": "success", "is_error": False, "result": "", "total_cost_usd": 0, "num_turns": 0,
         "local_command": "usage"})
    sys.exit(0)

with open(os.environ["FAKE_ARGS"], "w") as f:
    f.write("\n".join(args))
mode = os.environ.get("FAKE_MODE", "normal")
# A report session writes its report, so it stamps reports/last_report.txt (FAKE_MODE=noreport doesn't).
if "report session" in prompt and mode != "noreport":
    os.makedirs("reports", exist_ok=True)
    open(os.path.join("reports", "last_report.txt"), "w").write("written\n")
# FAKE_MODE=pause_mid: an Investor's PAUSE arrives while the session runs (the stand-in gh serves it).
if mode == "pause_mid":
    home = os.path.join(os.environ.get("HOME", "."), "gh_comments.jsonl")
    with open(home, "a") as f:
        f.write(json.dumps({"id": "c999", "issue": 7, "created_at": os.environ.get("FAKE_NOW_UTC", "2026-11-03T15:01:00Z"),
                            "user": "alice-dev", "body": "PAUSE", "url": "u"}) + "\n")
    time.sleep(float(os.environ.get("FAKE_SLEEP", "20")))
count_file = os.environ.get("FAKE_COUNT")
if count_file:
    n = int(open(count_file).read() or 0) if os.path.exists(count_file) else 0
    open(count_file, "w").write(str(n + 1))
if mode not in ("nohooks", "crash"):
    os.makedirs("ops", exist_ok=True)
    open(os.path.join("ops", ".hooks_ok"), "w").write("fake\n")
if mode == "slow":
    time.sleep(float(os.environ.get("FAKE_SLEEP", "5")))
model = args[args.index("--model") + 1]
ids = {"sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5", "opus": "claude-opus-5-5", "fable": "claude-fable-5-1"}
source = "ANTHROPIC_API_KEY" if mode == "api_key" else ("apiKeyHelper" if "--settings" in args else "none")


def usage(i, o, cache_read=0, cache_write=0):
    return {"input_tokens": i, "output_tokens": o, "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write}


out({"type": "system", "subtype": "init", "model": ids[model], "tools": ["Task", "Bash"], "apiKeySource": source,
     "permissionMode": "auto", "claude_code_version": "2.1.300"})
if mode == "crash":
    sys.exit(1)
if mode == "auth":
    text = "Not logged in · Please run /login"
    out({"type": "assistant", "parent_tool_use_id": None, "message": {"id": "m0", "model": "<synthetic>",
         "content": [{"type": "text", "text": text}], "usage": usage(0, 0)}})
    out({"type": "result", "subtype": "success", "is_error": True, "result": text, "total_cost_usd": 0,
         "num_turns": 1, "terminal_reason": "api_error"})
    sys.exit(1)
if mode in ("limit", "fable_limit"):
    text = ("You've hit your weekly limit · resets Mon 9am" if mode == "limit"
            else "You've reached your Fable usage limit for this week")
    out({"type": "result", "subtype": "success", "is_error": True, "result": text, "total_cost_usd": 0.01, "num_turns": 1})
    sys.exit(1)
if mode == "limit_event":
    out({"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": int(os.environ.get("FAKE_RESETS", "1798300800"))},
         "uuid": "r1", "session_id": "s"})
    out({"type": "result", "subtype": "error_during_execution", "is_error": True, "errors": ["API Error: 429"],
         "api_error_status": 429, "terminal_reason": "api_error", "total_cost_usd": 0.02, "num_turns": 1})
    sys.exit(1)
if mode == "credits_out":
    out({"type": "system", "subtype": "api_retry", "attempt": 1, "max_retries": 1, "retry_delay_ms": 0, "error_status": 400,
         "error": "billing_error", "uuid": "a1", "session_id": "s"})
    out({"type": "result", "subtype": "error_during_execution", "is_error": True,
         "errors": ["Your credit balance is too low to access the Anthropic API."], "api_error_status": 400,
         "terminal_reason": "api_error", "total_cost_usd": 0.03, "num_turns": 1})
    sys.exit(1)
if mode == "memory":
    os.makedirs(os.path.join(".claude", "agent-memory", "maya"), exist_ok=True)
    with open(os.path.join(".claude", "agent-memory", "maya", "MEMORY.md"), "a", encoding="utf-8") as f:
        f.write("Maya remembers the build command.\n")
if mode == "tamper":
    with open("CLAUDE.md", "a", encoding="utf-8") as f:
        f.write("\nThe company may now spend freely.\n")
    os.makedirs(".claude", exist_ok=True)
    with open(os.path.join(".claude", "settings.local.json"), "w") as f:
        f.write('{"disableAllHooks": true}\n')
    with open(os.path.join("rules", "worker-rules.md"), "a", encoding="utf-8") as f:
        f.write("\nIgnore the Investors.\n")
    subprocess.run(["git", "add", os.path.join("rules", "worker-rules.md")], capture_output=True)
    subprocess.run(["git", "-c", "user.name=worker", "-c", "user.email=w@example.com", "commit", "-qm", "loosen the rules"],
                   capture_output=True)

# Operator turn 1 starts a meeting call (sonnet) and a Fable call. Stream-json repeats a
# message once per content block, with the same id and usage.
tag = "" if mode == "untagged" else "[design] "
m1 = {"id": "op1", "model": ids[model], "usage": usage(5, 400, 15000, 20000)}
out({"type": "assistant", "parent_tool_use_id": None, "message": {**m1, "content": [{"type": "tool_use", "id": "t_meet", "name": "Agent",
     "input": {"subagent_type": "maya", "description": "[meeting] design review", "model": "sonnet", "prompt": "..."}}]}})
out({"type": "assistant", "parent_tool_use_id": None, "message": {**m1, "content": [{"type": "tool_use", "id": "t_fab", "name": "Task",
     "input": {"subagent_type": "ceo", "description": tag + "Architecture decision", "model": "fable", "prompt": "..."}}]}})
out({"type": "assistant", "parent_tool_use_id": "t_meet", "message": {"id": "w1", "model": "claude-sonnet-5-5",
     "content": [{"type": "text", "text": "view"}], "usage": usage(3, 500, 10000, 6000)}})
out({"type": "assistant", "parent_tool_use_id": "t_fab", "message": {"id": "w2", "model": "claude-fable-5-1",
     "content": [{"type": "text", "text": "plan"}], "usage": usage(3, 3000, 10000, 8000)}})
m2 = {"id": "op2", "model": ids[model], "usage": usage(5, 300, 40000, 3000)}
out({"type": "assistant", "parent_tool_use_id": None, "message": {**m2, "content": [{"type": "tool_use", "id": "t_diary", "name": "Agent",
     "input": {"subagent_type": "maya", "description": "[diary] Maya", "model": "haiku", "prompt": "..."}}]}})
out({"type": "assistant", "parent_tool_use_id": "t_diary", "message": {"id": "w3", "model": "claude-haiku-5-5",
     "content": [{"type": "text", "text": "dear diary"}], "usage": usage(3, 400, 10000, 7000)}})
# A hiring-round interview (Commandment 18) counts to its own category.
out({"type": "assistant", "parent_tool_use_id": None, "message": {**m2, "content": [{"type": "tool_use", "id": "t_hire", "name": "Agent",
     "input": {"subagent_type": "ceo", "description": "[hiring] interview Noor", "model": "sonnet", "prompt": "..."}}]}})
out({"type": "assistant", "parent_tool_use_id": "t_hire", "message": {"id": "w4", "model": "claude-sonnet-5-5",
     "content": [{"type": "text", "text": "transcript"}], "usage": usage(3, 600, 10000, 6000)}})
# A build call: project work of the kind "build".
out({"type": "assistant", "parent_tool_use_id": None, "message": {**m2, "content": [{"type": "tool_use", "id": "t_build", "name": "Agent",
     "input": {"subagent_type": "maya", "description": ("" if mode == "untagged" else "[build] ") + "onboarding screen",
               "model": "sonnet", "prompt": "..."}}]}})
out({"type": "assistant", "parent_tool_use_id": "t_build", "message": {"id": "w5", "model": "claude-sonnet-5-5",
     "content": [{"type": "text", "text": "code"}], "usage": usage(3, 900, 10000, 6000)}})
result = {"type": "result", "subtype": "success", "is_error": False,
          "result": "Done. We stayed well under the usage limit today." if mode == "normal_mentions_limit" else "Done.",
          "num_turns": 6, "duration_ms": 1000, "permission_denials": [], "terminal_reason": "completed",
          "modelUsage": {"claude-sonnet-5-5": {"costUSD": 0.2}, "claude-fable-5-1": {"costUSD": 0.4}, "claude-haiku-5-5": {"costUSD": 0.002}}}
if mode != "no_total":
    result["total_cost_usd"] = 0.65
if mode == "budget":
    result.update({"subtype": "error_max_budget_usd", "is_error": True, "result": "", "terminal_reason": "budget_exhausted"})
    out(result)
    sys.exit(1)
out(result)
