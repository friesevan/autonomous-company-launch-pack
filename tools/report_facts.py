#!/usr/bin/env python3
"""Gather everything a report needs into one short file, so a report session reads one file.

  python3 tools/report_facts.py [--kind evening] [--now ISO] [--out ops/report_facts.md]

No Claude. The supervisor runs it before every report session (morning, evening, weekly, final).
It covers the time since reports/last_report.txt: the scoreboard, the business events from the
log (moods, interviews, offers, and report notices are left to the records), commits other than
the Operator's, tasks finished on the board and what is open, Investor messages, Claude usage as
percentages of the plan's limits, recent ledger lines, open issues for the Investors, and the
state file. On weekly and final runs it adds the week's usage by category against the caps and
the latest optimizations (Tenet 7).

The output is git-ignored; it is rebuilt for every report. Company-owned (Commandment 3).
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = ZoneInfo("America/New_York")
STORY_TYPES = ("mood", "interview", "offer", "report")
MAX_EVENTS = 80


def path(*parts):
    return os.path.join(ROOT, *parts)


def read(rel, default=""):
    try:
        with open(path(rel), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default


def load_json(rel):
    try:
        return json.loads(read(rel, "{}") or "{}")
    except json.JSONDecodeError:
        return {}


def sh(cmd, timeout=60):
    try:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_time(s):
    """ISO 8601 as Python 3.9 reads it: also accepts Z, -0400-style offsets, and any fraction digits."""
    text = str(s).strip().replace("Z", "+00:00")
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    text = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], text, count=1)
    d = dt.datetime.fromisoformat(text)
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def window_start(now):
    """The last report's time, else the start of Day 1, else a day ago."""
    last = read("reports/last_report.txt").strip()
    if last:
        try:
            return parse_time(last)
        except ValueError:
            pass
    day1 = load_json("ops/state.json").get("day1")
    if day1:
        try:
            return dt.datetime.combine(dt.date.fromisoformat(day1), dt.time(0, 0), TZ)
        except ValueError:
            pass
    return now - dt.timedelta(days=1)


def events_between(start, now):
    out = []
    for line in read("log/events.jsonl").splitlines():
        try:
            e = json.loads(line)
            t = parse_time(e["time"])
        except (ValueError, KeyError, TypeError):
            continue
        if start < t <= now:
            out.append((t, e))
    out.sort(key=lambda x: x[0])
    return out


def section(title, lines, empty="None."):
    return [f"## {title}", ""] + (lines or [empty]) + [""]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kind", default="evening", choices=["morning", "evening", "weekly", "final"])
    ap.add_argument("--now", help="pretend it is another time (tests)")
    ap.add_argument("--out", default=os.path.join("ops", "report_facts.md"))
    args = ap.parse_args(argv)
    now = parse_time(args.now) if args.now else dt.datetime.now(TZ)
    start = window_start(now)
    state = load_json("ops/state.json")
    try:
        day = (now.astimezone(TZ).date() - dt.date.fromisoformat(state["day1"])).days + 1 if state.get("day1") else None
    except ValueError:
        day = None
    cfg = load_json("site.json")
    goal = float(cfg.get("goal_usd") or 200)

    out = ["# Report facts", "",
           f"For the {args.kind} report{f' of Day {day}' if day else ''}. Covers "
           f"{start.astimezone(TZ):%a %b} {start.astimezone(TZ).day}, {start.astimezone(TZ):%H:%M} "
           f"to {now.astimezone(TZ):%a %b} {now.astimezone(TZ).day}, {now.astimezone(TZ):%H:%M} (Eastern). "
           "Built by tools/report_facts.py without Claude; every fact in the report must match this file or the log.", ""]

    sb = load_json("ops/scoreboard.json")
    rev, spent = float(sb.get("revenue_usd") or 0), float(sb.get("spent_usd") or 0)
    out += section("Scoreboard", [
        f"- Net proceeds: ${rev:,.2f} of ${goal:,.0f} (${max(0.0, goal - rev):,.2f} to go)",
        f"- Real spending to date: ${spent:,.2f}",
        f"- Day {sb.get('day', day or '?')} of {cfg.get('days_total', 30)}, {sb.get('days_left', '?')} days left",
        f"- Stage: {sb.get('stage') or 'unknown'}; app: {sb.get('app_name') or 'no product chosen yet'}"
        + (f"; status: {sb['status']}" if sb.get("status") else "")
        + (f"; App Store: {sb['app_store_url']}" if sb.get("app_store_url") else ""),
    ])

    evs = events_between(start, now)
    business = [(t, e) for t, e in evs if str(e.get("type", "")).lower() not in STORY_TYPES]
    lines = []
    for t, e in business[-MAX_EVENTS:]:
        link = f" ({e['link']})" if e.get("link") else ""
        lines.append(f"- {t.astimezone(TZ):%a %H:%M} {e.get('type', '')} ({e.get('worker', '')}): {e.get('summary', '')}{link}")
    if len(business) > MAX_EVENTS:
        lines.insert(0, f"- ({len(business) - MAX_EVENTS} earlier events left out; python3 tools/events.py since {start.isoformat()})")
    out += section("What got done (events, oldest first)", lines, "Nothing was logged in this period.")
    who = sorted({str(e.get("worker", "")) for _, e in evs if e.get("worker") and e.get("worker") != "operator"})
    out += section("Who worked", [", ".join(who)] if who else [], "No worker logged anything.")

    commits = []
    for line in sh(["git", "log", f"--since={start.isoformat()}", "--no-merges", "--format=%h%x09%an%x09%s"]).splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and parts[1] != "Operator":
            commits.append(f"- {parts[0]} {parts[1]}: {parts[2]}")
    out += section(f"Commits ({len(commits)})", commits[:40])

    board = read("ops/board.md")
    open_tasks = [l.strip()[6:] for l in board.splitlines() if l.strip().startswith("- [ ]")]
    base = sh(["git", "rev-list", "-1", f"--before={start.isoformat()}", "HEAD"]).strip()
    diff = sh(["git", "diff", base, "--", "ops/board.md"]) if base else ""
    finished = [l[1:].strip()[6:] for l in diff.splitlines() if l.startswith("+") and l[1:].strip().lower().startswith("- [x]")]
    out += section("Board", [f"- Finished since the last report ({len(finished)}): " + ("; ".join(finished[:15]) or "none"),
                             f"- Open ({len(open_tasks)}): " + ("; ".join(open_tasks[:10]) or "none")])

    messages = [f"- {t.astimezone(TZ):%a %H:%M}: {e.get('summary', '')}" for t, e in evs if str(e.get("type", "")).lower() == "message"]
    out += section("Investor messages", messages)

    usage = sh([sys.executable, "-I", path("tools", "governor.py"), "report-usage", "--now", now.isoformat()]).strip()
    out += section("Usage (percentages of the plan's limits; one line in the report)", usage.splitlines(), "Not recorded yet.")

    ledger = []
    for p in sorted(glob.glob(path("log", "ledger*"))):
        rows = [r for r in read(os.path.relpath(p, ROOT)).splitlines() if r.strip()]
        ledger += [f"{os.path.basename(p)}: " + r for r in rows[-8:]]
    out += section("Ledger (latest lines)", ledger, "No ledger yet.")

    gh = shlex.split(os.environ.get("GH_CMD") or "gh")  # GH_CMD overrides gh, as in tools/inbox.py
    if shutil.which(gh[0]):
        raw = sh([*gh, "issue", "list", "--state", "open", "--limit", "30", "--json", "number,title,labels"])
        try:
            issues = json.loads(raw or "[]")
        except json.JSONDecodeError:
            issues = []
        keep = []
        for i in issues:
            labels = {l.get("name", "") for l in i.get("labels", [])}
            if labels & {"emergency", "urgent", "report", "pitch"}:
                keep.append(f"- #{i.get('number')} [{', '.join(sorted(labels))}] {i.get('title', '')}")
        out += section("Open requests to the Investors", keep)

    safety = []
    for name, value in sorted(load_json("ops/posture.json").items()):
        if isinstance(value, str) and value != "on":
            safety.append(f"- Security setting {name}: {value} (ops/posture.json)")
    for mark in sorted(glob.glob(path("ops", ".alerted_*"))):
        try:
            when = dt.datetime.fromtimestamp(os.path.getmtime(mark), TZ)
        except OSError:
            continue
        if start < when <= now:
            safety.append(f"- Emergency sent {when:%a %H:%M}: {os.path.basename(mark)[len('.alerted_'):]}")
    for line in read("ops/runs/supervisor.log").splitlines()[-3000:]:
        if "file guard:" in line or "removed a stale lock" in line or "stopped" in line and "session ran past" in line:
            try:
                when = dt.datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
            except ValueError:
                continue
            if start < when <= now:
                safety.append(f"- {when:%a %H:%M} {line[20:].strip()}")
    if os.path.exists(path("ops", "paused")):
        safety.append(f"- The company is paused: {read('ops/paused').strip()}")
    out += section("Safety and outages (emergencies, restored files, settings; outages are in the events)", safety)

    if args.kind in ("weekly", "final"):
        status = sh([sys.executable, "-I", path("tools", "governor.py"), "status", "--json", "--now", now.isoformat()])
        try:
            st = json.loads(status or "{}")
        except json.JSONDecodeError:
            st = {}
        plan = (st.get("plan") or {}).get("week") or {}
        kinds = st.get("kinds_7d") or {}
        api = st.get("api") or {}
        caps = st.get("caps") or {}
        shares = st.get("shares_7d") or {}
        pace = st.get("pacing") or {}
        week = [f"- {c}: {float(v):.1%} of the last 7 days" + (f" (cap {float(caps[c]):.0%})" if c in caps else " (at least 90%)")
                for c, v in shares.items()]
        if pace.get("budget_usd"):
            week.append(f"- This week so far: {float(pace.get('used_week_usd', 0)) / float(pace['budget_usd']):.0%} of the weekly limit")
        if st.get("fable_allowance_usd"):
            week.append(f"- Fable this week: {float(st.get('fable_week_usd', 0)) / float(st['fable_allowance_usd']):.0%} of its allowance")
        if plan:
            week.append(f"- Plan by now: {float(plan.get('plan_pct', 0)):.0f}% of the week; used {float(plan.get('actual_pct', 0)):.0f}% "
                        f"({plan.get('status', '?')}); why: " + (" ".join((st.get("plan") or {}).get("reasons") or []) or "nothing unusual"))
        if any(kinds.values()):
            week.append("- Product work by kind: " + ", ".join(f"{k} {float(v):.0%}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]) if v))
        if api.get("month_usd"):
            week.append(f"- API credits this cycle: {float(api.get('month_pct', 0)):.0f}% of the included credits, as overflow")
        out += section("The week in usage", week, "Not recorded yet.")
        opt = [l for l in read("log/optimizations.md").splitlines() if l.strip()]
        out += section("Optimizations (log/optimizations.md, latest lines)", opt[-25:], "None logged.")

    st_md = read("ops/state.md").splitlines()
    out += section("Where things stand (ops/state.md)", st_md[:80], "No state file.")

    text = "\n".join(out).rstrip() + "\n"
    dest = path(args.out) if not os.path.isabs(args.out) else args.out
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"report facts: {len(business)} events, {len(commits)} commits, {len(finished)} tasks finished -> {os.path.relpath(dest, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
