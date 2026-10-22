#!/usr/bin/env python3
"""Usage governor and run scheduler, called by tools/supervisor.sh.

Subcommands:
  decide [--now ISO] [--api-ready] [--dry-run]
                                     print a JSON decision: which session to run, if any, and
                                     how it is billed (the plan, or API credits as overflow)
  record <run file> --type T [--exit N] [--billing plan|api] [--result-out PATH] [--now ISO]
                                     account a finished run (stream-json or json output): split
                                     its cost by category, work kind, and model; detect a usage
                                     limit, a logged-out Claude Code, used-up API credits, and a
                                     session billed to the wrong account
  meter <run file> [--now ISO]       read the plan's own meters from a `claude -p "/usage"` run:
                                     exact percentages and reset times; calibrates the budgets,
                                     anchors the week, and ends a limit pause early
  meter --due [--now ISO]            exit 0 when a meter reading is due
  set-day1 [YYYY-MM-DD]              record Day 1 (default: today, Eastern)
  set-budget <usd>                   set weekly_budget_usd by hand (the meter calibrates it)
  set-fable-budget <usd>             set fable_budget_usd by hand
  set-5h-budget <usd>                set five_hour_budget_usd by hand
  report-usage [--now ISO]           print the "Usage" block for a report (Markdown, percentages)
  set-anchor <ISO>                   align the pacing week with the plan's weekly reset by hand
  mark-limit <hours> [--now ISO]     pause Claude sessions for N hours by hand
  status [--json] [--now ISO]        one-screen summary (or JSON for the site and weekly review)

Files, all under ops/ unless noted:
  usage.json      budgets, caps, spend per day by category, work kind, and model, recent runs,
                  pauses, the latest meter reading, and API-credit spend
  state.json      day1, timestamps of the last morning, evening, work, and inbox runs
  board.md        the task board; a runnable task is a line starting with "- [ ]"
  inbox_pending   exists while Investor messages wait (tools/inbox.py)
  hold            Day 1 setup is running: no sessions
  paused          an Investor wrote PAUSE or STOP (tools/inbox.py): nothing runs until RESUME
  ticks.jsonl     one line per decision: what the loop did and why
  run.json        written by the supervisor for the session (and the hooks) to read
  investors/billing.json   the Investors' switch and caps for API-credit overflow

Budget unit: Claude Code's own cost estimate (total_cost_usd in each run's result), which
prices every model at its API rate, so one weekly figure paces every model at once. The
plan's own meter (/usage) gives the exact percentages; the governor calibrates its dollar
budgets from them and shows usage only as percentages of the plan's limits.

Categories (Tenet 6): project, reports, meetings, hiring, talk. A session's own messages count
to its type (work and inbox = project; morning, evening, weekly, final = reports). A worker call
counts to the cap tag that starts its Agent description: [meeting], [hiring], [diary] or
[talk], [report] or [testimony]; untagged calls count to the session's category.

Work kinds break project usage down further: research, design, build, test, release, review,
tools, plan (a kind tag after any cap tag, as in "[meeting] [design] ..."), operations (the
Operator's own turns), and other (project worker calls without a kind tag).

Use it all (Tenet 7): unused usage is lost at the weekly reset, so the governor paces toward
100% of the weekly limit. It flags a week that is behind pace (upgrade: move Haiku and Sonnet
work up a model; backlog: refill the board instead of idling), releases the daily reserve once
the evening report is done, and calibrates itself. Fable is a ceiling, not a target: it shares
the weekly limit, so it is used as the work needs and never pushed.

API credits (the plan's included credits, Tenet 6): only as overflow while a plan limit has
paused work, never for Fable, within investors/billing.json's caps.

Company-owned: the company may improve this under Commandment 3.
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPS = os.path.join(ROOT, "ops")
USAGE = os.path.join(OPS, "usage.json")
STATE = os.path.join(OPS, "state.json")
BOARD = os.path.join(OPS, "board.md")
INBOX = os.path.join(OPS, "inbox_pending")
HOLD = os.path.join(OPS, "hold")
PAUSED = os.path.join(OPS, "paused")
TICKS = os.path.join(OPS, "ticks.jsonl")
BILLING = os.path.join(ROOT, "investors", "billing.json")
LAST_REPORT = os.path.join(ROOT, "reports", "last_report.txt")
QUIET = os.path.join(ROOT, "tools", "quiet_night.py")
TZ = ZoneInfo("America/New_York")

# Session types. budget_share caps one session's cost (--max-budget-usd) as a
# fraction of today's share; work sessions are capped at what's left of it.
RUN_SPECS = {
    "work": {"prompt": "work.md", "model": "sonnet", "effort": "medium", "max_turns": 40, "category": "project",
             "main_kind": "operations"},
    "inbox": {"prompt": "work.md", "model": "sonnet", "effort": "low", "max_turns": 15, "category": "project",
              "main_kind": "operations", "budget_share": 0.05},
    "morning": {"prompt": "morning.md", "model": "haiku", "effort": "low", "max_turns": 12,
                "category": "reports", "budget_share": 0.05},
    "evening": {"prompt": "evening.md", "model": "sonnet", "effort": "low", "max_turns": 20,
                "category": "reports", "budget_share": 0.15},
    "weekly": {"prompt": "evening.md", "model": "sonnet", "effort": "medium", "max_turns": 30,
               "category": "reports", "budget_share": 0.25},
    "final": {"prompt": "evening.md", "model": "opus", "effort": "high", "max_turns": 70,
              "category": "reports", "budget_share": 1.0},
}
CATEGORIES = ("project", "reports", "meetings", "hiring", "talk")
TAGS = {"[meeting]": "meetings", "[hiring]": "hiring", "[diary]": "talk", "[talk]": "talk", "[report]": "reports", "[testimony]": "reports"}
KINDS = ("research", "design", "build", "test", "release", "review", "tools", "plan")
ALL_KINDS = KINDS + ("operations", "other")
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
    "caps": {"reports": 0.03, "meetings": 0.03, "hiring": 0.03, "talk": 0.01},
    "week_anchor": None,
    "rate_limit_until": None,
    "rate_limit_kind": None,
    "fable_blocked_until": None,
    "auth_failed_at": None,
    "days": {},
    "cats": {},
    "kinds": {},
    "models": {},
    "runs": [],
    "plan_cost_total": 0.0,
    "fable_cost_total": 0.0,
    "meter": None,
    "meter_points": [],
    "meter_failed_at": None,
    "estimates": {"week": [], "five": [], "fable": []},
    "credits_on_at": None,
    "api_days": {},
    "api_exhausted_until": None,
    "api_paused_until": None,
    "api_mismatch_at": None,
}
STATE_DEFAULTS = {
    "day1": None,
    "last_morning_date": None,
    "last_evening_date": None,
    "last_evening_at": None,
    "last_work_at": None,
    "last_inbox_at": None,
    "inbox_last_check": "1970-01-01T00:00:00Z",
    "morning_skipped": [],
    "last_backlog_at": None,
    "api_ready": False,
}
BILLING_DEFAULTS = {"api_overflow": False, "monthly_credits_usd": 200.0, "reserve_usd": 10.0, "weekly_cap_usd": 50.0,
                    "cycle_day": 1}
IDLE_MINUTES = 60
BACKLOG_MINUTES = 30   # a refill that leaves the board empty: wait this long before the next
INBOX_MINUTES = 20
BEHIND = 0.85
AUTH_RETRY_MINUTES = 60
MIN_SESSION_USD = 0.50
REPORT_FLOOR_USD = {"morning": 1.0, "evening": 3.0, "weekly": 5.0, "final": 15.0}
API_HEADROOM = 0.8
METER_FRESH_MINUTES = 70
METER_RETRY_HOURS = 6
API_RETRY_MINUTES = 15
TICK_MINUTES = 15
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
AUTH_RE = re.compile(r"not logged in|run /login|invalid api key|oauth token (has )?expired|authentication[_ ]error|authentication_failed", re.I)
CREDIT_RE = re.compile(r"credit balance (is )?too low|insufficient credits?|billing_error|out of credits", re.I)
# Key sources that mean the subscription paid for a run (Agent SDK ApiKeySource).
PLAN_KEY_SOURCES = (None, "", "none", "oauth")
# What the loop was doing in each tick, for the usage page's reasons.
CODE_LABELS = {
    "limit_5h": "at the 5-hour limit",
    "limit_week": "at the weekly limit",
    "logged_out": "logged out of Claude Code",
    "share_spent": "with today's share used up",
    "idle": "with nothing on the board",
    "blocked": "waiting on the Investors, with nothing else on the board",
    "paused": "paused by an Investor",
    "hold": "held for setup",
    "offline": "with the Mac offline or the loop stopped",
}
WORKING_CODES = ("work", "report", "inbox", "backlog")


def load(path, defaults):
    """The file over the defaults. A corrupt file (a half-written save, git conflict markers) falls back
    to its last good copy (path + ".bak"); if both are unreadable the governor stops with an error, so
    the supervisor alerts instead of silently starting over from defaults and losing Day 1."""
    data = json.loads(json.dumps(defaults))
    if not os.path.exists(path):
        return data
    for p in (path, path + ".bak"):
        try:
            with open(p, encoding="utf-8") as f:
                data.update(json.load(f))
            return data
        except (OSError, ValueError):
            continue
    raise SystemExit(f"governor: {os.path.relpath(path, ROOT)} is not valid JSON and has no good backup")


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                json.load(f)
            shutil.copyfile(path, path + ".bak")
        except (OSError, ValueError):
            pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def flag_file(path):
    """A hold, pause, or settings file: its JSON object, {} when it isn't one, None when absent."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def parse_now(value):
    if not value:
        return dt.datetime.now(TZ)
    d = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)
    return d.astimezone(TZ)


def parse_reset(value):
    """A reset time from Claude Code: ISO 8601, or epoch seconds or milliseconds."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            v = float(value)
            return dt.datetime.fromtimestamp(v / 1000.0 if v > 1e12 else v, TZ)
        text = str(value).strip()
        if re.fullmatch(r"\d{9,}(\.\d+)?", text):
            return parse_reset(float(text))
        # Python 3.9 reads only 3 or 6 fraction digits.
        text = re.sub(r"\.(\d+)", lambda f: "." + (f.group(1) + "000000")[:6], text, count=1)
        return parse_now(text)
    except (ValueError, OverflowError, OSError):
        return None


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


# ---------------------------------------------------------------- the plan's own meter

def meter_fresh(usage, now, minutes=METER_FRESH_MINUTES):
    """The latest meter reading if it is recent enough to trust, else None."""
    m = usage.get("meter")
    if not isinstance(m, dict) or not m.get("at"):
        return None
    age = now - parse_now(m["at"])
    if age > dt.timedelta(minutes=minutes) or age < -dt.timedelta(minutes=5):
        return None
    return m


def meter_row(m, which):
    """The meter row for 'session' (the 5-hour window), 'week', or 'fable'."""
    for r in (m or {}).get("limits") or []:
        kind = str(r.get("kind") or "")
        model = str(r.get("model") or "").lower()
        if which == "session" and kind == "session":
            return r
        if which == "week" and kind == "weekly_all":
            return r
        if which == "fable" and kind == "weekly_scoped" and "fable" in model:
            return r
    return None


def meter_pct(m, which):
    r = meter_row(m, which)
    if not r or not isinstance(r.get("percent"), (int, float)):
        return None
    return float(r["percent"])


def same_reset(a, b):
    ra, rb = parse_reset(a), parse_reset(b)
    return ra is not None and rb is not None and abs((ra - rb).total_seconds()) < 600


# ---------------------------------------------------------------- pacing

def pacing(usage, state, now):
    start, end = week_window(usage, state, now)
    used_week = spend_between(usage, start, end)
    budget = float(usage.get("weekly_budget_usd", 150.0))
    # The meter counts everything on the account, interactive sessions included.
    m = meter_fresh(usage, now)
    week_pct = meter_pct(m, "week")
    if week_pct is not None:
        used_week = max(used_week, budget * week_pct / 100.0)
    days_left = max(1, (end.date() - now.date()).days)
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


def kind_shares(usage, now, days=7):
    """Each work kind's share of project spend over the last `days` days."""
    first = now.date() - dt.timedelta(days=days - 1)
    totals = {k: 0.0 for k in ALL_KINDS}
    for day, kinds in usage.get("kinds", {}).items():
        if first <= dt.date.fromisoformat(day) <= now.date():
            for k, v in kinds.items():
                totals[k] = totals.get(k, 0.0) + float(v)
    total = sum(totals.values())
    return total, {k: (round(v / total, 4) if total else 0.0) for k, v in totals.items()}


def window_spend(usage, now, hours):
    """Plan spend in the last `hours`, from the recorded runs."""
    since = now - dt.timedelta(hours=hours)
    return sum(float(r.get("cost_usd", 0.0)) for r in usage.get("runs", [])
               if r.get("billing", "plan") == "plan" and parse_now(r["at"]) > since)


def fable_budget(usage):
    calibrated = usage.get("fable_budget_usd")
    if calibrated:
        return float(calibrated)
    return float(usage.get("fable_fraction", 0.5)) * float(usage.get("weekly_budget_usd", 150.0))


def fable_status(usage, state, now):
    start, end = week_window(usage, state, now)
    spent = model_spend_between(usage, "fable", start, end)
    allowance = fable_budget(usage)
    pct = meter_pct(meter_fresh(usage, now), "fable")
    if pct is not None:
        spent = max(spent, allowance * pct / 100.0)
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


# ---------------------------------------------------------------- API credits (overflow)

def billing_settings():
    b = dict(BILLING_DEFAULTS)
    data = flag_file(BILLING) or {}
    for k in BILLING_DEFAULTS:
        if k in data:
            b[k] = data[k]
    return b


def credit_cycle(now, day):
    """The credit cycle containing `now`: from the last cycle day to the next."""
    day = min(max(int(day or 1), 1), 28)
    d = now.date()
    start = d.replace(day=day) if d.day >= day else (d.replace(day=1) - dt.timedelta(days=1)).replace(day=day)
    y, m = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    return start, dt.date(y, m, day)


def api_status(usage, state, now, ready=None):
    b = billing_settings()
    start, end = credit_cycle(now, b["cycle_day"])
    days = usage.get("api_days") or {}
    month = sum(float(v) for d, v in days.items() if start <= dt.date.fromisoformat(d) < end)
    wstart, wend = week_window(usage, state, now)
    week = sum(float(v) for d, v in days.items() if in_window(d, wstart, wend))
    left_month = float(b["monthly_credits_usd"]) - float(b["reserve_usd"]) - month
    left_week = float(b["weekly_cap_usd"]) - week
    if ready is None:
        ready = bool(state.get("api_ready"))
    blocked = []
    if not b["api_overflow"]:
        blocked.append("switched off in investors/billing.json")
    if not ready:
        blocked.append("no API key in the Keychain")
    if until_active(usage, "api_exhausted_until", now):
        blocked.append("the credits are used up until the next cycle")
    if until_active(usage, "api_paused_until", now):
        blocked.append("an API rate limit; retrying shortly")
    mismatch = usage.get("api_mismatch_at")
    if mismatch and now - parse_now(mismatch) < dt.timedelta(days=7):
        blocked.append("a plan session was billed to an API key; overflow is off until an Investor checks")
    if left_month < MIN_SESSION_USD:
        blocked.append("this cycle's credits are used down to the reserve")
    if left_week < MIN_SESSION_USD:
        blocked.append("this week's overflow cap is used")
    credits = float(b["monthly_credits_usd"]) or 1.0
    return {"ok": not blocked, "blocked": blocked, "enabled": bool(b["api_overflow"]), "ready": bool(ready),
            "month_usd": round(month, 4), "week_usd": round(week, 4),
            "left_month_usd": round(max(0.0, left_month), 4), "left_week_usd": round(max(0.0, left_week), 4),
            "month_pct": round(100.0 * month / credits, 1),
            "week_pct": round(100.0 * week / (float(b["weekly_cap_usd"]) or 1.0), 1),
            "reserve_pct": round(100.0 * float(b["reserve_usd"]) / credits, 1),
            "cycle_start": start.isoformat(), "cycle_end": end.isoformat()}


# ---------------------------------------------------------------- decisions

def session_budget(kind, pace, usage, base=None):
    spec = RUN_SPECS[kind]
    share = pace["today_share_usd"]
    if kind == "work":
        left = share * (1 - pace["reserve_fraction"]) - pace["today_used_usd"]
        cap = max(left, 0.25 * share)
    else:
        cap = spec["budget_share"] * share
    # A report always gets enough to be written, even late in a week whose share is nearly spent.
    cap = max(MIN_SESSION_USD, REPORT_FLOOR_USD.get(kind, 0.0), cap)
    api = (base or {}).get("api")
    if (base or {}).get("billing") == "api" and api:
        # --max-budget-usd can overshoot a little, so credits keep a fifth of their headroom.
        cap = min(cap, API_HEADROOM * api["left_week_usd"], API_HEADROOM * api["left_month_usd"])
    return round(max(MIN_SESSION_USD, cap), 2)


def report_written(started):
    """True when reports/last_report.txt changed after the session started (epoch seconds)."""
    if not started:
        return True
    try:
        return os.path.getmtime(LAST_REPORT) >= float(started) - 5
    except (OSError, ValueError):
        return False


def session(kind, base, pace, usage, **extra):
    return {**base, "run": kind, **RUN_SPECS[kind], "max_budget_usd": session_budget(kind, pace, usage, base), **extra}


def last_tick_time():
    try:
        with open(TICKS, "rb") as f:
            f.seek(max(0, os.path.getsize(TICKS) - 4096))
            tail = f.read().decode("utf-8", "replace").splitlines()
        return parse_now(json.loads(tail[-1])["at"]) if tail else None
    except (OSError, ValueError, KeyError, IndexError):
        return None


def log_outage(start, end):
    """A gap between ticks means the loop was down (the Mac off, offline, asleep): an event for the next report."""
    hours = (end - start).total_seconds() / 3600.0
    entry = {"time": end.isoformat(timespec="seconds"), "worker": "operator", "type": "outage",
             "summary": f"The run loop was down for about {hours_text(hours)}, from {clock(start)} to {clock(end)} "
                        "(no ticks: the Mac was off, offline, asleep, or stuck at the FileVault screen).", "link": ""}
    try:
        os.makedirs(os.path.join(ROOT, "log"), exist_ok=True)
        with open(os.path.join(ROOT, "log", "events.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def log_tick(now, d):
    line = {"at": now.isoformat(timespec="seconds"), "run": d.get("run"), "code": d.get("code") or d.get("run"),
            "billing": d.get("billing", "plan")}
    last = last_tick_time()
    if last is not None and dt.timedelta(minutes=45) < now - last < dt.timedelta(days=14):
        log_outage(last, now)
    try:
        os.makedirs(OPS, exist_ok=True)
        with open(TICKS, "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
        if os.path.getsize(TICKS) > 400_000:
            keep_from = now - dt.timedelta(days=21)
            kept = [t for t in read_ticks() if t.get("at") and parse_now(t["at"]) >= keep_from]
            with open(TICKS, "w", encoding="utf-8") as f:
                f.write("".join(json.dumps(t) + "\n" for t in kept))
    except OSError:
        pass


def read_ticks():
    out = []
    try:
        with open(TICKS, encoding="utf-8") as f:
            for line in f:
                try:
                    t = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(t, dict):
                    out.append(t)
    except OSError:
        pass
    return out


def decide(args):
    now = parse_now(args.now)
    usage = load(USAGE, USAGE_DEFAULTS)
    state = load(STATE, STATE_DEFAULTS)
    dry = bool(getattr(args, "dry_run", False))
    ready = bool(getattr(args, "api_ready", False))
    if close_weeks(usage, state, now) and not dry:
        save(USAGE, usage)
    if not dry and bool(state.get("api_ready")) != ready:
        state["api_ready"] = ready
        save(STATE, state)
    pace = pacing(usage, state, now)
    base = {"now": now.isoformat(), "day": day_number(state, now), "pacing": pace, "backlog": False, "billing": "plan",
            **budget_signals(usage, state, now, pace)}
    d = choose(usage, state, now, pace, base, ready, dry)
    if not dry:
        log_tick(now, d)
    return d


def choose(usage, state, now, pace, base, ready, dry):
    today = now.date().isoformat()
    day = base["day"]
    paused = flag_file(PAUSED)
    if paused is not None:
        who = paused.get("by") or "an Investor"
        return {**base, "run": "hold", "code": "paused",
                "reason": f"paused by {who}; a message that starts with RESUME restarts the company"}
    # A dry run looks past the Day 1 hold, so Day 1 can test the loop while it is held. A hold older
    # than 12 hours is left over from a Day 1 session that didn't finish, and no longer holds.
    if os.path.exists(HOLD) and not dry and time.time() - os.path.getmtime(HOLD) < 12 * 3600:
        return {**base, "run": "hold", "code": "hold", "reason": "ops/hold is set: Day 1 setup is running"}
    auth = usage.get("auth_failed_at")
    if auth and now - parse_now(auth) < dt.timedelta(minutes=AUTH_RETRY_MINUTES):
        return {**base, "run": "queue", "code": "logged_out",
                "reason": "Claude Code is logged out; retrying hourly until an Investor logs in again"}

    # A plan limit pauses Claude sessions; API credits, if allowed, carry on in the meantime.
    if until_active(usage, "rate_limit_until", now):
        code = "limit_week" if usage.get("rate_limit_kind") == "weekly" else "limit_5h"
        api = api_status(usage, state, now, ready)
        if not api["ok"]:
            why = f"; API credits: {api['blocked'][0]}" if api["blocked"] else ""
            return {**base, "run": "queue", "code": code, "api": api, "until": usage["rate_limit_until"],
                    "reason": f"usage limit reached; sessions resume after {usage['rate_limit_until']}{why}"}
        base = {**base, "billing": "api", "fable_ok": False, "api": api, "limit_code": code}

    # Reports first. They are exempt from the daily share but not from a limit (then they use credits).
    if now.hour >= 18 and state.get("last_evening_date") != today:
        kind = "final" if day == 30 else "weekly" if day in (7, 14, 21, 28) else "evening"
        return session(kind, base, pace, usage, code="report", weekly=kind == "weekly", final=kind == "final",
                       questions=True, reason="evening report is due")

    last_evening = state.get("last_evening_at")
    morning_due = (6 <= now.hour < 12 and state.get("last_morning_date") != today
                   and last_evening and parse_now(last_evening).date() < now.date())
    if morning_due:
        if is_quiet(last_evening):
            if not dry:
                state["last_morning_date"] = today
                state.setdefault("morning_skipped", []).append(today)
                save(STATE, state)
            base["morning_skipped"] = True
        else:
            return session("morning", base, pace, usage, code="report", weekly=False, final=False, questions=False,
                           reason="morning report is due and the night was not quiet")

    tasks = open_tasks()
    inbox = os.path.exists(INBOX)
    work_ok = base["billing"] == "api" or pace["work_allowed"]
    last_work = state.get("last_work_at")
    recent = last_work and (now - parse_now(last_work)) < dt.timedelta(minutes=IDLE_MINUTES)
    # An Investor message is answered even when the share is spent or the board is empty: a short session.
    if inbox and (not work_ok or (tasks == 0 and recent)):
        last_inbox = state.get("last_inbox_at")
        if last_inbox and dt.timedelta(0) <= now - parse_now(last_inbox) < dt.timedelta(minutes=INBOX_MINUTES):
            return {**base, "run": "queue", "code": "share_spent" if not work_ok else "idle",
                    "reason": "an Investor message waits for the next short inbox session"}
        return session("inbox", base, pace, usage, code="inbox", weekly=False, final=False, questions=False,
                       open_tasks=tasks, inbox_pending=True, inbox_only=True,
                       reason="an Investor message is waiting: a short session replies")
    if not work_ok:
        return {**base, "run": "queue", "code": "share_spent", "reason": "today's share of the weekly budget is spent"}

    # The company never idles (Tenet 2): an empty board starts a session that refills it. Only when
    # a refill has just run and still left nothing runnable is it waiting on the Investors, whose
    # Urgent Requests that session opened; then the no-Claude queue runs until they answer.
    if tasks == 0 and not inbox:
        last_backlog = state.get("last_backlog_at")
        if last_backlog and dt.timedelta(0) <= now - parse_now(last_backlog) < dt.timedelta(minutes=BACKLOG_MINUTES):
            return {**base, "run": "queue", "code": "blocked",
                    "reason": "the board is still empty after a refill: waiting on the Investors (their open urgent requests say what for)"}
        if not dry:
            state["last_backlog_at"] = now.isoformat()
            save(STATE, state)
        return session("work", base, pace, usage, code="backlog", weekly=False, final=False, questions=False,
                       backlog=True, open_tasks=0, inbox_pending=False,
                       reason="the board is empty: refill it with the most valuable work (Tenet 2)")

    return session("work", base, pace, usage, code="work", weekly=False, final=False, questions=False,
                   open_tasks=tasks, inbox_pending=inbox, inbox_only=False,
                   reason="work session on API credits while the plan's limit resets" if base["billing"] == "api"
                   else "work session")


# ---------------------------------------------------------------- accounting

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


def parse_tags(description):
    """(category or None, kind or None) from the tags that start a worker call's description."""
    d = (description or "").strip().lower()
    lead = re.match(r"^((?:\[[a-z]+\]\s*)+)", d)
    cat = kind = None
    for t in re.findall(r"\[([a-z]+)\]", lead.group(1) if lead else ""):
        tag = "[" + t + "]"
        if cat is None and tag in TAGS:
            cat = TAGS[tag]
        elif kind is None and t in KINDS:
            kind = t
    return cat, kind


def tag_category(description, default):
    return parse_tags(description)[0] or default


def attribute(objs, session_category, session_kind=None):
    """Split usage between categories, work kinds, and model families using stream-json messages.

    Worker messages carry parent_tool_use_id, the id of the Agent call that started them; that
    call's tags decide the category and the work kind. Messages are counted once per message id
    (stream-json repeats a message once per content block). Kinds cover project usage only.
    """
    calls, per_message = {}, {}
    main_kind = session_kind if session_category == "project" else None
    for o in objs:
        if o.get("type") != "assistant":
            continue
        msg = o.get("message") or {}
        parent = o.get("parent_tool_use_id")
        if parent:
            cat, kind = calls.get(parent, (session_category, "other" if session_category == "project" else None))
        else:
            cat, kind = session_category, main_kind
        for block in msg.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task"):
                c, k = parse_tags((block.get("input") or {}).get("description"))
                if parent:
                    c, k = c or cat, k or kind
                else:
                    c = c or session_category
                    k = k or ("other" if c == "project" else None)
                calls[block.get("id")] = (c, k)
        if isinstance(msg.get("usage"), dict):
            per_message[msg.get("id") or id(o)] = (cat, kind, family(msg.get("model")), msg["usage"])
    cats, models, kinds = {}, {}, {}
    for cat, kind, fam, u in per_message.values():
        c = price(fam, u)
        cats[cat] = cats.get(cat, 0.0) + c
        models[fam] = models.get(fam, 0.0) + c
        if cat == "project":
            k = kind or "other"
            kinds[k] = kinds.get(k, 0.0) + c
    return cats, models, kinds


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


def run_signals(objs, result):
    """What the stream says about how a run ended: init facts, error codes, a rejected rate limit."""
    init = next((o for o in objs if o.get("type") == "system" and o.get("subtype") == "init"), {})
    codes, texts, rejected, resets = set(), [], False, None
    for o in objs:
        t = o.get("type")
        if t == "rate_limit_event":
            info = o.get("rate_limit_info") or {}
            if info.get("status") == "rejected":
                rejected = True
                resets = info.get("resetsAt") or resets
                if info.get("errorCode"):
                    codes.add(str(info["errorCode"]))
        elif t == "system" and o.get("subtype") == "api_retry" and o.get("error"):
            codes.add(str(o["error"]))
        elif t == "assistant" and o.get("error"):
            codes.add(str(o["error"]))
    for e in result.get("errors") or []:
        texts.append(str(e))
    status = result.get("api_error_status")
    if status == 429:
        codes.add("rate_limit")
    elif status == 401:
        codes.add("authentication_failed")
    elif status == 402:
        codes.add("billing_error")
    return {"api_key_source": init.get("apiKeySource"), "permission_mode": init.get("permissionMode"),
            "version": init.get("claude_code_version"), "codes": codes, "errors": texts,
            "rejected": rejected, "resets_at": resets}


def record(args):
    now = parse_now(args.now)
    usage = load(USAGE, USAGE_DEFAULTS)
    state = load(STATE, STATE_DEFAULTS)
    billing = getattr(args, "billing", None) or "plan"
    raw, objs, result = read_run(args.run_file)
    if args.result_out:
        with open(args.result_out, "w", encoding="utf-8") as f:
            json.dump(result or {"type": "result", "is_error": True, "subtype": "no_result", "tail": raw[-2000:]}, f, indent=1)
            f.write("\n")
    spec = RUN_SPECS.get(args.type, RUN_SPECS["work"])
    category = spec["category"]
    cats_est, models_est, kinds_est = attribute(objs, category, spec.get("main_kind"))
    est_total = sum(cats_est.values())
    cost = run_cost(result, est_total)
    cats = scale(cats_est, cost) or ({category: cost} if cost else {})
    project = cats.get("project", 0.0)
    kinds = scale(kinds_est, project) or ({spec.get("main_kind") or "other": project} if project else {})
    mu = result.get("modelUsage") or {}
    models = {}
    for m, u in mu.items():
        if isinstance(u, dict):
            c = u.get("costUSD") if isinstance(u.get("costUSD"), (int, float)) else price(family(m), u)
            models[family(m)] = models.get(family(m), 0.0) + c
    models = scale(models, cost) or scale(models_est, cost)

    today = now.date().isoformat()
    add_to(usage.setdefault("cats", {}), today, cats)
    add_to(usage.setdefault("kinds", {}), today, kinds)
    if billing == "api":
        usage.setdefault("api_days", {})[today] = round(float(usage["api_days"].get(today, 0.0)) + cost, 4)
    else:
        usage.setdefault("days", {})[today] = round(float(usage["days"].get(today, 0.0)) + cost, 4)
        add_to(usage.setdefault("models", {}), today, models)
        usage["plan_cost_total"] = round(float(usage.get("plan_cost_total") or 0.0) + cost, 6)
        usage["fable_cost_total"] = round(float(usage.get("fable_cost_total") or 0.0) + models.get("fable", 0.0), 6)

    sig = run_signals(objs, result)
    codes = sig["codes"]
    failed = bool(result.get("is_error")) or not result or args.exit != 0
    # Only Claude Code's own signals decide limits and log-outs: the structured events and the result's
    # error fields. The model's and the tools' text never does: a session that wrote about rate limits
    # before it was stopped hit no limit. Without a result, only the structured events count.
    if result:
        text = " ".join([str(result.get(k, "")) for k in ("error", "subtype", "terminal_reason")] + sig["errors"] + sorted(codes))
        if result.get("is_error"):
            text += " " + str(result.get("result", ""))
    else:
        text = " ".join(sorted(codes))
    limited = failed and (sig["rejected"] or "rate_limit" in codes or "credits_required" in codes or bool(LIMIT_RE.search(text)))
    auth_failed = failed and ("authentication_failed" in codes or bool(AUTH_RE.search(text)))
    credit_out = failed and billing == "api" and ("billing_error" in codes or bool(CREDIT_RE.search(text)))
    fable_only = billing == "plan" and limited and "fable" in text.lower()
    timed_out = args.exit in (124, 137, 143)  # stopped by the supervisor's time limit (SIGTERM, then SIGKILL)
    subtype = str(result.get("subtype", ""))
    terminal = str(result.get("terminal_reason") or "")
    capped = subtype.startswith("error_max") or "budget" in subtype or terminal in ("max_turns", "budget_exhausted")
    source = sig["api_key_source"]
    mismatch = billing == "plan" and source not in PLAN_KEY_SOURCES
    mode_ok = sig["permission_mode"] in (None, "auto")
    if mismatch:
        usage["api_mismatch_at"] = now.isoformat()
    entry = {
        "at": now.isoformat(), "type": args.type, "exit": args.exit, "billing": billing, "cost_usd": round(cost, 4),
        "cats": {k: round(v, 4) for k, v in cats.items()}, "kinds": {k: round(v, 4) for k, v in kinds.items()},
        "models": {k: round(v, 4) for k, v in models.items()},
        "turns": result.get("num_turns"), "duration_ms": result.get("duration_ms"), "subtype": subtype or None,
        "terminal_reason": terminal or None, "is_error": failed, "denials": len(result.get("permission_denials") or []),
        "limited": limited, "auth_failed": auth_failed, "credits_out": credit_out, "timed_out": timed_out,
        "api_key_source": source, "billing_mismatch": mismatch, "permission_mode": sig["permission_mode"],
        "mode_ok": mode_ok, "version": sig["version"],
        "coverage": round(est_total / cost, 2) if cost else None,
        "retry": failed and not (limited or auth_failed or capped or timed_out or credit_out),
        "file": os.path.relpath(args.result_out or args.run_file, ROOT),
    }

    # Spend "this plan week": the pacing window when it is anchored to the plan's reset, else the last 7 days.
    if usage.get("week_anchor"):
        wstart, wend = week_window(usage, state, now)
        in7 = lambda day: in_window(day, wstart, wend)
    else:
        first7 = now.date() - dt.timedelta(days=6)
        in7 = lambda day: first7 <= dt.date.fromisoformat(day) <= now.date()
    m = meter_fresh(usage, now)
    reset_at = parse_reset(sig["resets_at"])
    if billing == "api":
        if credit_out:
            _, cycle_end = credit_cycle(now, billing_settings()["cycle_day"])
            usage["api_exhausted_until"] = dt.datetime.combine(cycle_end, dt.time(0, 0), TZ).isoformat()
            entry["note"] = "API credits used up until the next cycle"
        elif auth_failed:
            usage["api_exhausted_until"] = (now + dt.timedelta(hours=24)).isoformat()
            entry["note"] = "the API key was rejected; overflow is off for 24 hours"
        elif limited:
            usage["api_paused_until"] = (now + dt.timedelta(minutes=API_RETRY_MINUTES)).isoformat()
    elif fable_only:
        row = meter_row(m, "fable")
        until = reset_at or parse_reset((row or {}).get("resets_at")) or (now + dt.timedelta(hours=24))
        usage["fable_blocked_until"] = until.isoformat()
        # The real Fable limit is what was actually spent on Fable when it was reached.
        fable7 = sum(float(x.get("fable", 0.0)) for d, x in usage.get("models", {}).items() if in7(d))
        if fable7 > 0:
            usage["fable_budget_usd"] = round(fable7, 2)
        usage.setdefault("limit_hits", []).append({"at": now.isoformat(), "kind": "fable", "spend_7d_usd": round(fable7, 2)})
    elif limited:
        week_pct = meter_pct(m, "week")
        weekly = "week" in text.lower() or (week_pct is not None and week_pct >= 99)
        row = meter_row(m, "week" if weekly else "session")
        until = reset_at or parse_reset((row or {}).get("resets_at"))
        if until is None or until <= now:
            if weekly:
                until = week_window(usage, state, now)[1] if usage.get("week_anchor") else now + dt.timedelta(hours=24)
            else:
                until = now + dt.timedelta(hours=5)
        usage["rate_limit_until"] = until.isoformat()
        usage["rate_limit_kind"] = "weekly" if weekly else "session"
        spend7 = sum(float(c) for d, c in usage.get("days", {}).items() if in7(d))
        # The real weekly limit is what was spent when it was reached; a figure far below the current
        # budget means the signal was something else, so the budget is left alone.
        if weekly and spend7 >= 0.25 * float(usage.get("weekly_budget_usd") or 150.0):
            usage["weekly_budget_usd"] = round(spend7, 2)
        usage.setdefault("limit_hits", []).append({"at": now.isoformat(), "kind": "weekly" if weekly else "session",
                                                   "spend_7d_usd": round(spend7, 2)})
    entry["pause_until"] = usage.get("rate_limit_until") if limited and billing == "plan" and not fable_only else None
    usage.setdefault("runs", []).append(entry)
    usage["runs"] = usage["runs"][-400:]
    usage["limit_hits"] = usage.get("limit_hits", [])[-50:]
    if not limited and usage.get("rate_limit_until") and parse_now(usage["rate_limit_until"]) <= now:
        usage["rate_limit_until"] = None
        usage["rate_limit_kind"] = None
    if billing == "plan":
        if auth_failed:
            usage["auth_failed_at"] = now.isoformat()
        elif not failed:
            usage["auth_failed_at"] = None
    # A report counts as done only once it was written (reports/last_report.txt moved during the
    # session), or after a second attempt today, so a report cut off by its cap is retried once.
    report = args.type in ("morning", "evening", "weekly", "final")
    if report and (not failed or capped or timed_out):
        attempts = state.setdefault("report_attempts", {})
        key = f"{today} {args.type}"
        attempts[key] = int(attempts.get(key, 0)) + 1
        state["report_attempts"] = {k: v for k, v in attempts.items() if k[:10] >= (now.date() - dt.timedelta(days=3)).isoformat()}
        if not report_written(getattr(args, "started", None)) and attempts[key] < 2:
            entry["note"] = "the report was not written; it is retried at the next tick"
            report = None
    if not failed or capped or timed_out:
        if args.type == "work":
            state["last_work_at"] = now.isoformat()
        elif args.type == "inbox":
            state["last_inbox_at"] = now.isoformat()
        elif args.type == "morning" and report is not None:
            state["last_morning_date"] = today
        elif args.type in ("evening", "weekly", "final") and report is not None:
            state["last_evening_date"] = today
            state["last_evening_at"] = now.isoformat()
    elif args.type == "inbox":
        state["last_inbox_at"] = now.isoformat()
    save(USAGE, usage)
    save(STATE, state)
    print(json.dumps(entry))


# ---------------------------------------------------------------- the meter

def meter(args):
    now = parse_now(args.now)
    usage = load(USAGE, USAGE_DEFAULTS)
    if args.due:
        sys.exit(0 if meter_due(usage, now) else 1)
    if not args.run_file:
        print("meter: a run file or --due is required", file=sys.stderr)
        sys.exit(2)
    raw, objs, result = read_run(args.run_file)
    report = None
    for o in objs:
        r = o.get("usage_report") or (o.get("message") or {}).get("usage_report")
        if isinstance(r, dict):
            report = r
    # /usage is a local command and costs nothing; if it ever reaches the model, count what it spent.
    cost = run_cost(result, 0.0) if result else 0.0
    if cost > 0:
        today = now.date().isoformat()
        usage.setdefault("days", {})[today] = round(float(usage["days"].get(today, 0.0)) + cost, 4)
        add_to(usage.setdefault("cats", {}), today, {"project": cost})
        add_to(usage.setdefault("kinds", {}), today, {"operations": cost})
        usage["plan_cost_total"] = round(float(usage.get("plan_cost_total") or 0.0) + cost, 6)
    limits = ((report or {}).get("rate_limits") or {}).get("limits") if report else None
    if not isinstance(limits, list):
        usage["meter_failed_at"] = now.isoformat()
        save(USAGE, usage)
        print(json.dumps({"ok": False, "reason": "no usage_report in the /usage output", "cost_usd": round(cost, 4)}))
        return
    rows = []
    for r in limits:
        if not isinstance(r, dict):
            continue
        scope = r.get("scope") or {}
        rows.append({"kind": r.get("kind"), "group": r.get("group"),
                     "percent": float(r["percent"]) if isinstance(r.get("percent"), (int, float)) else None,
                     "resets_at": r.get("resets_at"), "severity": r.get("severity"),
                     "model": ((scope.get("model") or {}).get("display_name") or "") if isinstance(scope, dict) else "",
                     "surface": ((scope.get("surface") or {}).get("display_name") or "") if isinstance(scope, dict) else ""})
    extra = ((report.get("rate_limits") or {}).get("extra_usage")) or None
    m = {"at": now.isoformat(), "limits": rows, "extra_usage": extra}
    usage["meter"] = m
    usage["meter_failed_at"] = None
    usage["credits_on_at"] = now.isoformat() if isinstance(extra, dict) and extra.get("is_enabled") else None
    notes = []

    week, session_row, fable = meter_row(m, "week"), meter_row(m, "session"), meter_row(m, "fable")
    # The week follows the plan's own reset.
    wreset = parse_reset((week or {}).get("resets_at"))
    if wreset:
        anchor = (wreset - dt.timedelta(days=7)).replace(second=0, microsecond=0)
        cur = parse_now(usage["week_anchor"]) if usage.get("week_anchor") else None
        if cur is None or abs((cur - anchor).total_seconds()) > 1800:
            usage["week_anchor"] = anchor.isoformat()
            notes.append("week anchored to the plan's reset")
    # Pause before a doomed session, and resume as soon as the plan reopens.
    full = [(r, k) for r, k in ((week, "weekly"), (session_row, "session"))
            if r and isinstance(r.get("percent"), float) and r["percent"] >= 100]
    if full:
        r, k = full[0]
        until = parse_reset(r.get("resets_at")) or now + dt.timedelta(hours=5 if k == "session" else 24)
        if until > now:
            usage["rate_limit_until"] = until.isoformat()
            usage["rate_limit_kind"] = k
            notes.append(f"{k} limit reached; paused until {until.isoformat()}")
    elif until_active(usage, "rate_limit_until", now):
        open_now = all(r is None or r.get("percent") is None or r["percent"] < 98 for r in (week, session_row))
        if open_now and (week or session_row):
            usage["rate_limit_until"] = None
            usage["rate_limit_kind"] = None
            notes.append("the plan's limit has reset: sessions resume")
    if fable and isinstance(fable.get("percent"), float):
        if fable["percent"] >= 100:
            until = parse_reset(fable.get("resets_at")) or now + dt.timedelta(hours=24)
            usage["fable_blocked_until"] = until.isoformat()
        elif fable["percent"] < 98 and until_active(usage, "fable_blocked_until", now):
            usage["fable_blocked_until"] = None
            notes.append("Fable is available again")

    point = {"at": now.isoformat(), "plan_cost": float(usage.get("plan_cost_total") or 0.0),
             "fable_cost": float(usage.get("fable_cost_total") or 0.0),
             "week_pct": (week or {}).get("percent"), "week_reset": (week or {}).get("resets_at"),
             "session_pct": (session_row or {}).get("percent"), "session_reset": (session_row or {}).get("resets_at"),
             "fable_pct": (fable or {}).get("percent"), "fable_reset": (fable or {}).get("resets_at")}
    notes += calibrate(usage, point)
    usage["meter_points"] = (usage.get("meter_points") or [])[-299:] + [point]
    save(USAGE, usage)
    print(json.dumps({"ok": True, "week_pct": point["week_pct"], "session_pct": point["session_pct"],
                      "fable_pct": point["fable_pct"], "credits_on": bool(usage["credits_on_at"]), "notes": notes}))


def meter_due(usage, now):
    failed = usage.get("meter_failed_at")
    if failed and dt.timedelta(0) <= now - parse_now(failed) < dt.timedelta(hours=METER_RETRY_HOURS):
        return False
    auth = usage.get("auth_failed_at")
    if auth and dt.timedelta(0) <= now - parse_now(auth) < dt.timedelta(minutes=AUTH_RETRY_MINUTES):
        return False
    m = usage.get("meter")
    if isinstance(m, dict) and m.get("at") and dt.timedelta(0) <= now - parse_now(m["at"]) < dt.timedelta(minutes=10):
        return False
    return True


def calibrate(usage, point):
    """Turn two meter readings in the same window into a dollar budget: cost between them over
    the change in percent. Each estimate moves the budget at most threefold, and the median of the
    last five estimates is used, so one odd reading (an interactive session) can't throw it off."""
    est = usage.get("estimates") or {}
    usage["estimates"] = est
    notes = []
    pts = usage.get("meter_points") or []
    specs = (("week", "week_pct", "week_reset", "plan_cost", 5.0, "weekly_budget_usd"),
             ("five", "session_pct", "session_reset", "plan_cost", 10.0, "five_hour_budget_usd"),
             ("fable", "fable_pct", "fable_reset", "fable_cost", 5.0, "fable_budget_usd"))
    for name, pct_key, reset_key, cost_key, min_delta, field in specs:
        if point.get(pct_key) is None:
            continue
        value = None
        # The newest reading far enough back: older ones may span the interactive Day 1 session.
        for p in reversed(pts):
            if p.get(pct_key) is None or not same_reset(p.get(reset_key), point.get(reset_key)):
                continue
            dp = point[pct_key] - p[pct_key]
            dc = point[cost_key] - float(p.get(cost_key) or 0.0)
            if dp >= min_delta and dc > 0:
                value = dc / (dp / 100.0)
                break
        if value is None:
            continue
        lst = (est.get(name) or [])[-4:] + [round(value, 2)]
        est[name] = lst
        median = sorted(lst)[len(lst) // 2]
        cur = usage.get(field) or (fable_budget(usage) if field == "fable_budget_usd" else None)
        new = median if not cur else min(max(median, float(cur) / 3.0), float(cur) * 3.0)
        usage[field] = round(new, 2)
        notes.append(f"{field} calibrated to {usage[field]}")
    return notes


# ---------------------------------------------------------------- plan vs actual

def ticks_hours(start, now):
    """Hours spent in each tick code between `start` and `now`, plus hours with no tick at all."""
    hours, first = {}, None
    for t in read_ticks():
        try:
            at = parse_now(t["at"])
        except (KeyError, ValueError):
            continue
        if not (start <= at <= now):
            continue
        first = at if first is None or at < first else first
        code = t.get("code") or t.get("run") or "other"
        if t.get("billing") == "api" and code in WORKING_CODES:
            code = "overflow"
        hours[code] = hours.get(code, 0.0) + TICK_MINUTES / 60.0
    if first is not None:
        span = (now - first).total_seconds() / 3600.0 + TICK_MINUTES / 60.0
        missing = span - sum(hours.values())
        if missing >= 1.0:
            hours["offline"] = missing
    return {k: round(v, 2) for k, v in hours.items()}


def hours_text(h):
    v = round(h * 2) / 2
    return f"{v:g} h"


def plan_status(usage, state, now, pace=None, signals=None):
    """The plan by now against what was used, for the week and today, with the reasons, all in percent."""
    pace = pace or pacing(usage, state, now)
    signals = signals or budget_signals(usage, state, now, pace)
    m = meter_fresh(usage, now)
    start, end = week_window(usage, state, now)
    budget = float(pace["budget_usd"]) or 1.0
    span = (end - start).total_seconds() or 1.0
    week_plan = 100.0 * min(1.0, max(0.0, (now - start).total_seconds() / span))
    week_meter = meter_pct(m, "week")
    week_actual = week_meter if week_meter is not None else 100.0 * pace["used_week_usd"] / budget
    day_start = max(start, dt.datetime.combine(now.date(), dt.time(0, 0), TZ))
    day_end = min(end, day_start + dt.timedelta(days=1))
    day_span = (day_end - day_start).total_seconds() or 1.0
    today_plan = 100.0 * min(1.0, max(0.0, (now - day_start).total_seconds() / day_span))
    share = pace["today_share_usd"]
    today_actual = 100.0 * pace["today_used_usd"] / share if share else 0.0

    def verdict(delta, band):
        return "ahead" if delta > band else "behind" if delta < -band else "on pace"

    five = None
    srow = meter_row(m, "session")
    if srow and srow.get("percent") is not None:
        five = {"actual_pct": round(srow["percent"], 1), "resets_at": srow.get("resets_at"), "source": "meter"}
    elif usage.get("five_hour_budget_usd"):
        five = {"actual_pct": round(100.0 * window_spend(usage, now, 5) / float(usage["five_hour_budget_usd"]), 1),
                "resets_at": None, "source": "estimate"}
    frow = meter_row(m, "fable")
    if frow and frow.get("percent") is not None:
        fable = {"actual_pct": round(frow["percent"], 1), "resets_at": frow.get("resets_at"), "source": "meter"}
    else:
        allowance = signals["fable_allowance_usd"] or 1.0
        fable = {"actual_pct": round(100.0 * signals["fable_week_usd"] / allowance, 1), "resets_at": None,
                 "source": "estimate"}

    week_delta = week_actual - week_plan
    hours = ticks_hours(start, now)
    reasons = current_reasons(usage, state, now, pace, signals)
    lost = sorted(((h, c) for c, h in hours.items() if c not in WORKING_CODES and c != "overflow" and h >= 0.5),
                  reverse=True)
    if week_delta < -5:
        reasons += [f"{hours_text(h)} this week {CODE_LABELS.get(c, c)}." for h, c in lost[:3]]
    elif week_delta > 5:
        if signals.get("upgrade"):
            reasons.append("The week was behind earlier, so Haiku and Sonnet work moved up a model.")
        week_models = {}
        for d, ms in usage.get("models", {}).items():
            if in_window(d, start, end):
                for k, v in ms.items():
                    week_models[k] = week_models.get(k, 0.0) + float(v)
        total = sum(week_models.values())
        if total and week_models.get("fable", 0.0) / total > 0.25:
            reasons.append(f"Fable did {week_models['fable'] / total:.0%} of this week's work.")
        if not reasons:
            reasons.append("More work ran early in the week than an even pace would.")
    if hours.get("overflow"):
        reasons.append(f"{hours_text(hours['overflow'])} this week ran on API credits while the plan was paused.")
    return {"source": "meter" if week_meter is not None else "estimate", "meter_at": (m or {}).get("at"),
            "week": {"actual_pct": round(week_actual, 1), "plan_pct": round(week_plan, 1),
                     "delta_pts": round(week_delta, 1), "status": verdict(week_delta, 5.0),
                     "resets_at": (meter_row(m, "week") or {}).get("resets_at") or end.isoformat()},
            "today": {"actual_pct": round(today_actual, 1), "plan_pct": round(today_plan, 1),
                      "delta_pts": round(today_actual - today_plan, 1), "status": verdict(today_actual - today_plan, 10.0),
                      "reserve_pct": round(100.0 * (1 - pace["reserve_fraction"]), 1),
                      "share_of_week_pct": round(100.0 * share / budget, 1)},
            "five_hour": five, "fable": fable, "reasons": reasons, "hours": hours,
            "credits_on": bool(usage.get("credits_on_at"))}


def clock(when):
    return f"{when:%a} {int(when.strftime('%I'))}:{when:%M %p}"


def current_reasons(usage, state, now, pace, signals):
    out = []
    paused = flag_file(PAUSED)
    if paused is not None:
        out.append(f"Paused by {paused.get('by') or 'an Investor'}; nothing runs until a message that starts with RESUME.")
    elif os.path.exists(HOLD):
        out.append("Held for Day 1 setup.")
    if until_active(usage, "rate_limit_until", now):
        until = parse_now(usage["rate_limit_until"])
        which = "weekly" if usage.get("rate_limit_kind") == "weekly" else "5-hour"
        out.append(f"At the {which} limit until {clock(until)}.")
    auth = usage.get("auth_failed_at")
    if auth and now - parse_now(auth) < dt.timedelta(hours=3):
        out.append("Claude Code is logged out; an Investor has to log in again.")
    if not pace["work_allowed"] and not until_active(usage, "rate_limit_until", now):
        out.append("Today's share is used; work waits for tomorrow's share, while reports and replies still run.")
    if open_tasks() == 0:
        out.append("The board has no open tasks.")
    if signals.get("upgrade"):
        out.append("Behind pace, so Haiku and Sonnet work moves up a model.")
    if usage.get("credits_on_at"):
        out.append("Usage credits are switched on in the plan: at a limit, Claude would bill real money.")
    return out


# ---------------------------------------------------------------- commands

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
    """The Usage section of a report: each window the plan meters as a share of its limit, the plan
    by now, why the week is ahead or behind, and the splits by model and by kind of work.

    Percentages only: the plan's limits are percentages, and the dollar figures are only the
    governor's internal unit for pacing."""
    now = parse_now(args.now)
    usage = load(USAGE, USAGE_DEFAULTS)
    state = load(STATE, STATE_DEFAULTS)
    pace = pacing(usage, state, now)
    signals = budget_signals(usage, state, now, pace)
    ps = plan_status(usage, state, now, pace, signals)
    start, end = week_window(usage, state, now)
    by_model = {}
    for day, models in usage.get("models", {}).items():
        if in_window(day, start, end):
            for k, v in models.items():
                by_model[k] = by_model.get(k, 0.0) + float(v)
    total_week = sum(by_model.values()) or pace["used_week_usd"]
    reset = parse_reset(ps["week"]["resets_at"]) or end
    reset_text = f"{reset:%a %b} {reset.day}, {int(reset.strftime('%I'))}:{reset:%M %p}"
    five = ps["five_hour"]
    five_text = "not calibrated yet"
    if five:
        five_text = f"{five['actual_pct'] / 100:.0%} of the 5-hour limit"
        r5 = parse_reset(five.get("resets_at"))
        if r5:
            five_text += f" (resets {int(r5.strftime('%I'))}:{r5:%M %p})"
    wk, td, fb = ps["week"], ps["today"], ps["fable"]
    lines = ["| Window | Used | Plan by now |", "| --- | --- | --- |",
             f"| Last 5 hours | {five_text} | |",
             f"| Today | {td['actual_pct'] / 100:.0%} of the daily pace | {td['plan_pct'] / 100:.0%} |",
             f"| This week | {wk['actual_pct'] / 100:.0%} of the weekly limit (resets {reset_text}) | {wk['plan_pct'] / 100:.0%} |",
             f"| Fable this week | {fb['actual_pct'] / 100:.0%} of its weekly allowance | |"]
    delta = wk["delta_pts"]
    pace_line = ("On pace for the week." if wk["status"] == "on pace"
                 else f"{abs(delta):.0f} points {'behind' if wk['status'] == 'behind' else 'ahead of'} the week's even pace.")
    if ps["reasons"]:
        pace_line += " Why: " + " ".join(ps["reasons"])
    lines += ["", pace_line + (" (Source: the plan's own meter.)" if ps["source"] == "meter" else " (Source: the governor's estimate.)")]
    lines += ["", "| Model | Share of this week's usage |", "| --- | --- |"]
    for k in ("fable", "opus", "sonnet", "haiku"):
        v = by_model.get(k, 0.0)
        lines.append(f"| {k.capitalize()} | {v / total_week:.0%} |" if total_week else f"| {k.capitalize()} | 0% |")
    ktotal, kshares = kind_shares(usage, now)
    if ktotal:
        parts = [f"{k} {kshares[k]:.0%}" for k in sorted(kshares, key=lambda x: -kshares[x]) if kshares[k] >= 0.01]
        lines += ["", "Product work by kind, last 7 days: " + ", ".join(parts) + "."]
    api = api_status(usage, state, now)
    if api["month_usd"] > 0:
        lines += ["", f"API credits this cycle: {api['month_pct'] / 100:.0%} of the included credits used, as overflow while the plan was paused."]
    if ps["credits_on"]:
        lines += ["", "Warning: usage credits are switched on in the plan, so a limit would bill real money."]
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
    usage["rate_limit_kind"] = "session"
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
        for k, v in models.items():
            by_model[k] = by_model.get(k, 0.0) + float(v)
    five_h = window_spend(usage, now, 5)
    five_budget = usage.get("five_hour_budget_usd")
    ktotal, kshares = kind_shares(usage, now)
    ps = plan_status(usage, state, now, pace, signals)
    api = api_status(usage, state, now)
    paused = flag_file(PAUSED)
    wstart, wend = week_window(usage, state, now)
    week_models = {}
    for day, models in usage.get("models", {}).items():
        if in_window(day, wstart, wend):
            for k, v in models.items():
                week_models[k] = round(week_models.get(k, 0.0) + float(v), 4)
    out = {"now": now.isoformat(), "day": day_number(state, now), "pacing": pace, **signals,
           "window_5h_usd": round(five_h, 4), "five_hour_budget_usd": five_budget,
           "window_5h_share": round(five_h / float(five_budget), 4) if five_budget else None,
           "caps": effective_caps(usage), "all_time_by_category_usd": {k: round(v, 2) for k, v in totals.items()},
           "all_time_by_model_usd": {k: round(v, 2) for k, v in by_model.items()},
           "kinds_7d": kshares, "kinds_7d_usd": round(ktotal, 4), "week_models": week_models,
           "plan": ps, "api": api, "meter": usage.get("meter"),
           "weeks": usage.get("weeks", [])[-5:], "limit_hits": usage.get("limit_hits", [])[-5:],
           "rate_limit_until": usage.get("rate_limit_until"), "rate_limit_kind": usage.get("rate_limit_kind"),
           "auth_failed_at": usage.get("auth_failed_at"),
           "paused": paused, "hold": os.path.exists(HOLD),
           "open_tasks": open_tasks(), "inbox_pending": os.path.exists(INBOX)}
    if args.json:
        print(json.dumps(out, indent=2))
        return
    print(f"Now {now:%Y-%m-%d %H:%M %Z}, Day {out['day']}")
    print(f"Week {pace['week_start'][:10]} to {pace['week_end'][:10]}: used ${pace['used_week_usd']:.2f} of ${pace['budget_usd']:.2f}; "
          f"today ${pace['today_used_usd']:.2f} of share ${pace['today_share_usd']:.2f}; work allowed: {pace['work_allowed']}")
    wk = ps["week"]
    print(f"Plan by now {wk['plan_pct']:.0f}% of the week, used {wk['actual_pct']:.0f}% ({wk['status']}, source: {ps['source']})"
          + (f"; why: {' '.join(ps['reasons'])}" if ps["reasons"] else ""))
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
    if ktotal:
        print("Last 7 days by kind of product work: " + ", ".join(f"{k} {kshares[k]:.0%}" for k in ALL_KINDS if kshares.get(k)))
    print(f"API credits this cycle: ${api['month_usd']:.2f} of ${api['month_usd'] + api['left_month_usd']:.2f} usable "
          f"(this week ${api['week_usd']:.2f}); overflow {'ready' if api['ok'] else 'off: ' + '; '.join(api['blocked'])}")
    print(f"Limit pause until: {usage.get('rate_limit_until')}; logged out since: {usage.get('auth_failed_at')}; "
          f"open tasks: {out['open_tasks']}; inbox pending: {out['inbox_pending']}; paused: {paused is not None}; hold: {out['hold']}")
    for r in usage.get("runs", [])[-5:]:
        print(f"  {r['at'][:16]} {r['type']:8s} {r.get('billing', 'plan'):4s} ${r['cost_usd']:.3f} turns={r.get('turns')} "
              f"exit={r.get('exit')} limited={r['limited']} {' '.join(f'{k}=${v:.3f}' for k, v in (r.get('cats') or {}).items())}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("decide"); s.add_argument("--now"); s.add_argument("--api-ready", action="store_true")
    s.add_argument("--dry-run", action="store_true"); s.set_defaults(fn=decide)
    s = sub.add_parser("record"); s.add_argument("run_file"); s.add_argument("--type", required=True)
    s.add_argument("--exit", type=int, default=0); s.add_argument("--result-out"); s.add_argument("--now")
    s.add_argument("--billing", choices=("plan", "api"), default="plan")
    s.add_argument("--started", type=float, help="epoch seconds when the session started (reports)")
    s.set_defaults(fn=record)
    s = sub.add_parser("meter"); s.add_argument("run_file", nargs="?"); s.add_argument("--due", action="store_true")
    s.add_argument("--now"); s.set_defaults(fn=meter)
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
