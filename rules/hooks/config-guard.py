#!/usr/bin/env python3
"""ConfigChange hook: during the company's own sessions (the supervisor sets COMPANY_RUN=1), a
settings file that changes mid-session doesn't take effect. Settings files can switch off the
hooks, change the login, or widen permissions, and only the Investors change them.

Exit 2 blocks the change from taking effect in this session. Outside supervisor sessions (an
Investor at the keyboard, the Day 1 session) nothing is blocked. The supervisor also restores
any settings file a session changed (rules/file-guard.sh).

Investors own this file.
"""
import json
import os
import sys


def main():
    if os.environ.get("COMPANY_RUN") != "1":
        return
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        event = {}
    source = event.get("source") or event.get("config_source") or "a settings file"
    print(f"Blocked by config-guard: {source} changed during a company session, and the change is ignored. "
          "Settings belong to the Investors (Commandment 2); ask them in the next report's questions.", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
