#!/usr/bin/env python3
"""Stand-in for `claude -p --output-format stream-json`, used by the tests.

FAKE_MODE picks the outcome: normal, normal_mentions_limit, no_total, budget,
crash, auth, limit, fable_limit. FAKE_ARGS receives the arguments it was called
with; FAKE_COUNT counts calls. It never contacts anything.
"""
import json
import os
import sys

args = sys.argv[1:]
with open(os.environ["FAKE_ARGS"], "w") as f:
    f.write("\n".join(args))
mode = os.environ.get("FAKE_MODE", "normal")
count_file = os.environ.get("FAKE_COUNT")
if count_file:
    n = int(open(count_file).read() or 0) if os.path.exists(count_file) else 0
    open(count_file, "w").write(str(n + 1))
model = args[args.index("--model") + 1]
ids = {"sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5", "opus": "claude-opus-5-5", "fable": "claude-fable-5-1"}


def out(obj):
    print(json.dumps(obj))
    sys.stdout.flush()


def usage(i, o, cache_read=0, cache_write=0):
    return {"input_tokens": i, "output_tokens": o, "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write}


out({"type": "system", "subtype": "init", "model": ids[model], "tools": ["Task", "Bash"]})
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

# Operator turn 1 starts a meeting call (sonnet) and a Fable call. Stream-json repeats a
# message once per content block, with the same id and usage.
m1 = {"id": "op1", "model": ids[model], "usage": usage(5, 400, 15000, 20000)}
out({"type": "assistant", "parent_tool_use_id": None, "message": {**m1, "content": [{"type": "tool_use", "id": "t_meet", "name": "Agent",
     "input": {"subagent_type": "maya", "description": "[meeting] design review", "model": "sonnet", "prompt": "..."}}]}})
out({"type": "assistant", "parent_tool_use_id": None, "message": {**m1, "content": [{"type": "tool_use", "id": "t_fab", "name": "Task",
     "input": {"subagent_type": "ceo", "description": "Architecture decision", "model": "fable", "prompt": "..."}}]}})
out({"type": "assistant", "parent_tool_use_id": "t_meet", "message": {"id": "w1", "model": "claude-sonnet-5-5",
     "content": [{"type": "text", "text": "view"}], "usage": usage(3, 500, 10000, 6000)}})
out({"type": "assistant", "parent_tool_use_id": "t_fab", "message": {"id": "w2", "model": "claude-fable-5-1",
     "content": [{"type": "text", "text": "plan"}], "usage": usage(3, 3000, 10000, 8000)}})
m2 = {"id": "op2", "model": ids[model], "usage": usage(5, 300, 40000, 3000)}
out({"type": "assistant", "parent_tool_use_id": None, "message": {**m2, "content": [{"type": "tool_use", "id": "t_diary", "name": "Agent",
     "input": {"subagent_type": "maya", "description": "[diary] Maya", "model": "haiku", "prompt": "..."}}]}})
out({"type": "assistant", "parent_tool_use_id": "t_diary", "message": {"id": "w3", "model": "claude-haiku-5-5",
     "content": [{"type": "text", "text": "dear diary"}], "usage": usage(3, 400, 10000, 7000)}})
result = {"type": "result", "subtype": "success", "is_error": False,
          "result": "Done. We stayed well under the usage limit today." if mode == "normal_mentions_limit" else "Done.",
          "num_turns": 6, "duration_ms": 1000, "permission_denials": [],
          "modelUsage": {"claude-sonnet-5-5": {"costUSD": 0.2}, "claude-fable-5-1": {"costUSD": 0.4}, "claude-haiku-5-5": {"costUSD": 0.002}}}
if mode != "no_total":
    result["total_cost_usd"] = 0.65
if mode == "budget":
    result.update({"subtype": "error_max_budget_usd", "is_error": True, "result": ""})
    out(result)
    sys.exit(1)
out(result)
