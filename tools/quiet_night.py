#!/usr/bin/env python3
"""Was anything worth reporting since a timestamp? Used to skip the 6 a.m. report.

  python3 tools/quiet_night.py --since 2026-11-03T18:05:00-05:00

Prints JSON: {"quiet": true|false, "reasons": [...]}. Checks, without Claude:
commits that aren't the supervisor's own "ops:" commits, new lines in
log/events.jsonl, a pending Investor message, and failed runs. Company-owned.
"""
import argparse
import datetime as dt
import glob
import json
import os
import subprocess
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = ZoneInfo("America/New_York")


def parse(value):
    d = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--since", required=True, help="ISO timestamp of the last evening report")
    args = p.parse_args()
    try:
        since = parse(args.since)
    except (ValueError, AttributeError):
        print(json.dumps({"quiet": False, "reasons": ["no reference time"]}))
        return
    reasons = []

    try:
        out = subprocess.run(["git", "log", f"--since={since.isoformat()}", "--format=%s", "--no-merges"],
                             capture_output=True, text=True, cwd=ROOT, timeout=30).stdout
        commits = [s for s in out.splitlines() if s and not s.startswith("ops:")]
        if commits:
            reasons.append(f"{len(commits)} commit(s)")
    except Exception:
        pass

    events = os.path.join(ROOT, "log", "events.jsonl")
    if os.path.exists(events):
        n = 0
        with open(events, encoding="utf-8") as f:
            for line in f:
                try:
                    t = json.loads(line).get("time")
                    if t and parse(t) > since:
                        n += 1
                except (json.JSONDecodeError, ValueError):
                    continue
        if n:
            reasons.append(f"{n} event(s)")

    if os.path.exists(os.path.join(ROOT, "ops", "inbox_pending")):
        reasons.append("Investor message pending")

    failed = 0
    for path in glob.glob(os.path.join(ROOT, "ops", "runs", "*.json")):
        if dt.datetime.fromtimestamp(os.path.getmtime(path), TZ) <= since:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                r = json.load(f)
            if r.get("is_error"):
                failed += 1
        except (json.JSONDecodeError, OSError):
            continue
    if failed:
        reasons.append(f"{failed} failed run(s)")

    print(json.dumps({"quiet": not reasons, "reasons": reasons}))


if __name__ == "__main__":
    main()
