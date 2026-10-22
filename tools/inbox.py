#!/usr/bin/env python3
"""Investor messages, without Claude: what arrived, what is waiting, and receipts. Company-owned.

  python3 tools/inbox.py poll [--now ISO]
      Every tick (the supervisor): fetch the issues and comments the Investors created
      (investors/allowlist.md, case-insensitive) since the last poll, skip the company's own
      account, and keep them in ops/inbox/pending.json; ops/inbox_pending exists while any wait.
      A message whose first word is PAUSE or STOP writes ops/paused, and nothing runs until a
      message whose first word is RESUME, which removes it. Both get a confirmation at once.
  python3 tools/inbox.py list
      What a session reads: the waiting messages, grouped by issue, oldest first.
  python3 tools/inbox.py done <id>... | --all
      A session marks messages handled once it has replied to them.
  python3 tools/inbox.py receipt --decision ops/last_decision.json [--now ISO]
      The supervisor, when no session will reply this tick: one receipt comment per issue for
      messages from the last 24 hours that haven't had one ("Received (9:42 PM). ...").

Messages are counted by when they were created, so the company's own replies, which only
update an issue, never bring an old message back. Edits to an old comment aren't seen: a new
comment is. State lives in ops/inbox/ (committed, so a reinstall doesn't replay old messages).
Silent when gh isn't installed or logged in.
"""
import argparse
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "ops", "inbox")
STATE = os.path.join(DIR, "state.json")
PENDING = os.path.join(DIR, "pending.json")
MARK = os.path.join(ROOT, "ops", "inbox_pending")
PAUSED = os.path.join(ROOT, "ops", "paused")
ALLOW = os.path.join(ROOT, "investors", "allowlist.md")
OLD_STATE = os.path.join(ROOT, "ops", "state.json")
EVENTS = os.path.join(ROOT, "tools", "events.py")
TZ = ZoneInfo("America/New_York")
MESSAGES = os.path.join(DIR, "messages.jsonl")
OVERLAP = dt.timedelta(minutes=10)
RECEIPT_WINDOW = dt.timedelta(hours=24)
COMMAND_WINDOW = dt.timedelta(hours=2)
COMMAND_RE = re.compile(r"^[\s>*_#`~-]*(pause|stop|resume)\b[\s.!:,-]*", re.I)
ISSUE_JQ = ('.[] | select(.pull_request | not) | {id: ("i" + (.number | tostring)), issue: .number, created_at, '
            'user: .user.login, body, url: .html_url, title} | @json')
COMMENT_JQ = ('.[] | {id: ("c" + (.id | tostring)), issue: (.issue_url | split("/") | last | tonumber), created_at, '
              'user: .user.login, body, url: .html_url} | @json')


def parse_time(value):
    if not value:
        return dt.datetime.now(TZ)
    d = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)
    return d.astimezone(TZ)


def utc(d):
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clock(iso):
    d = parse_time(iso)
    return f"{d:%a} {int(d.strftime('%I'))}:{d:%M %p} ET"


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def gh(*args):
    # GH_CMD overrides the gh command, as CLAUDE_BIN does for claude (tests on machines that can't run a script as gh).
    base = shlex.split(os.environ.get("GH_CMD") or "gh")
    try:
        out = subprocess.run([*base, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, cwd=ROOT)
        return out.returncode, out.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def have_gh():
    return gh("auth", "status")[0] == 0


def repo():
    r = os.environ.get("COMPANY_REPO")
    if r:
        return r
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except OSError:
        return None
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def allowlist():
    try:
        with open(ALLOW, encoding="utf-8") as f:
            lines = f.read().replace("\r", "").splitlines()
    except OSError:
        return set()
    names = set()
    for line in lines:
        name = line.strip().lstrip("@").strip()
        if re.fullmatch(r"[A-Za-z0-9-]{1,39}", name):
            names.add(name.lower())
    return names


def my_login(state, now):
    cached, at = state.get("me"), state.get("me_at")
    if cached and at and now - parse_time(at) < dt.timedelta(hours=24):
        return cached
    code, out = gh("api", "user", "-q", ".login")
    if code == 0 and out.strip():
        state["me"], state["me_at"] = out.strip(), now.isoformat()
        return state["me"]
    return cached


def first_cursor():
    legacy = load_json(OLD_STATE, {}).get("inbox_last_check")
    return legacy or "1970-01-01T00:00:00Z"


def fetch(r, since):
    """Every issue and comment updated since `since`; None unless both reads succeed, so the cursor
    never moves past a gap."""
    items = []
    for path, jq in ((f"repos/{r}/issues", ISSUE_JQ), (f"repos/{r}/issues/comments", COMMENT_JQ)):
        extra = ["-f", "state=all"] if path.endswith("/issues") else []
        code, out = gh("api", "-X", "GET", path, "-f", f"since={since}", "-f", "per_page=100", *extra, "--paginate", "--jq", jq)
        if code != 0:
            return None
        for line in out.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                it = json.loads(line)
            except ValueError:
                continue
            if isinstance(it, dict) and it.get("id") and it.get("created_at"):
                items.append(it)
    return items


def log_event(summary, link):
    try:
        subprocess.run([sys.executable, "-I", EVENTS, "add", "--worker", "operator", "--type", "message",
                        "--summary", summary, "--link", link or ""], capture_output=True, timeout=30, cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired):
        pass


def comment(r, issue, body):
    return gh("issue", "comment", str(issue), "--repo", r, "--body", body)[0] == 0


def update_mark(pending):
    if pending:
        open(MARK, "a").close()
    elif os.path.exists(MARK):
        os.remove(MARK)


def command(it, r, now):
    """Act on PAUSE, STOP, or RESUME at the start of a message, or of a new issue's title. True when
    nothing else is left to handle. A command more than two hours old (the first poll reads the whole
    history) is kept as a message but never acted on."""
    body, title = it.get("body") or "", it.get("title") or ""
    m, rest = COMMAND_RE.match(body), ""
    if m:
        rest = body[m.end():].strip()
    else:
        m = COMMAND_RE.match(title)
        if not m:
            return False
        rest = (title[m.end():] + " " + body).strip()
    if now - parse_time(it["created_at"]) > COMMAND_WINDOW:
        return False
    word = m.group(1).upper()
    who = "@" + (it.get("author") or "an Investor")
    when = clock(it["created_at"])
    if word in ("PAUSE", "STOP"):
        save_json(PAUSED, {"by": who, "at": it["created_at"], "url": it.get("url"), "word": word})
        reply = (f"Paused at {when}, as you asked. Nothing runs, no sessions and no queued jobs, until a message "
                 "that starts with RESUME. The heartbeat keeps going, so the watchdog stays quiet. (automatic reply)")
        log_event(f"Paused by an Investor ({word})", it.get("url"))
    else:
        was = os.path.exists(PAUSED)
        if was:
            os.remove(PAUSED)
        reply = (f"Resumed at {when}. The next session starts within 15 minutes. (automatic reply)" if was
                 else f"Received RESUME at {when}; the company wasn't paused, so nothing changed. (automatic reply)")
        log_event("Resumed by an Investor" if was else "RESUME from an Investor while not paused", it.get("url"))
    if comment(r, it["issue"], reply):
        it["receipt"] = now.isoformat()
    # A bare command needs nothing more; a command with more text waits for a session.
    return len(rest.split()) < 3


def poll(args):
    now = parse_time(args.now)
    r, allow = repo(), allowlist()
    if not r or not allow or not have_gh():
        return
    state = load_json(STATE, {})
    pending = load_json(PENDING, [])
    cursor = parse_time(state.get("cursor") or first_cursor())
    since = utc(cursor - OVERLAP)
    me = (my_login(state, now) or "").lower()
    items = fetch(r, since)
    if items is None:
        print("inbox: GitHub could not be read; will try again next tick")
        save_json(STATE, state)
        return
    seen = set(state.get("seen") or [])
    new = []
    for it in sorted(items, key=lambda x: x["created_at"]):
        if it["id"] in seen:
            continue
        author = (it.get("user") or "").lower()
        if author not in allow or author == me or parse_time(it["created_at"]) < cursor - OVERLAP:
            continue
        seen.add(it["id"])
        new.append(it)
    for it in new:
        msg = {"id": it["id"], "issue": it["issue"], "author": it.get("user"), "created_at": it["created_at"],
               "url": it.get("url"), "title": it.get("title"), "body": (it.get("body") or "")[:4000], "receipt": None}
        # Every Investor message, verbatim: amendments are checked against it (rules/amendment-check.py).
        os.makedirs(DIR, exist_ok=True)
        with open(MESSAGES, "a", encoding="utf-8") as f:
            f.write(json.dumps({**{k: msg[k] for k in ("id", "issue", "author", "created_at", "url", "title")},
                                "body": it.get("body") or ""}, ensure_ascii=False) + "\n")
        # The log is published on the site, so it names no account (Commandment 42).
        log_event(f"An Investor message on issue #{it['issue']}", it.get("url"))
        if command(msg, r, now):
            continue
        pending.append(msg)
    state["cursor"] = utc(now)
    state["seen"] = sorted(seen)[-2000:]
    save_json(STATE, state)
    save_json(PENDING, pending)
    update_mark(pending)
    if new:
        print(f"inbox: {len(new)} new Investor message(s), {len(pending)} waiting")


def grouped(pending):
    groups, order = {}, []
    for m in sorted(pending, key=lambda x: x["created_at"]):
        if m["issue"] not in groups:
            groups[m["issue"]] = []
            order.append(m["issue"])
        groups[m["issue"]].append(m)
    return [(i, groups[i]) for i in order]


def list_cmd(args):
    pending = load_json(PENDING, [])
    if not pending:
        print("No Investor messages are waiting.")
        return
    print(f"{len(pending)} Investor message(s) waiting. Reply to each in its issue, then run "
          "`python3 tools/inbox.py done <id>...`.")
    for issue, msgs in grouped(pending):
        title = next((m.get("title") for m in msgs if m.get("title")), None)
        print(f"\n## Issue #{issue}" + (f": {title}" if title else ""))
        for m in msgs:
            note = " | receipt sent" if m.get("receipt") else ""
            print(f"- {m['id']} | @{m.get('author')} | {clock(m['created_at'])}{note} | {m.get('url') or ''}")
            for line in (m.get("body") or "(no text)").splitlines() or ["(no text)"]:
                print("  > " + line)


def done(args):
    pending = load_json(PENDING, [])
    ids = set(args.ids)
    left = [] if args.all else [m for m in pending if m["id"] not in ids]
    unknown = sorted(ids - {m["id"] for m in pending}) if not args.all else []
    save_json(PENDING, left)
    update_mark(left)
    print(f"{len(pending) - len(left)} marked done, {len(left)} waiting" + (f"; unknown: {', '.join(unknown)}" if unknown else ""))


def situation(d):
    run, code, until = d.get("run"), d.get("code"), d.get("until")
    if code == "paused":
        return "The company is paused; it will act on this after a message that starts with RESUME."
    if code == "hold":
        return "Day 1 setup is running; the company will reply when it finishes."
    if code in ("limit_5h", "limit_week") and until:
        which = "weekly" if code == "limit_week" else "5-hour"
        return f"The company is at its {which} usage limit until {clock(until)} and will reply then."
    if code == "logged_out":
        return ("Claude Code is logged out on the Mac mini, so the company can't reply until one of you logs in "
                "again (see the emergency issue).")
    if run in ("morning", "evening", "weekly", "final"):
        return "The company is writing its report now and will reply right after it, within about 30 minutes."
    return "The company will reply at its next session, usually within 30 minutes."


def receipt(args):
    now = parse_time(args.now)
    pending = load_json(PENDING, [])
    todo = [m for m in pending if not m.get("receipt") and now - parse_time(m["created_at"]) < RECEIPT_WINDOW]
    r = repo()
    if not todo or not r or not have_gh():
        return
    text = situation(load_json(args.decision, {}))
    sent = 0
    for issue, msgs in grouped(todo):
        times = ", ".join(clock(m["created_at"]) for m in msgs)
        if comment(r, issue, f"Received ({times}). {text} (automatic receipt)"):
            for m in msgs:
                m["receipt"] = now.isoformat()
            sent += 1
    save_json(PENDING, pending)
    print(f"inbox: {sent} receipt(s) posted")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("poll"); s.add_argument("--now"); s.set_defaults(fn=poll)
    s = sub.add_parser("list"); s.set_defaults(fn=list_cmd)
    s = sub.add_parser("done"); s.add_argument("ids", nargs="*"); s.add_argument("--all", action="store_true")
    s.set_defaults(fn=done)
    s = sub.add_parser("receipt"); s.add_argument("--decision", default=os.path.join(ROOT, "ops", "last_decision.json"))
    s.add_argument("--now"); s.set_defaults(fn=receipt)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
