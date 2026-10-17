#!/usr/bin/env python3
"""The event log: one JSON line per notable event in log/events.jsonl.

  python3 tools/events.py add --worker maya --type commit --summary "Onboarding screen done" --link app/...
  python3 tools/events.py since 2026-11-03T18:00:00-05:00
  python3 tools/events.py tail 20

Types: decision, commit, build, test, sale, review, hire, departure, mood, message,
report, amendment, other. Reports and the quiet-night check read this file instead
of the whole repository. Company-owned.
"""
import argparse
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "log", "events.jsonl")
TZ = ZoneInfo("America/New_York")


def read():
    if not os.path.exists(PATH):
        return []
    with open(PATH, encoding="utf-8") as f:
        out = []
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--worker", required=True, help="first name, or 'operator'")
    a.add_argument("--type", required=True)
    a.add_argument("--summary", required=True)
    a.add_argument("--link", default="")
    s = sub.add_parser("since"); s.add_argument("iso")
    t = sub.add_parser("tail"); t.add_argument("n", type=int, nargs="?", default=20)
    args = p.parse_args()

    if args.cmd == "add":
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        entry = {"time": dt.datetime.now(TZ).isoformat(timespec="seconds"), "worker": args.worker,
                 "type": args.type, "summary": args.summary.strip()[:300], "link": args.link}
        with open(PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(json.dumps(entry, ensure_ascii=False))
    elif args.cmd == "since":
        since = dt.datetime.fromisoformat(args.iso.replace("Z", "+00:00"))
        if since.tzinfo is None:
            since = since.replace(tzinfo=TZ)
        for e in read():
            try:
                if dt.datetime.fromisoformat(e["time"]) > since:
                    print(json.dumps(e, ensure_ascii=False))
            except (KeyError, ValueError):
                continue
    else:
        for e in read()[-args.n:]:
            print(json.dumps(e, ensure_ascii=False))


if __name__ == "__main__":
    main()
