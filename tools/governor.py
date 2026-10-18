#!/usr/bin/env python3
"""Usage governor and run scheduler, called by tools/supervisor.sh.

Subcommands:
  decide [--now ISO]                 print a JSON decision: which session to run, if any
  record <run file> --type T [--exit N] [--result-out PATH] [--now ISO]
                                     account a finished run (stream-json or json output);
                                     split its cost by category and model; detect a
                                     usage-limit hit or a logged-out Claude Code
  set-day1 [YYYY-MM-DD]              record Day 1 (default: today, Eastern)
  set-budget <usd>                   set weekly_budget_usd (calibrate on Day 1 against /usage)
  set-fable-budget <usd>             set fable_budget_usd (the Fable meter in /usage)
  set-5h-budget <usd>                set five_hour_budget_usd (the 5-hour meter in /usage)
  report-usage [--now ISO]           print the "Usage" block for a report (Markdown)
  set-anchor <ISO>                   align the pacing week with the plan's weekly reset
  mark-limit <hours> [--now ISO]     pause Claude sessions for N hours by hand
  status [--json] [--now ISO]        one-screen summary (or JSON for the weekly review)

Files, all under ops/:
  usage.json      budget, caps, spend per day by category and model, recent runs, pauses
  state.json      day1, timestamps of the last morning/evening/work runs, inbox_last_check
  board.md        the task board; a runnable task is a line starting with "- [ ]"
  inbox_pending   exists when tools/inbox_check.sh found a new Investor message
  run.json        written by the supervisor for the session (and the model guard) to read

Budget unit: Claude Code's own cost estimate (total_cost_usd in each run's
result), which prices every model at its API rate, so one weekly figure paces
every model at once. Calibrate weekly_budget_usd on Day 1 against the
percentages in /usage, and again whenever a limit is hit early.

Categories (Tenet 6): project, reports, meetings, hiring, talk. A session's own
messages count to its type (work = project; morning, evening, weekly, final =
reports). A worker call counts to the tag that starts its Agent description:
[meeting], [hiring], [diary] or [talk], [report] or [testimony]; untagged calls
count to the session's category.

Use it all (Tenet 7): unused usage is lost at the weekly reset, so the governor
paces toward 100% of the weekly limit. It flags a week that is behind pace
(upgrade: move Haiku and Sonnet work up a model; backlog: refill the board
instead of idling), releases the daily reserve once the evening report is done,
and calibrates itself: a real limit hit sets the budget to what was actually
spent, and a week that spent its whole budget without hitting the limit raises
the budget by probe_step. Fable is a ceiling, not a target: it shares the weekly
limit, so it is used as the work needs and never pushed.

Company-owned: the company may improve this under Commandment 3.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPS = os.path.join(ROOT, "ops")
USAGE = os.path.join(OPS, "usage.json")
STATE = os.path.join(OPS, "state.json")
BOARD = os.path.join(OPS, "board.md")
INBOX = os.path.join(OPS, "inbox_pending")
QUIET = os.path.join(ROOT, "tools", "quiet_night.py")
TZ = ZoneInfo("America/New_York")

# Session types. budget_share caps one session's cost (--max-budget-usd) as a
# fraction of today's share; work sessions are capped at what's left of it.
RUN_SPECS = {
    "work": {"prompt": "work.md", "model": "sonnet", "effort": "medium", "max_turns": 40, "category": "project"},
    "morning": {"prompt": "morning.md", "model": "haiku", "effort": "low", "max_turns": 20,
                "category": "reports", "budget_share": 0.05},
    "evening": {"prompt": "evening.md", "model": "sonnet", "effort": "low", "max_turns": 30,
                "category": "reports", "budget_share": 0.15},
    "weekly": {"prompt": "evening.md", "model": "sonnet", "effort": "medium", "max_turns": 45,
               "category": "reports", "budget_share": 0.25},
    "final": {"prompt": "evening.md", "model": "opus", "effort": "high", "max_turns": 70,
              "category": "reports", "budget_share": 1.0},
}
CATEGORIES = ("project", "reports", "meetings", "hiring", "talk")
TAGS = {"[meeting]": "meetings", "[hiring]": "hiring", "[diary]": "talk", "[talk]": "talk", "[report]": "reports", "[testimony]": "reports"}
USAGE_DEFAULTS = {
    "weekly_budget_usd": 150.0,
    "reserve_fraction": 0.10,
    "fable_fraction": 0.5,
    "fable_budget_usd": None,
    "five_hour_budget_usd": None,
    "probe_step": 0.10,
    "week_closed_until": None,
    "weeks": [],
    "limit_hits": [],
    "caps": {"reports": 0.05, "meetings": 0.04, "hiring": 0.03, "talk": 0.01},
    "week_anchor": None,
    "rate_limit_until": None,
    "fable_blocked_until": None,
    "auth_failed_at": None,
    "days": {},
    "cats": {},
    "models": {},
    "runs": [],
}
STATE_DEFAULTS = {
    "day1": None,
    "last_morning_date": None,
    "last_evening_date": None,
    "last_evening_at": None,
    "last_work_at": None,
    "inbox_last_check": "1970-01-01T00:00:00Z",
    "morning_skipped": [],
    "last_backlog_at": None,
}
IDLE_MINUTES = 60
BACKLOG_MINUTES = 120
BEHIND = 0.85
AUTH_RETRY_MINUTES = 60
MIN_SESSION_USD = 0.50
# Per million tokens: input, cache write (1 hour), cache read, output.
# platform.claude.com/docs/en/about-claude/pricing, October 2026. Only used when a
# result carries no cost of its own, and to split a run's cost between categories.
PRICES_PER_MTOK = {
    "fable": (10.0, 20.0, 0.25, 50.0),
    "opus": (4.0, 8.0, 0.20, 20.0),
    "sonnet": (2.0, 4.0, 0.10, 10.0),
    "haiku": (0.10, 0.20, 0.01, 0.50),
}
LIMIT_RE = re.compile(r"(hit|reached|exceed\w*) (your|the) ([a-z ]*?)limit|rate[_ ]limit|usage limit|limit reached", re.I)
AUTH_RE = re.compile(r"not logged in|run /login|invalid api key|oauth token (has )?expired|authentication[_ ]error", re.I)


def load(path, defaults):
    data = json.loads(json.dumps(defaults))
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            try:
                data.update(json.load(f))
            except json.JSONDecodeError:
                pass
    return data


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def parse_now(value):
    if not value:
        return dt.datetime.now(TZ)
    d = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)
    return d.astimezone(TZ)


def until_active(usage, key, now):
    value = usage.get(key)
    return bool(value) and parse_now(value) > now


def day_number(state, now):
    if not state.get("day1"):
        return None
    d1 = dt.date.fromisoformat(state["day1"])
    return (now.date() - d1).days + 1


def week_window(usage, state, now):
    """Return (start, end) of the current pacing week as aware datetimes."""
    anchor = usage.get("week_anchor")
    if anchor:
        a = parse_now(anchor)
    elif state.get("day1"):
        a = dt.datetime.combine(dt.date.fromisoformat(state["day1"]), dt.time(0, 0), TZ)
    else:
        a = dt.datetime.combine(now.date(), dt.time(0, 0), TZ)
    weeks = (now - a) // dt.timedelta(days=7)
    start = a + weeks * dt.timedelta(days=7)
    if start > now:
        start -= dt.timedelta(days=7)
    return start, start + dt.timedelta(days=7)


def in_window(day, start, end):
    d = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(12, 0), TZ)
    return start <= d < end


def spend_between(usage, start, end):
    return sum(float(c) for day, c in usage.get("days", {}).items() if in_window(day, start, end))


def model_spend_between(usage, family, start, end):
    return sum(float(m.get(family, 0.0)) for day, m in usage.get("models", {}).items() if in_window(day, start, end))


def pacing(usage, state, now):
    start, end = week_window(usage, state, now)
    used_week = spend_between(usage, start, end)
    days_left = max(1, (end.date() - now.date()).days)
    budget = float(usage.get("weekly_budget_usd", 150.0))
    today = usage.get("days", {}).get(now.date().isoformat(), 0.0)
    # Today's share is fixed for the day: what was left this morning, spread over the days left.
    share = max(0.0, budget - (used_week - float(today))) / days_left
    reserve = float(usage.get("reserve_fraction", 0.10))
    # The reserve protects the evening report; once it has run, the rest of the day's share is for work.
    if state.get("last_evening_date") == now.date().isoformat():
        reserve = 0.0
    return {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "used_week_usd": round(used_week, 4),
        "budget_usd": budget,
        "days_left": days_left,
        "today_share_usd": round(share, 4),
        "today_used_usd": round(float(today), 4),
        "reserve_fraction": reserve,
        "work_allowed": float(today) < share * (1 - reserve),
    }


def category_shares(usage, now, days=7):
    """Each category's share of all spend over the last `days` days (rolling)."""
    first = now.date() - dt.timedelta(days=days - 1)
    totals = {c: 0.0 for c in CATEGORIES}
    for day, cats in usage.get("cats", {}).items():
        if first <= dt.date.fromisoformat(day) <= now.date():
            for c, v in cats.items():
                totals[c] = totals.get(c, 0.0) + float(v)
    total = sum(totals.values())
    return total, {c: (round(v / total, 4) if total else 0.0) for c, v in totals.items()}


def window_spend(usage, now, hours):
    """Spend in the last `hours`, from the recorded runs."""
    since = now - dt.timedelta(hours=hours)
    return sum(float(r.get("cost_usd", 0.0)) for r in usage.get("runs", []) if parse_now(r["at"]) > since)


def fable_budget(usage):
    calibrated = usage.get("fable_budget_usd")
    if calibrated:
        return float(calibrated)
    return float(usage.get("fable_fraction", 0.5)) * float(usage.get("weekly_budget_usd", 150.0))


def fable_status(usage, state, now):
    start, end = week_window(usage, state, now)
    spent = model_spend_between(usage, "fable", start, end)
    allowance = fable_budget(usage)
    blocked = until_active(usage, "fable_blocked_until", now)
    return {"fable_ok": spent < allowance and not blocked, "fable_week_usd": round(spent, 4),
            "fable_allowance_usd": round(allowance, 4), "fable_blocked_until": usage.get("fable_blocked_until") if blocked else None}


def effective_caps(usage):
    """Saved caps over the defaults, so a usage.json written before a category existed still caps it."""
    return {**USAGE_DEFAULTS["caps"], **(usage.get("caps") or {})}


def budget_signals(usage, state, now, pace):
    total, shares = category_shares(usage, now)
    caps = effective_caps(usage)
    # Shares are noise until there is about half a day of spend to divide.
    enough = total >= 0.5 * max(pace["today_share_usd"], 1.0)
    over = [c for c, cap in caps.items() if enough and shares.get(c, 0.0) > float(cap)]
    fable = fable_status(usage, state, now)
    return {**fable, "shares_7d": shares, "spend_7d_usd": round(total, 4), "over_cap": over,
            **pace_flags(usage, state, now, pace, fable)}


def pace_flags(usage, state, now, pace, fable):
    """Behind pace = the days already finished this week spent under 85% of their share of the
    budget. Then the company spends more per hour on stronger models (Fable excepted: it shares
    the weekly limit, so it is never pushed; its pace is reported for information only)."""
    start = parse_now(pace["week_start"])
    days_done = (now.date() - start.date()).days
    if days_done < 1:
        return {"upgrade": False, "pace_ratio": None, "fable_pace_ratio": None}
    before_today = pace["used_week_usd"] - pace["today_used_usd"]
    expected = pace["budget_usd"] * days_done / 7
    fable_before = fable["fable_week_usd"] - float(usage.get("models", {}).get(now.date().isoformat(), {}).get("fable", 0.0))
    fable_expected = fable["fable_allowance_usd"] * days_done / 7
    ratio = before_today / expected if expected else None
    fratio = fable_before / fable_expected if fable_expected else None
    return {"upgrade": ratio is not None and ratio < BEHIND,
            "pace_ratio": round(ratio, 3) if ratio is not None else None,
            "fable_pace_ratio": round(fratio, 3) if fratio is not None else None}


def close_weeks(usage, state, now):
    """Close the previous pacing week once: record it, and raise a budget that was fully spent
    without hitting its limit (the limit is higher than we thought). Returns True if it changed usage."""
    if not state.get("day1"):
        return False
    start, _ = week_window(usage, state, now)
    prev_start, prev_end = start - dt.timedelta(days=7), start
    day1 = dt.datetime.combine(dt.date.fromisoformat(state["day1"]), dt.time(0, 0), TZ)
    closed = usage.get("week_closed_until")
    if prev_end <= day1 or (closed and parse_now(closed) >= prev_end):
        return False
    spent = spend_between(usage, prev_start, prev_end)
    fable = model_spend_between(usage, "fable", prev_start, prev_end)
    hits = [h for h in usage.get("limit_hits", []) if prev_start <= parse_now(h["at"]) < prev_end]
    weekly_hit = any(h["kind"] == "weekly" for h in hits)
    fable_hit = any(h["kind"] == "fable" for h in hits)
    budget, fbudget = float(usage.get("weekly_budget_usd", 150.0)), fable_budget(usage)
    step = float(usage.get("probe_step", 0.10))
    actions = []
    if not weekly_hit and spent >= 0.95 * budget:
        usage["weekly_budget_usd"] = round(budget * (1 + step), 2)
        actions.append(f"weekly budget raised to {usage['weekly_budget_usd']}")
    if not fable_hit and fable >= 0.95 * fbudget:
        usage["fable_budget_usd"] = round(fbudget * (1 + step), 2)
        actions.append(f"Fable budget raised to {usage['fable_budget_usd']}")
    usage.setdefault("weeks", []).append({
        "start": prev_start.isoformat(), "budget_usd": budget, "spent_usd": round(spent, 2),
        "fable_budget_usd": round(fbudget, 2), "fable_spent_usd": round(fable, 2),
        "weekly_limit_hit": weekly_hit, "fable_limit_hit": fable_hit, "actions": actions})
    usage["weeks"] = usage["weeks"][-20:]
    usage["week_closed_until"] = prev_end.isoformat()
    return True


def open_tasks():
    if not os.path.exists(BOARD):
        return 0
    with open(BOARD, encoding="utf-8") as f:
        return sum(1 for line in f if line.lstrip().startswith("- [ ]"))


def is_quiet(since):
    if not since or not os.path.exists(QUIET):
        return False
    try:
        out = subprocess.run([sys.executable, "-I", QUIET, "--since", since],
                             capture_output=True, text=True, timeout=60, cwd=ROOT)
        return bool(json.loads(out.stdout).get("quiet"))
    except Exception:
        return False


def session_budget(kind, pace, usage):
    spec = RUN_SPECS[kind]
    share = pace["today_share_usd"]
    if kind == "work":
        left = share * (1 - pace["reserve_fraction"]) - pace["today_used_usd"]
        cap = max(left, 0.25 * share)
    else:
        cap = spec["budget_share"] * share
    return round(max(MIN_SESSION_USD, cap), 2)


def session(kind, base, pace, usage, **extra):
    return {**base, "run": kind, **RUN_SPECS[kind], "max_budget_usd": session_budget(kind, pace, usage), **extra}


def decide(args):
    now = parse_now(args.now)
    usage = load(USAGE, USAGE_DEFAULTS)
    state = load(STATE, STATE_DEFAULTS)
    today = now.date().isoformat()
    day = day_number(state, now)
    if close_weeks(usage, state, now):
        save(USAGE, usage)
    pace = pacing(usage, state, now)
    base = {"now": now.isoformat(), "day": day, "pacing": pace, "backlog": False,
            **budget_signals(usage, state, now, pace)}

    if until_active(usage, "rate_limit_until", now):
        return {**base, "run": "queue", "reason": f"usage limit hit; sessions resume after {usage['rate_limit_until']}"}
    auth = usage.get("auth_failed_at")
    if auth and now - parse_now(auth) < dt.timedelta(minutes=AUTH_RETRY_MINUTES):
        return {**base, "run": "queue", "reason": "Claude Code is logged out; retrying hourly until an Investor logs in again"}

    # Reports first. They are exempt from the daily share but not from a limit hit.
    if now.hour >= 18 and state.get("last_evening_date") != today:
        kind = "final" if day == 30 else "weekly" if day in (7, 14, 21, 28) else "evening"
        return session(kind, base, pace, usage, weekly=kind == "weekly", final=kind == "final", questions=True,
                       reason="evening report is due")

    last_evening = state.get("last_evening_at")
    morning_due = (6 <= now.hour < 12 and state.get("last_morning_date") != today
                   and last_evening and parse_now(last_evening).date() < now.date())
    if morning_due:
        if is_quiet(last_evening):
            state["last_morning_date"] = today
            state.setdefault("morning_skipped", []).append(today)
            save(STATE, state)
            base["morning_skipped"] = True
        else:
            return session("morning", base, pace, usage, weekly=False, final=False, questions=False,
                           reason="morning report is due and the night was not quiet")

    if not pace["work_allowed"]:
        return {**base, "run": "queue", "reason": "today's share of the weekly budget is spent"}

    tasks = open_tasks()
    inbox = os.path.exists(INBOX)
    last_work = state.get("last_work_at")
    recent = last_work and (now - parse_now(last_work)) < dt.timedelta(minutes=IDLE_MINUTES)
    if tasks == 0 and not inbox and recent:
        last_backlog = state.get("last_backlog_at")
        if base["upgrade"] and not (last_backlog and now - parse_now(last_backlog) < dt.timedelta(minutes=BACKLOG_MINUTES)):
            state["last_backlog_at"] = now.isoformat()
            save(STATE, state)
            return session("work", base, pace, usage, weekly=False, final=False, questions=False, backlog=True,
                           open_tasks=0, inbox_pending=False,
                           reason="the board is empty but the week is behind pace: refill it with improvements")
        return {**base, "run": "skip", "reason": "nothing to do: no open tasks, no new messages, a session ran recently"}

    return session("work", base, pace, usage, weekly=False, final=False, questions=False,
                   open_tasks=tasks, inbox_pending=inbox, reason="work session")


def family(model):
    m = (model or "").lower()
    return next((f for f in PRICES_PER_MTOK if f in m), "other")


def price(fam, u):
    p = PRICES_PER_MTOK.get(fam, PRICES_PER_MTOK["sonnet"])
    get = lambda *keys: float(next((u[k] for k in keys if isinstance(u.get(k), (int, float))), 0))
    return (get("input_tokens", "inputTokens") * p[0]
            + get("cache_creation_input_tokens", "cacheCreationInputTokens") * p[1]
            + get("cache_read_input_tokens", "cacheReadInputTokens") * p[2]
            + get("output_tokens", "outputTokens") * p[3]) / 1_000_000


def read_run(path):
    """Return (raw text, every JSON object, the result object) from json or stream-json output."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except OSError:
        return "", [], {}
    objs = []
    try:
        whole = json.loads(raw)
        objs = whole if isinstance(whole, list) else [whole]
    except json.JSONDecodeError:
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    objs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    objs = [o for o in objs if isinstance(o, dict)]
    result = next((o for o in reversed(objs) if o.get("type") == "result" or "total_cost_usd" in o), {})
    return raw, objs, result


def tag_category(description, default):
    d = (description or "").strip().lower()
    return next((cat for tag, cat in TAGS.items() if d.startswith(tag)), default)


def attribute(objs, session_category):
    """Split usage between categories and model families using stream-json messages.

    Worker messages carry parent_tool_use_id, the id of the Agent call that started
    them; that call's description tag decides the category. Messages are counted
    once per message id (stream-json repeats a message once per content block).
    """
    calls, per_message = {}, {}
    for o in objs:
        if o.get("type") != "assistant":
            continue
        msg = o.get("message") or {}
        parent = o.get("parent_tool_use_id")
        cat = calls.get(parent, session_category) if parent else session_category
        for block in msg.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task"):
                calls[block.get("id")] = tag_category((block.get("input") or {}).get("description"), session_category)
        if isinstance(msg.get("usage"), dict):
            per_message[msg.get("id") or id(o)] = (cat, family(msg.get("model")), msg["usage"])
    cats, models = {}, {}
    for cat, fam, u in per_message.values():
        c = price(fam, u)
        cats[cat] = cats.get(cat, 0.0) + c
        models[fam] = models.get(fam, 0.0) + c
    return cats, models


def scale(parts, total):
    s = sum(parts.values())
    if total <= 0 or s <= 0:
        return {}
    return {k: round(v * total / s, 6) for k, v in parts.items() if v > 0}


def run_cost(result, est_total):
    cost = result.get("total_cost_usd")
    if isinstance(cost, (int, float)):
        return float(cost)
    mu = result.get("modelUsage") or {}
    listed = [u.get("costUSD") for u in mu.values() if isinstance(u, dict)]
    if listed and all(isinstance(c, (int, float)) for c in listed):
        return float(sum(listed))
    if mu:
        return sum(price(family(m), u) for m, u in mu.items() if isinstance(u, dict))
    return est_total


def add_to(table, day, parts):
    row = table.setdefault(day, {})
    for k, v in parts.items():
        row[k] = round(float(row.get(k, 0.0)) + v, 6)


def record(args):
    now = parse_now(args.now)
    usage = load(USAGE, USAGE_DEFAULTS)
    state = load(STATE, STATE_DEFAULTS)
    raw, objs, result = read_run(args.run_file)
    if args.result_out:
        with open(args.result_out, "w", encoding="utf-8") as f:
            json.dump(result or {"type": "result", "is_error": True, "subtype": "no_result", "tail": raw[-2000:]}, f, indent=1)
            f.write("\n")
    category = RUN_SPECS.get(args.type, RUN_SPECS["work"])["category"]
    cats_est, models_est = attribute(objs, category)
    cost = run_cost(result, sum(cats_est.values()))
    cats = scale(cats_est, cost) or ({category: cost} if cost else {})
    mu = result.get("modelUsage") or {}
    models = {}
    for m, u in mu.items():
        if isinstance(u, dict):
            c = u.get("costUSD") if isinstance(u.get("costUSD"), (int, float)) else price(family(m), u)
            models[family(m)] = models.get(family(m), 0.0) + c
    models = scale(models, cost) or scale(models_est, cost)

    today = now.date().isoformat()
    usage.setdefault("days", {})[today] = round(float(usage["days"].get(today, 0.0)) + cost, 4)
    add_to(usage.setdefault("cats", {}), today, cats)
    add_to(usage.setdefault("models", {}), today, models)

    failed = bool(result.get("is_error")) or not result or args.exit != 0
    text = " ".join(str(result.get(k, "")) for k in ("result", "error", "subtype", "terminal_reason")) if result else raw[-2000:]
    limited = failed and (bool(LIMIT_RE.search(text)) or result.get("subtype") == "error_rate_limit")
    auth_failed = failed and bool(AUTH_RE.search(text))
    fable_only = limited and "fable" in text.lower()
    subtype = str(result.get("subtype", ""))
    capped = subtype.startswith("error_max") or "budget" in subtype
    entry = {
        "at": now.isoformat(), "type": args.type, "exit": args.exit, "cost_usd": round(cost, 4),
        "cats": {k: round(v, 4) for k, v in cats.items()}, "models": {k: round(v, 4) for k, v in models.items()},
        "turns": result.get("num_turns"), "duration_ms": result.get("duration_ms"), "subtype": subtype or None,
        "is_error": failed, "denials": len(result.get("permission_denials") or []),
        "limited": limited, "auth_failed": auth_failed,
        "retry": failed and not (limited or auth_failed or capped),
        "file": os.path.relpath(args.result_out or args.run_file, ROOT),
    }
    usage.setdefault("runs", []).append(entry)
    usage["runs"] = usage["runs"][-400:]
    # Spend "this plan week": the pacing window when it is anchored to the plan's reset, else the last 7 days.
    if usage.get("week_anchor"):
        wstart, wend = week_window(usage, state, now)
        in7 = lambda day: in_window(day, wstart, wend)
    else:
        first7 = now.date() - dt.timedelta(days=6)
        in7 = lambda day: first7 <= dt.date.fromisoformat(day) <= now.date()
    if fable_only:
        usage["fable_blocked_until"] = (now + dt.timedelta(hours=24)).isoformat()
        # The real Fable limit is what was actually spent on Fable when it was reached.
        fable7 = sum(float(m.get("fable", 0.0)) for d, m in usage.get("models", {}).items() if in7(d))
        if fable7 > 0:
            usage["fable_budget_usd"] = round(fable7, 2)
        usage.setdefault("limit_hits", []).append({"at": now.isoformat(), "kind": "fable", "spend_7d_usd": round(fable7, 2)})
    elif limited:
        weekly = "week" in text.lower()
        usage["rate_limit_until"] = (now + dt.timedelta(hours=24 if weekly else 5)).isoformat()
        spend7 = sum(float(c) for d, c in usage.get("days", {}).items() if in7(d))
        if weekly and spend7 > 0:
            usage["weekly_budget_usd"] = round(spend7, 2)
        usage.setdefault("limit_hits", []).append({"at": now.isoformat(), "kind": "weekly" if weekly else "session",
                                                   "spend_7d_usd": round(spend7, 2)})
    usage["limit_hits"] = usage.get("limit_hits", [])[-50:]
    if not limited and usage.get("rate_limit_until") and parse_now(usage["rate_limit_until"]) <= now:
        usage["rate_limit_until"] = None
    if auth_failed:
        usage["auth_failed_at"] = now.isoformat()
    elif not failed:
        usage["auth_failed_at"] = None
    if not failed or capped:
        if args.type == "work":
            state["last_work_at"] = now.isoformat()
        elif args.type == "morning":
            state["last_morning_date"] = today
        elif args.type in ("evening", "weekly", "final"):
            state["last_evening_date"] = today
            state["last_evening_at"] = now.isoformat()
    save(USAGE, usage)
    save(STATE, state)
    print(json.dumps(entry))


def set_day1(args):
    state = load(STATE, STATE_DEFAULTS)
    state["day1"] = args.date or dt.datetime.now(TZ).date().isoformat()
    save(STATE, state)
    print(f"Day 1 = {state['day1']}")


def set_budget(args):
    usage = load(USAGE, USAGE_DEFAULTS)
    usage["weekly_budget_usd"] = float(args.usd)
    save(USAGE, usage)
    print(f"weekly_budget_usd = {usage['weekly_budget_usd']}")


def set_fable_budget(args):
    usage = load(USAGE, USAGE_DEFAULTS)
    usage["fable_budget_usd"] = float(args.usd)
    save(USAGE, usage)
    print(f"fable_budget_usd = {usage['fable_budget_usd']}")


def set_5h_budget(args):
    usage = load(USAGE, USAGE_DEFAULTS)
    usage["five_hour_budget_usd"] = float(args.usd)
    save(USAGE, usage)
    print(f"five_hour_budget_usd = {usage['five_hour_budget_usd']}")


def report_usage(args):
    """The Usage section of a report: every window the plan meters, by model, as Markdown."""
    now = parse_now(args.now)
    usage = load(USAGE, USAGE_DEFAULTS)
    state = load(STATE, STATE_DEFAULTS)
    pace = pacing(usage, state, now)
    fable = fable_status(usage, state, now)
    five_h = window_spend(usage, now, 5)
    five_budget = usage.get("five_hour_budget_usd")
    start, end = week_window(usage, state, now)
    by_model = {}
    for day, models in usage.get("models", {}).items():
        if in_window(day, start, end):
            for m, v in models.items():
                by_model[m] = by_model.get(m, 0.0) + float(v)
    total_week = sum(by_model.values()) or pace["used_week_usd"]
    pct = lambda used, budget: f"{used / budget:.0%}" if budget else "not calibrated"
    lines = ["| Window | Used | Of | Share |", "| --- | --- | --- | --- |",
             f"| Last 5 hours | ${five_h:.2f} | ${float(five_budget):.2f} | {pct(five_h, five_budget)} |" if five_budget
             else f"| Last 5 hours | ${five_h:.2f} | not calibrated | |",
             f"| Today | ${pace['today_used_usd']:.2f} | ${pace['today_share_usd']:.2f} (today's share) | {pct(pace['today_used_usd'], pace['today_share_usd'])} |",
             f"| This week (resets {end:%a %b %-d, %-I:%M %p}) | ${pace['used_week_usd']:.2f} | ${pace['budget_usd']:.2f} | {pct(pace['used_week_usd'], pace['budget_usd'])} |",
             f"| Fable this week | ${fable['fable_week_usd']:.2f} | ${fable['fable_allowance_usd']:.2f} | {pct(fable['fable_week_usd'], fable['fable_allowance_usd'])} |",
             "", "| Model | This week | Share |", "| --- | --- | --- |"]
    for m in ("fable", "opus", "sonnet", "haiku"):
        v = by_model.get(m, 0.0)
        lines.append(f"| {m.capitalize()} | ${v:.2f} | {v / total_week:.0%} |" if total_week else f"| {m.capitalize()} | ${v:.2f} | |")
    notes = []
    if until_active(usage, "rate_limit_until", now):
        notes.append(f"Sessions paused until {parse_now(usage['rate_limit_until']):%a %-I:%M %p} (limit reached).")
    if not fable["fable_ok"]:
        notes.append("Fable is paused until the week resets.")
    if notes:
        lines += [""] + notes
    print("\n".join(lines))


def set_anchor(args):
    usage = load(USAGE, USAGE_DEFAULTS)
    usage["week_anchor"] = parse_now(args.when).isoformat()
    save(USAGE, usage)
    print(f"week_anchor = {usage['week_anchor']}")


def mark_limit(args):
    now = parse_now(args.now)
    usage = load(USAGE, USAGE_DEFAULTS)
    usage["rate_limit_until"] = (now + dt.timedelta(hours=float(args.hours))).isoformat()
    save(USAGE, usage)
    print(f"sessions paused until {usage['rate_limit_until']}")


def status(args):
    now = parse_now(args.now)
    usage = load(USAGE, USAGE_DEFAULTS)
    state = load(STATE, STATE_DEFAULTS)
    pace = pacing(usage, state, now)
    signals = budget_signals(usage, state, now, pace)
    totals = {c: 0.0 for c in CATEGORIES}
    for cats in usage.get("cats", {}).values():
        for c, v in cats.items():
            totals[c] = totals.get(c, 0.0) + float(v)
    by_model = {}
    for models in usage.get("models", {}).values():
        for m, v in models.items():
            by_model[m] = by_model.get(m, 0.0) + float(v)
    five_h = window_spend(usage, now, 5)
    five_budget = usage.get("five_hour_budget_usd")
    out = {"now": now.isoformat(), "day": day_number(state, now), "pacing": pace, **signals,
           "window_5h_usd": round(five_h, 4), "five_hour_budget_usd": five_budget,
           "window_5h_share": round(five_h / float(five_budget), 4) if five_budget else None,
           "caps": effective_caps(usage), "all_time_by_category_usd": {k: round(v, 2) for k, v in totals.items()},
           "all_time_by_model_usd": {k: round(v, 2) for k, v in by_model.items()},
           "weeks": usage.get("weeks", [])[-5:], "limit_hits": usage.get("limit_hits", [])[-5:],
           "rate_limit_until": usage.get("rate_limit_until"), "auth_failed_at": usage.get("auth_failed_at"),
           "open_tasks": open_tasks(), "inbox_pending": os.path.exists(INBOX)}
    if args.json:
        print(json.dumps(out, indent=2))
        return
    print(f"Now {now:%Y-%m-%d %H:%M %Z}, Day {out['day']}")
    print(f"Week {pace['week_start'][:10]} to {pace['week_end'][:10]}: used ${pace['used_week_usd']:.2f} of ${pace['budget_usd']:.2f}; "
          f"today ${pace['today_used_usd']:.2f} of share ${pace['today_share_usd']:.2f}; work allowed: {pace['work_allowed']}")
    print(f"Fable this week ${signals['fable_week_usd']:.2f} of ${signals['fable_allowance_usd']:.2f}; fable ok: {signals['fable_ok']}")
    print(f"Pace (finished days vs. their share): all models {signals['pace_ratio']}, Fable {signals['fable_pace_ratio']}; "
          f"upgrade: {signals['upgrade']}")
    for w in usage.get("weeks", [])[-3:]:
        print(f"  week of {w['start'][:10]}: spent ${w['spent_usd']:.2f} of ${w['budget_usd']:.2f}, Fable ${w['fable_spent_usd']:.2f} "
              f"of ${w['fable_budget_usd']:.2f}; limits hit: weekly {w['weekly_limit_hit']}, Fable {w['fable_limit_hit']}; "
              f"{'; '.join(w['actions']) or 'no change'}")
    caps = effective_caps(usage)
    print("Last 7 days by category: " + ", ".join(
        f"{c} {signals['shares_7d'].get(c, 0):.1%}" + (f" (cap {caps[c]:.0%})" if c in caps else "") for c in CATEGORIES)
        + (f"; over cap: {', '.join(signals['over_cap'])}" if signals["over_cap"] else ""))
    print(f"Limit pause until: {usage.get('rate_limit_until')}; logged out since: {usage.get('auth_failed_at')}; "
          f"open tasks: {out['open_tasks']}; inbox pending: {out['inbox_pending']}")
    for r in usage.get("runs", [])[-5:]:
        print(f"  {r['at'][:16]} {r['type']:8s} ${r['cost_usd']:.3f} turns={r.get('turns')} exit={r.get('exit')} "
              f"limited={r['limited']} {' '.join(f'{k}=${v:.3f}' for k, v in (r.get('cats') or {}).items())}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("decide"); s.add_argument("--now"); s.set_defaults(fn=decide)
    s = sub.add_parser("record"); s.add_argument("run_file"); s.add_argument("--type", required=True)
    s.add_argument("--exit", type=int, default=0); s.add_argument("--result-out"); s.add_argument("--now")
    s.set_defaults(fn=record)
    s = sub.add_parser("set-day1"); s.add_argument("date", nargs="?"); s.set_defaults(fn=set_day1)
    s = sub.add_parser("set-budget"); s.add_argument("usd"); s.set_defaults(fn=set_budget)
    s = sub.add_parser("set-fable-budget"); s.add_argument("usd"); s.set_defaults(fn=set_fable_budget)
    s = sub.add_parser("set-5h-budget"); s.add_argument("usd"); s.set_defaults(fn=set_5h_budget)
    s = sub.add_parser("report-usage"); s.add_argument("--now"); s.set_defaults(fn=report_usage)
    s = sub.add_parser("set-anchor"); s.add_argument("when"); s.set_defaults(fn=set_anchor)
    s = sub.add_parser("mark-limit"); s.add_argument("hours"); s.add_argument("--now"); s.set_defaults(fn=mark_limit)
    s = sub.add_parser("status"); s.add_argument("--json", action="store_true"); s.add_argument("--now")
    s.set_defaults(fn=status)
    args = p.parse_args()
    out = args.fn(args)
    if isinstance(out, dict):
        print(json.dumps(out))


if __name__ == "__main__":
    main()
