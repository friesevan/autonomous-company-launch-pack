#!/usr/bin/env python3
"""Assemble every active worker into ops/agents.json for the --agents flag.

Each worker's persona lives in personnel/agents/<slug>.md (outside .claude/,
which Claude Code protects from unattended writes). This script combines each
persona with the worker rules and the amendments in effect, so every worker
always runs on the current rules. The supervisor runs it before every session.

Persona file format:

    ---
    description: Maya, iOS engineer. Use for Swift and SwiftUI work.
    maxTurns: 40
    effort: medium
    tools: Read, Grep, Glob, Bash
    ---
    # Maya
    <persona, career goal, current goals...>

Only `description` is required. `tools` and `disallowedTools` are comma-separated
lists (brackets optional); Claude Code needs them as JSON arrays, so they are
written as arrays. Files in personnel/agents/former/ are skipped,
except with --include-former, which the supervisor passes on Day 30 so former
workers can write their Final Report testimonies.
The output is written only when it changes, so the prompt cache stays warm.

Models are chosen per task, not per worker (Tenet 6): the Operator names the
model and effort on every Agent call. Each worker's fallback is sonnet at
medium effort, and a persona cannot set its own model, so a call that forgets
to name one never runs on Fable or Opus by accident.

Investors own this file.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENTS_DIR = os.path.join(ROOT, "personnel", "agents")
RULES = os.path.join(ROOT, "rules", "worker-rules.md")
AMENDMENTS = os.path.join(ROOT, "amendments.md")
OUT = os.path.join(ROOT, "ops", "agents.json")

ALLOWED_KEYS = {"description", "maxTurns", "effort", "tools", "disallowedTools"}
LIST_KEYS = {"tools", "disallowedTools"}
DEFAULT_MODEL = "sonnet"
DEFAULT_EFFORT = "medium"


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def parse(path):
    text = read(path)
    meta, body = {}, text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = parts[2].lstrip("\n")
    return meta, body.rstrip() + "\n"


def as_list(value):
    """'Read, Grep' or '[Read, "Grep"]' -> ['Read', 'Grep']."""
    return [t.strip().strip("'\"") for t in value.strip().strip("[]").split(",") if t.strip().strip("'\"")]


def amendments_block():
    if not os.path.exists(AMENDMENTS):
        return ""
    entries, cur, in_code = [], None, False
    for line in read(AMENDMENTS).splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if line.startswith("## "):
            if cur:
                entries.append(cur)
            cur = [line]
        elif cur is not None:
            cur.append(line)
    if cur:
        entries.append(cur)
    if not entries:
        return ""
    joined = "\n\n".join("\n".join(e).strip() for e in entries)
    return "\n\n# Amendments in effect\n\nThese override the Worker Rules and the Commandments.\n\n" + joined + "\n"


FORMER_NOTE = ("\n\n# You have left the company\n\nYou are writing your testimony for the Final Report "
               "(Commandment 48). Your archived memory is beside your persona in personnel/agents/former/; "
               "read it first. Write only from what the records show.\n")


def collect(directory, rules, amend, former=False):
    agents = {}
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not name.endswith(".md") or not os.path.isfile(path):
            continue
        slug = name[:-3]
        meta, persona = parse(path)
        if not meta.get("description"):
            print(f"Skipping {name}: no description in its header.", file=sys.stderr)
            continue
        entry = {
            "description": ("Former worker. " if former else "") + meta["description"],
            "prompt": persona + "\n" + rules + amend + (FORMER_NOTE if former else ""),
            "memory": "project",
            "omitClaudeMd": True,
            "maxTurns": int(meta.get("maxTurns", 40)),
            "model": DEFAULT_MODEL,
            "effort": DEFAULT_EFFORT,
        }
        for key in sorted(ALLOWED_KEYS - {"description", "maxTurns"}):
            if key in meta:
                entry[key] = as_list(meta[key]) if key in LIST_KEYS else meta[key]
        agents[slug] = entry
    return agents


def main():
    if not os.path.isdir(AGENTS_DIR):
        print("No personnel/agents/ directory yet.", file=sys.stderr)
        return 1
    rules = read(RULES).rstrip() + "\n"
    amend = amendments_block()
    agents = collect(AGENTS_DIR, rules, amend)
    former_dir = os.path.join(AGENTS_DIR, "former")
    if "--include-former" in sys.argv[1:] and os.path.isdir(former_dir):
        for slug, entry in collect(former_dir, rules, amend, former=True).items():
            agents.setdefault(slug, entry)
    payload = json.dumps(agents, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    old = read(OUT) if os.path.exists(OUT) else None
    if payload != old:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"Wrote {len(agents)} worker(s) to ops/agents.json")
    else:
        print(f"ops/agents.json unchanged ({len(agents)} worker(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
