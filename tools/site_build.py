#!/usr/bin/env python3
"""Build the public site from the company's records. No Claude, no dependencies.

  python3 tools/site_build.py --out ../site        # write the Jekyll source into the site repo
  python3 tools/site_build.py --out /tmp/site --no-gh

The output is a Jekyll site that GitHub Pages renders on push. It is rebuilt from
scratch on every run (everything in --out except .git and CNAME is replaced). Every
chart, bar, and portrait is inline SVG drawn here by code (Commandment 9); moods are words, color-coded.

What it reads (the data contract; the Handbook may add fields but not rename these):
  site.json                 company name, tagline, repo, site URL, options
  reports/*.md              the public report, without its questions; front matter: title, number,
                            day, date, time, kind, issue; optionally revenue_usd, spent_usd
  story/**/*.md             front matter: title, date, time, kind, workers (comma list);
                            a diary also carries mood (1-5), feeling (one word), and mood_reason
  personnel/registry.json   [{name, role, manager, status (active|candidate|former), salary,
                            career_goal, joined, left, bio, temperament, round}]
  personnel/portraits/*.svg the still portraits (tools/portrait.py draws the animated ones here)
  .claude/agent-memory/<name>/MEMORY.md   what each worker remembers (published if publish_memory)
  log/events.jsonl          {time, worker, type, summary, link}
  ops/scoreboard.json       {revenue_usd, spent_usd, day, days_left, app_name, app_store_url, status,
                            stage, launched, history: [{date, revenue_usd, spent_usd}]}
  ops/usage.json            through tools/governor.py status --json and report-usage
  site/pages/*.md           about, privacy, support, press: copied with a layout
  gh (optional)             open issues in the company repo, for the Requests page

Everything published is scrubbed: links into the private company repository become
"(private)", and anything that looks like a token or key is removed (Commandment 42).
Company-owned; the company may improve it under Commandment 3.
"""
import argparse
import datetime as dt
import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)
from portrait import portrait_svg, default_temperament, assign_variants, params as portrait_params, TEMPERAMENTS  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

TZ = ZoneInfo("America/New_York")

DEFAULT_SITE = {
    "name": "The Company",
    "tagline": "An AI-run company with 30 days to build and sell an iOS app.",
    "company_repo": "",          # "org/company": enables the Requests page and the message link
    "url": "",                    # "https://org.github.io/site"
    "publish_memory": True,
    "log_rows": 500,
    "goal_usd": 200,
    "days_total": 30,
    "disclosure": "Everyone who works here is an AI-simulated character. The business is real and is an "
                  "experiment run by two private individuals. Every report is true to the operational log.",
}
EVENT_LIMIT_PER_WORKER = 200
STAGES = [("research", "Research"), ("pitch", "The Pitch"), ("build", "Build"), ("review", "App Review"),
          ("launch", "Launch"), ("selling", "Selling")]
MOOD_WORDS = {1: "struggling", 2: "low", 3: "steady", 4: "good", 5: "great"}
CATEGORY_LABELS = [("project", "product work"), ("reports", "reports"), ("meetings", "meetings"),
                   ("hiring", "hiring"), ("talk", "small talk")]
STATUS_GROUPS = (("active", "Working here now"), ("candidate", "Considered, not hired"), ("former", "Former workers"))


# ---------- small helpers ----------

def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def front_matter(text):
    """Return (meta dict, body) for a file with a simple key: value front matter block."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n---", 1)
    if len(parts) < 2:
        return {}, text
    meta = {}
    for line in parts[0].splitlines()[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip().strip('"').strip("'")
    return meta, parts[1].lstrip("\n")


def fm(meta):
    lines = ["---"]
    for k, v in meta.items():
        if v is None or v == "":
            continue
        v = json.dumps(v) if isinstance(v, (list, dict)) else json.dumps(str(v))
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "page"


SECRET_RE = re.compile(r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|AuthKey_[A-Z0-9]+\.p8|"
                       r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----)")


def scrubber(cfg):
    repo = cfg.get("company_repo") or ""
    private = re.compile(r"https?://github\.com/" + re.escape(repo) + r"[^\s)\]>\"']*") if repo else None

    def scrub(text):
        text = SECRET_RE.sub("[removed]", text)
        if private:
            text = private.sub("(private)", text)
        return text
    return scrub


def raw(body):
    """Keep Jekyll's Liquid from interpreting anything in company-written text."""
    return "{% raw %}\n" + body.rstrip() + "\n{% endraw %}\n"


def when(meta, default_time="00:00"):
    return f"{meta.get('date', '1970-01-01')} {meta.get('time', default_time)}"


def esc(s):
    return html.escape(str(s), quote=False)


def cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def fmt_time(iso):
    try:
        d = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return f"{d:%b} {d.day}, {d:%H:%M}"
    except ValueError:
        return str(iso)[:16]


def num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def run(cmd, timeout=60):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def rel(path):
    return "{{ '" + path + "' | relative_url }}"


# ---------- drawing (inline SVG and HTML, no scripts) ----------

def state_class(share):
    return "hot" if share >= 0.9 else "warm" if share >= 0.7 else "ok"


def bar(label, value, maxv, note="", fmt="${:,.2f}", cls=None):
    """A labelled progress bar. value/maxv as numbers; note replaces the right-hand text."""
    share = (value / maxv) if maxv else 0.0
    width = max(0.0, min(1.0, share)) * 100
    cls = cls or state_class(share)
    right = note if note else (f"{fmt.format(value)} of {fmt.format(maxv)}" if maxv else fmt.format(value))
    pct = f" · {share:.0%}" if maxv and note != " " else ""
    return (f'<div class="bar {cls}"><div class="bar-head"><span>{esc(label)}</span><span>{esc(right.strip())}{pct}</span></div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{width:.1f}%"></div></div></div>')


def mood_chip(level, word=None, reason=None, big=False):
    """The worker's own feeling as a color-coded word, then the reason. Level 1..5 sets the color."""
    known = level in (1, 2, 3, 4, 5)
    lv = level if known else 0
    text = (word or MOOD_WORDS.get(level) or "no mood recorded yet")
    text = text[:1].upper() + text[1:]
    out = f'<span class="mood-word lv{lv}{" big" if big else ""}">{esc(text)}</span>'
    if reason:
        out += f' <span class="mood-why">\u2013 {esc(reason)}</span>'
    return out


def sparkline(values, width=160, height=36, lo=1, hi=5):
    if len(values) < 2:
        return ""
    step = width / (len(values) - 1)
    pts = [(i * step, height - 4 - (v - lo) / (hi - lo) * (height - 8)) for i, v in enumerate(values)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    lx, ly = pts[-1]
    return (f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" aria-hidden="true">'
            f'<polyline points="{line}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"/>'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3" fill="var(--accent)"/></svg>')


def pipeline(stage):
    keys = [k for k, _ in STAGES]
    cur = keys.index(stage) if stage in keys else 0
    items = []
    for i, (k, label) in enumerate(STAGES):
        cls = "done" if i < cur else "now" if i == cur else "todo"
        items.append(f'<li class="{cls}"><span class="dot"></span><span class="lbl">{label}</span></li>')
    return '<ol class="pipe">' + "".join(items) + "</ol>"


def day_track(day, total=30, launched_day=None):
    cells = []
    for d in range(1, total + 1):
        cls = "past" if d < day else "now" if d == day else "todo"
        if launched_day and d == launched_day:
            cls += " launch"
        cells.append(f'<i class="{cls}" title="Day {d}"></i>')
    return f'<div class="track" aria-label="Day {day} of {total}">{"".join(cells)}</div>'


def revenue_chart(history, goal, days_total=30, day1=None, width=640, height=220):
    """Net proceeds by day against the goal line. history: [{date, revenue_usd}], day1: date or None."""
    pts = []
    for h in history:
        d = h.get("day")
        if d is None and day1 and h.get("date"):
            try:
                d = (dt.date.fromisoformat(h["date"]) - day1).days + 1
            except ValueError:
                d = None
        if d is not None:
            pts.append((int(d), num(h.get("revenue_usd"))))
    pts.sort()
    top = max(goal * 1.15, max((v for _, v in pts), default=0) * 1.1, 1)
    L, R, T, B = 44, 12, 12, 28
    x = lambda d: L + (d - 1) / (days_total - 1) * (width - L - R)  # noqa: E731
    y = lambda v: T + (1 - v / top) * (height - T - B)  # noqa: E731
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="net proceeds by day">']
    out.append(f'<line x1="{L}" y1="{y(goal):.1f}" x2="{width - R}" y2="{y(goal):.1f}" stroke="var(--accent)" stroke-dasharray="4 4" opacity=".7"/>')
    out.append(f'<text x="{width - R}" y="{y(goal) - 5:.1f}" text-anchor="end" class="lbl">goal ${goal:,.0f}</text>')
    for d in (1, 10, 20, days_total):
        anchor = "start" if d == 1 else "end" if d == days_total else "middle"
        out.append(f'<text x="{x(d):.1f}" y="{height - 8}" text-anchor="{anchor}" class="lbl">Day {d}</text>')
    for v in (0, goal / 2, goal):
        out.append(f'<text x="{L - 6}" y="{y(v) + 4:.1f}" text-anchor="end" class="lbl">${v:,.0f}</text>')
    out.append(f'<line x1="{L}" y1="{y(0):.1f}" x2="{width - R}" y2="{y(0):.1f}" stroke="var(--line)"/>')
    if pts:
        poly = " ".join(f"{x(d):.1f},{y(v):.1f}" for d, v in pts)
        area = f"{x(pts[0][0]):.1f},{y(0):.1f} " + poly + f" {x(pts[-1][0]):.1f},{y(0):.1f}"
        out.append(f'<polygon points="{area}" fill="var(--accent)" opacity=".12"/>')
        out.append(f'<polyline points="{poly}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linejoin="round"/>')
        d, v = pts[-1]
        out.append(f'<circle cx="{x(d):.1f}" cy="{y(v):.1f}" r="4" fill="var(--accent)"/>'
                   f'<text x="{x(d):.1f}" y="{y(v) - 9:.1f}" text-anchor="middle" class="lbl strong">${v:,.2f}</text>')
    out.append("</svg>")
    return "".join(out)


def stacked(shares, caps):
    """Horizontal stacked bar of the 7-day category shares, with a legend."""
    segs, legend = [], []
    for k, label in CATEGORY_LABELS:
        v = max(0.0, num(shares.get(k)))
        if v > 0:
            segs.append(f'<i class="seg {k}" style="width:{v * 100:.1f}%" title="{label} {v:.1%}"></i>')
        cap = f" (cap {caps[k] * 100:.0f}%)" if k in caps else ""
        legend.append(f'<span><i class="seg {k}"></i>{label} {v:.1%}{cap}</span>')
    return f'<div class="stack">{"".join(segs)}</div><div class="legend">{"".join(legend)}</div>'


def event_time(e):
    try:
        d = dt.datetime.fromisoformat(str(e.get("time", "")).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=TZ)).astimezone(TZ).replace(tzinfo=None)
    except ValueError:
        return None


def when_time(s):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


REPORT_GRACE = dt.timedelta(minutes=90)
PEOPLE_TYPES = {"hire": "joined", "departure": "left", "promotion": "promoted", "demotion": "demoted", "pay": "pay change", "review": "reviewed"}
MILESTONE_TYPES = ("hire", "departure", "promotion", "decision", "pitch", "build", "submit", "release", "launch", "sale", "review", "amendment")


def rail(events, by_slug, limit=40):
    """A vertical timeline of events, oldest first, each with time, worker, type, and summary."""
    rows = list(reversed(events[:limit]))
    if not rows:
        return '<p class="mood-why">Nothing was logged in this period.</p>'
    out = ['<ol class="rail">']
    for e in rows:
        wslug = str(e.get("worker", "")).lower()
        who = f'<a href="{rel("/cast/" + wslug + ".html")}">{esc(by_slug[wslug]["name"])}</a>' if wslug in by_slug else esc(e.get("worker", ""))
        link = f' <a href="{esc(e["link"])}">link</a>' if e.get("link") and e["link"] != "(private)" else ""
        t = event_time(e)
        out.append(f'<li class="t-{esc(e.get("type", ""))}"><time>{t.strftime("%a %H:%M") if t else ""}</time>'
                   f'<span class="tag t-{esc(e.get("type", ""))}">{esc(e.get("type", ""))}</span> <b>{who}</b> {esc(e.get("summary", ""))}{link}</li>')
    out.append("</ol>")
    return "".join(out)


def daily_bars(days, values, share, width=640, height=90):
    """Spend per day as bars against the daily share line."""
    if not days:
        return ""
    top = max(max(values), share, 1.0) * 1.15
    L, R, T, B = 36, 8, 8, 22
    bw = (width - L - R) / len(days)
    y = lambda v: T + (1 - v / top) * (height - T - B)  # noqa: E731
    out = [f'<svg class="chart small" viewBox="0 0 {width} {height}" role="img" aria-label="Claude usage by day">']
    out.append(f'<line x1="{L}" y1="{y(share):.1f}" x2="{width - R}" y2="{y(share):.1f}" stroke="var(--accent)" stroke-dasharray="4 4" opacity=".7"/>')
    out.append(f'<text x="{L - 4}" y="{y(share) + 4:.1f}" text-anchor="end" class="lbl">1/7</text>')
    for i, (d, v) in enumerate(zip(days, values)):
        x0 = L + i * bw + bw * 0.15
        cls = state_class(v / share if share else 0)
        out.append(f'<rect x="{x0:.1f}" y="{y(v):.1f}" width="{bw * 0.7:.1f}" height="{y(0) - y(v):.1f}" rx="2" class="d-{cls}"><title>{d}: ${v:,.2f}</title></rect>')
        if i % max(1, len(days) // 7) == 0 or i == len(days) - 1:
            out.append(f'<text x="{x0 + bw * 0.35:.1f}" y="{height - 6}" text-anchor="middle" class="lbl">{d[5:]}</text>')
    out.append("</svg>")
    return "".join(out)


def people_strip(events, by_slug, variants):
    items = []
    for e in reversed(events):
        t = str(e.get("type", "")).lower()
        if t not in PEOPLE_TYPES:
            continue
        wslug = str(e.get("worker", "")).lower()
        name = by_slug[wslug]["name"] if wslug in by_slug else e.get("worker", "")
        img = f'<img src="{rel("/assets/portraits/" + wslug + ".svg")}" alt="">' if wslug in by_slug else ""
        items.append(f'<a class="person" href="{rel("/cast/" + wslug + ".html")}">{img}<b>{esc(name)}</b><small>{PEOPLE_TYPES[t]}</small></a>')
    return f'<div class="people">{"".join(items)}</div>' if items else ""


def mood_list(story, by_slug, start, end):
    items = []
    for s_ in sorted(story, key=lambda m: m["when"]):
        t = when_time(s_["when"])
        if s_.get("kind") != "diary" or s_.get("mood") is None or not t or not (start < t <= end):
            continue
        for w in s_["workers"]:
            name = by_slug[w]["name"] if w in by_slug else w
            items.append(f'<li><a href="{rel("/cast/" + w + ".html")}">{esc(name)}</a>: {mood_chip(s_["mood"], s_.get("feeling"), s_["mood_reason"])} '
                         f'<a class="mood-why" href="{rel("/story/" + s_["path"] + ".html")}">diary</a></li>')
    return f'<ul class="moods">{"".join(items)}</ul>' if items else ""


def small_multiples(workers, moods, start_day, end_day, day_of):
    """One sparkline per active worker over a day range (mood by day)."""
    cards = []
    for w in workers:
        pts = [(day_of(m[0]), m[1]) for m in moods.get(w["slug"], []) if start_day <= day_of(m[0]) <= end_day]
        if len(pts) < 2:
            continue
        vals = [v for _, v in pts]
        last = moods[w["slug"]][-1]
        cards.append(f'<div class="mini"><b>{esc(w["name"])}</b> {mood_chip(last[1], last[3])}{sparkline(vals, 120, 30)}</div>')
    return f'<div class="minis">{"".join(cards)}</div>' if cards else ""


# ---------- navigation and page structure ----------

REPORT_KINDS = {"morning": ("Morning", "amber"), "evening": ("Evening", "blue"), "weekly": ("Weekly", "green"), "final": ("Final", "pink")}
RECORD_KINDS = {"diary": ("Diary", "pink"), "meeting": ("Meeting", "amber"), "chat": ("Conversation", "green"),
                "interview": ("Interview", "blue"), "memo": ("Memo", "grey"), "testimony": ("Testimony", "blue")}
STATUS_BADGES = {"active": ("Working here", "green"), "candidate": ("On the bench", "grey"), "former": ("Former worker", "grey")}


def safe(s):
    """Escape company-written text for HTML that Jekyll's Liquid also reads, so braces stay text."""
    return esc(s).replace("{", "&#123;").replace("}", "&#125;")


def badge(label, tone):
    return f'<span class="kind {tone}">{esc(label)}</span>'


def report_badge(kind, suffix=""):
    label, tone = REPORT_KINDS.get(kind, (str(kind or "report").title(), "grey"))
    return badge(label + suffix, tone)


def record_badge(kind):
    label, tone = RECORD_KINDS.get(kind, (str(kind or "record").title(), "grey"))
    return badge(label, tone)


def crumbs(back_path, back_label, right=""):
    """The back link at the top of a page inside a section, with optional links on the right."""
    return (f'<div class="crumbs" role="navigation" aria-label="Back"><a class="back" href="{rel(back_path)}">'
            f'← {safe(back_label)}</a>{right}</div>\n')


def page_head(kicker, title, sub=""):
    return f'<div class="page-head"><div class="kicker">{kicker}</div><h1>{title}</h1>{sub}</div>'


def split_title(title):
    """'Report 6 — Hana joins' gives ('Report 6', 'Hana joins'); a title without a dash is all headline."""
    parts = re.split(r"\s+[—–-]\s+", str(title), maxsplit=1)
    lead, head = (parts[0], parts[1]) if len(parts) == 2 else ("", parts[0])
    return lead, head[:1].upper() + head[1:]


def nice_date(date_s):
    try:
        d = dt.date.fromisoformat(str(date_s)[:10])
    except ValueError:
        return str(date_s)
    return f"{d:%a} {d:%b} {d.day}"


def excerpt(body, limit=170):
    """The first plain paragraph of a report's Summary (or of the report), as one line of text."""
    m = re.search(r"^#{2,}\s*Summary\s*$", body, flags=re.M | re.I)
    text = body[m.end():] if m else body
    for para in re.split(r"\n\s*\n", text):
        p = para.strip()
        if not p or p.startswith(("#", "|", ">", "<", "```", "{%")) or re.match(r"([-*+]|\d+\.)\s", p):
            continue
        p = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", p)
        p = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", p)
        p = re.sub(r"<[^>]+>|[*_`]", "", p)
        p = re.sub(r"\s+", " ", p).strip()
        if len(p) > limit:
            p = p[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
        return p
    return ""


def avatars(slugs, by_slug, cls="avatar"):
    out = []
    for slug in slugs:
        if slug in by_slug:
            n = esc(by_slug[slug]["name"])
            out.append(f'<img class="{cls}" src="{rel("/assets/portraits/" + slug + ".svg")}" alt="{n}" title="{n}">')
    return "".join(out)


def person_chips(slugs, by_slug):
    items = []
    for slug in slugs:
        if slug in by_slug:
            w = by_slug[slug]
            items.append(f'<a class="person" href="{rel("/cast/" + slug + ".html")}"><img src="{rel("/assets/portraits/" + slug + ".svg")}" alt="">'
                         f'<b>{esc(w["name"])}</b><small>{safe(w.get("role", ""))}</small></a>')
        else:
            items.append(f'<span class="person"><b>{esc(slug)}</b></span>')
    return f'<div class="people">{"".join(items)}</div>' if items else ""


def scorecard_mean(body):
    """The mean of the numeric scores in a record's '## Scorecard' table, or None."""
    m = re.search(r"^##\s+Scorecard\s*$", body, flags=re.M | re.I)
    if not m:
        return None
    scores = []
    for line in body[m.end():].splitlines():
        line = line.strip()
        if not line.startswith("|"):
            if scores:
                break
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        mm = re.fullmatch(r"(\d+(?:\.\d+)?)(?:\s*/\s*\d+)?", cells[-1]) if cells else None
        if mm:
            scores.append(float(mm.group(1)))
    return sum(scores) / len(scores) if scores else None


# ---------- readers ----------

def load_config():
    cfg = dict(DEFAULT_SITE)
    p = os.path.join(ROOT, "site.json")
    if os.path.exists(p):
        try:
            cfg.update(json.loads(read(p)))
        except json.JSONDecodeError:
            print("site.json is not valid JSON; using defaults", file=sys.stderr)
    return cfg


def load_reports(scrub):
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "reports", "*.md"))):
        meta, body = front_matter(read(path))
        if not meta.get("date"):
            continue
        meta.setdefault("title", os.path.basename(path)[:-3])
        meta["slug"] = slugify(f"{meta['date']}-{meta.get('time', '0000').replace(':', '')}-{meta.get('kind', 'report')}")
        meta["when"] = when(meta)
        meta["body"] = scrub(body)
        out.append(meta)
    out.sort(key=lambda m: m["when"], reverse=True)
    return out


def load_story(scrub):
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "story", "**", "*.md"), recursive=True)):
        rel_path = os.path.relpath(path, os.path.join(ROOT, "story"))
        if rel_path.startswith("private" + os.sep):
            continue
        meta, body = front_matter(read(path))
        meta.setdefault("title", os.path.splitext(os.path.basename(path))[0].replace("-", " "))
        meta["workers"] = [w.strip().lower() for w in re.split(r"[,\s]+", meta.get("workers", "")) if w.strip()]
        meta["when"] = when(meta)
        meta["path"] = os.path.splitext(rel_path)[0].replace(os.sep, "/")
        meta["body"] = scrub(body)
        try:
            meta["mood"] = int(meta.get("mood", "")) if str(meta.get("mood", "")).strip() else None
        except ValueError:
            meta["mood"] = None
        if meta["mood"] not in (1, 2, 3, 4, 5):
            meta["mood"] = None
        meta["mood_reason"] = scrub(meta.get("mood_reason", "")) if meta.get("mood_reason") else ""
        meta["feeling"] = re.sub(r"[^A-Za-z' -]", "", meta.get("feeling", "")).strip().split(" ")[0][:24] if meta.get("feeling") else ""
        out.append(meta)
    out.sort(key=lambda m: m["when"], reverse=True)
    return out


def moods_by_worker(story):
    """{slug: [(when, mood, reason), ...] oldest first} from diaries that carry a mood."""
    out = {}
    for s in sorted(story, key=lambda m: m["when"]):
        if s.get("mood") is None or s.get("kind", "") != "diary":
            continue
        for w in s["workers"]:
            out.setdefault(w, []).append((s["when"], s["mood"], s["mood_reason"], s.get("feeling", "")))
    return out


def load_workers():
    p = os.path.join(ROOT, "personnel", "registry.json")
    if not os.path.exists(p):
        return []
    try:
        data = json.loads(read(p))
    except json.JSONDecodeError:
        print("personnel/registry.json is not valid JSON", file=sys.stderr)
        return []
    workers = data.get("workers", data) if isinstance(data, dict) else data
    out = []
    for w in workers:
        if not isinstance(w, dict) or not w.get("name"):
            continue
        w = dict(w)
        w["slug"] = slugify(w["name"])
        w.setdefault("status", "active")
        if w.get("temperament") not in TEMPERAMENTS:
            w["temperament"] = default_temperament(w["name"])
        out.append(w)
    rank = {"active": 0, "candidate": 1, "former": 2}
    out.sort(key=lambda w: (rank.get(w["status"], 3), w.get("joined", ""), w["name"]))
    return out


def load_events(scrub):
    p = os.path.join(ROOT, "log", "events.jsonl")
    out = []
    if os.path.exists(p):
        for line in read(p).splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(e, dict) and e.get("time"):
                e["summary"] = scrub(str(e.get("summary", "")))
                e["link"] = scrub(str(e.get("link", "")))
                out.append(e)
    out.sort(key=lambda e: str(e["time"]), reverse=True)
    return out


def load_json(rel_path):
    p = os.path.join(ROOT, rel_path)
    if not os.path.exists(p):
        return {}
    try:
        return json.loads(read(p))
    except json.JSONDecodeError:
        return {}


def load_memory(name, scrub):
    p = os.path.join(ROOT, ".claude", "agent-memory", name, "MEMORY.md")
    return scrub(read(p)) if os.path.exists(p) else ""


def load_usage():
    status = run([sys.executable, "-I", os.path.join(TOOLS, "governor.py"), "status", "--json"])
    block = run([sys.executable, "-I", os.path.join(TOOLS, "governor.py"), "report-usage"])
    try:
        return json.loads(status), block.strip()
    except json.JSONDecodeError:
        return {}, block.strip()


def load_requests(cfg, use_gh):
    repo = cfg.get("company_repo")
    if not (repo and use_gh and shutil.which("gh")):
        return None
    out = run(["gh", "issue", "list", "--repo", repo, "--state", "open", "--limit", "100",
               "--json", "number,title,labels,createdAt,url,comments"])
    try:
        issues = json.loads(out)
    except json.JSONDecodeError:
        return None
    keep = {"emergency": 0, "urgent": 1, "report": 2, "pitch": 3}
    rows = []
    for i in issues:
        labels = [l.get("name", "") for l in i.get("labels", [])]
        kinds = [l for l in labels if l in keep]
        if not kinds:
            continue
        rows.append({"kind": sorted(kinds, key=keep.get)[0], "title": i.get("title", ""), "url": i.get("url", ""),
                     "created": i.get("createdAt", ""), "comments": len(i.get("comments") or [])})
    rows.sort(key=lambda r: (keep[r["kind"]], r["created"]))
    return rows


# ---------- layout ----------

LAYOUT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% if page.title %}{{ page.title }} · {% endif %}{{ site.title }}</title>
<meta name="description" content="{{ page.description | default: site.description }}">
{% feed_meta %}
<style>
:root{--ink:#1b1b1b;--muted:#5f5f5f;--line:#e4e4e4;--bg:#fff;--accent:#2b5bd7;--soft:#f4f5f8;--ok:#2f9e5b;--warm:#d9a21b;--hot:#d9442b;--pink:#c04fb0;--seg:#fff;--portrait:#fff;--blue-bg:#dfe7ff;--blue-fg:#1d3d99;--amber-bg:#fbe3a6;--amber-fg:#4a3200;--green-bg:#d3f0de;--green-fg:#0f4a2a;--pink-bg:#f7d9f0;--pink-fg:#6a1f5e;--grey-bg:#e9eaee;--grey-fg:#3d3f46}
@media (prefers-color-scheme:dark){:root{--ink:#ececec;--muted:#a8a8a8;--line:#333;--bg:#111;--accent:#8ab0ff;--soft:#1b1b1b;--ok:#4fc27a;--warm:#e6b94a;--hot:#ef6a52;--pink:#e07bd2;--seg:#2c2f36;--blue-bg:#1d2b4f;--blue-fg:#c3d3ff;--amber-bg:#4a3a12;--amber-fg:#ffe0a0;--green-bg:#163a26;--green-fg:#a6e6c0;--pink-bg:#44203e;--pink-fg:#f5c2ea;--grey-bg:#2a2b30;--grey-fg:#c9cad0}}
*{box-sizing:border-box}body{margin:0;font:17px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}
a{color:var(--accent)}header.site,main,footer{max-width:960px;margin:0 auto;padding:0 18px}
header.site{padding-top:22px}header.site .brand{font-weight:800;font-size:22px;letter-spacing:-.01em;text-decoration:none;color:var(--ink)}
.tabs{display:flex;flex-wrap:wrap;gap:4px;margin:12px 0 0;padding:4px;background:var(--soft);border:1px solid var(--line);border-radius:14px}
.tabs a{padding:7px 13px;border-radius:10px;font-size:15px;font-weight:600;color:var(--muted);text-decoration:none}.tabs a:hover{color:var(--ink)}
.tabs a[aria-current]{background:var(--seg);color:var(--ink);font-weight:700;box-shadow:inset 0 -3px 0 var(--accent),0 1px 3px rgba(0,0,0,.14),0 0 0 1px var(--line)}
.tabs a:focus-visible,.subtabs a:focus-visible,.card:focus-visible,.rec:focus-visible,.pager a:focus-visible,.crumbs a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.notice{background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:9px 14px;margin:12px 0 0;font-size:13.5px;color:var(--muted)}
h1{font-size:34px;letter-spacing:-.02em;margin:18px 0 8px;text-wrap:balance}h2{font-size:22px;margin:30px 0 10px}h3{font-size:17px;margin:22px 0 8px}
.lead{font-size:19px;color:var(--muted);margin:0 0 18px}
.crumbs{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:6px 16px;margin:20px 0 0;font-size:15px}
.crumbs a{text-decoration:none;font-weight:600}.crumbs a:hover{text-decoration:underline}.crumbs .step{display:flex;gap:16px}
.page-head{flex:1;min-width:0;margin:6px 0 18px}.page-head h1{margin:8px 0 6px}.page-head .people{margin-top:12px}.page-head .mood{margin:12px 0 0}
.kicker{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;font-size:14px;color:var(--muted)}.kicker .num{font-weight:700;color:var(--ink)}
.kind{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;padding:2px 9px;border-radius:999px;white-space:nowrap}
.kind.blue{background:var(--blue-bg);color:var(--blue-fg)}.kind.amber{background:var(--amber-bg);color:var(--amber-fg)}.kind.green{background:var(--green-bg);color:var(--green-fg)}
.kind.pink{background:var(--pink-bg);color:var(--pink-fg)}.kind.grey{background:var(--grey-bg);color:var(--grey-fg)}
.person-head{display:flex;gap:18px;align-items:flex-start;justify-content:space-between}
.hero{display:grid;grid-template-columns:1fr;gap:16px;margin:12px 0 22px}.panel{background:var(--soft);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:0 0 16px}
.tile{background:var(--soft);border:1px solid var(--line);border-radius:14px;padding:14px 16px}.tile b{display:block;font-size:26px;letter-spacing:-.02em}.tile span{font-size:13.5px;color:var(--muted)}
.tile .bar{margin:6px 0 0}.tile .bar-head{display:none}
.bar{margin:10px 0}.bar-head{display:flex;justify-content:space-between;font-size:14px;color:var(--muted);margin-bottom:4px}.bar-head span:first-child{color:var(--ink)}
.bar-track{height:10px;background:var(--line);border-radius:6px;overflow:hidden}.bar-fill{height:100%;background:var(--ok);border-radius:6px;transition:width .4s}
.bar.warm .bar-fill{background:var(--warm)}.bar.hot .bar-fill{background:var(--hot)}.bar.money .bar-fill{background:var(--accent)}
.pipe{list-style:none;display:flex;padding:0;margin:8px 0 12px;position:relative}.pipe li{flex:1;position:relative;text-align:center;font-size:13.5px;color:var(--muted);padding-top:20px}
.pipe li .dot{position:absolute;top:0;left:50%;transform:translateX(-50%);width:14px;height:14px;border-radius:50%;background:var(--line);box-shadow:0 0 0 2px var(--soft)}
.pipe li::before{content:"";position:absolute;top:6px;left:-50%;width:100%;height:2px;background:var(--line)}.pipe li:first-child::before{display:none}
.pipe li.done .dot,.pipe li.now .dot{background:var(--accent)}.pipe li.done::before,.pipe li.now::before{background:var(--accent)}
.pipe li.now{color:var(--ink);font-weight:700}.pipe li.now .dot{transform:translateX(-50%) scale(1.35)}
.track{display:flex;gap:3px;margin:8px 0}.track i{flex:1;height:14px;border-radius:3px;background:var(--line)}.track i.past{background:var(--accent);opacity:.55}.track i.now{background:var(--accent);outline:2px solid var(--accent);outline-offset:1px}.track i.launch{background:var(--ok)}
.chart{width:100%;height:auto;display:block}.chart .lbl{font-size:11px;fill:var(--muted)}.chart .lbl.strong{fill:var(--ink);font-weight:700;font-size:12px}
.stack{display:flex;height:16px;border-radius:8px;overflow:hidden;background:var(--line);margin:8px 0 6px}.seg{display:inline-block;height:100%}.seg.project{background:var(--accent)}.seg.reports{background:var(--ok)}.seg.meetings{background:var(--warm)}.seg.hiring{background:var(--pink)}.seg.talk{background:var(--hot)}
.legend{font-size:13px;color:var(--muted);display:flex;flex-wrap:wrap;gap:4px 16px}.legend .seg{width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:middle}
.strip{display:grid;grid-template-columns:1fr;gap:4px 18px;background:var(--soft);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:0 0 18px;font-size:14px}
.strip .row{display:flex;align-items:center;gap:12px}.strip .bar{flex:1;margin:4px 0}.strip .track{flex:1}
table{border-collapse:collapse;width:100%;font-size:15px;margin:12px 0}th,td{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top}
img.portrait{width:120px;height:120px;border-radius:16px;flex:none;margin-top:6px;background:var(--portrait);border:1px solid var(--line)}
.cast{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px}.cast a{display:block;text-decoration:none;color:inherit;border:1px solid var(--line);border-radius:14px;padding:12px;background:var(--soft)}
.cast a:hover{border-color:var(--accent)}.cast img{width:100%;aspect-ratio:1;border-radius:12px;display:block;margin-bottom:8px;background:var(--portrait);border:1px solid var(--line)}.cast small{color:var(--muted);display:block}
.cast a>b{display:block}.cast .kind{margin-top:6px}.cast .score{margin-top:6px;font-size:13px}
.mood{display:flex;align-items:center;gap:12px;margin:8px 0 14px;flex-wrap:wrap}.mood .why{color:var(--muted);font-size:14.5px}.mood .spark{margin-left:auto}
.mood-word{font-weight:700;padding:1px 8px;border-radius:8px;white-space:nowrap}.mood-word.big{font-size:20px;padding:2px 10px}.mood-why{color:var(--muted)}
.mood-word.lv0{color:var(--muted);background:var(--line)}.mood-word.lv1{color:#fff;background:#c43d2b}.mood-word.lv2{color:#2b1a00;background:#e59a3a}.mood-word.lv3{color:#2b2400;background:#e7cf4a}.mood-word.lv4{color:#0f2e1a;background:#7fd19a}.mood-word.lv5{color:#082a12;background:#3fbf6e}
.cast .mood-word{display:inline-block;margin-top:6px;font-size:13px}
details{margin:12px 0}summary{cursor:pointer}footer{padding:28px 18px 44px;color:var(--muted);font-size:14px}blockquote{border-left:3px solid var(--line);margin:0;padding-left:12px;color:var(--muted)}
.tag{font-size:12px;padding:1px 7px;border:1px solid var(--line);border-radius:10px;color:var(--muted);white-space:nowrap}
.tag.t-hire,.tag.t-sale,.tag.t-launch,.tag.t-release{background:var(--green-bg);color:var(--green-fg);border-color:transparent}
.tag.t-decision,.tag.t-pitch,.tag.t-amendment{background:var(--blue-bg);color:var(--blue-fg);border-color:transparent}
.tag.t-interview,.tag.t-offer,.tag.t-message{background:var(--amber-bg);color:var(--amber-fg);border-color:transparent}
.tag.t-departure,.tag.t-review{background:var(--pink-bg);color:var(--pink-fg);border-color:transparent}
.period h3{margin:14px 0 6px;font-size:15px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}.period h3:first-child{margin-top:0}.period.wide{margin-top:18px}
.rail{list-style:none;margin:0;padding:0 0 0 14px;border-left:2px solid var(--line)}.rail li{position:relative;margin:0 0 10px;padding-left:12px;font-size:15px}
.rail li::before{content:"";position:absolute;left:-21px;top:7px;width:10px;height:10px;border-radius:50%;background:var(--accent);border:2px solid var(--soft)}
.rail li.t-hire::before,.rail li.t-sale::before,.rail li.t-launch::before{background:var(--ok)}.rail li.t-departure::before{background:var(--hot)}.rail li.t-decision::before{background:var(--pink)}
.rail time{display:inline-block;min-width:76px;color:var(--muted);font-size:13px}
.people{display:flex;flex-wrap:wrap;gap:12px}.person{display:flex;align-items:center;gap:8px;text-decoration:none;color:inherit;border:1px solid var(--line);border-radius:10px;padding:6px 10px;background:var(--bg)}
.person img{width:40px;height:40px;border-radius:8px;background:var(--portrait);border:1px solid var(--line)}.person small{color:var(--muted)}
.moods{list-style:none;padding:0;margin:0}.moods li{margin:6px 0}
.chart.small .lbl{font-size:10px}.d-ok{fill:var(--ok)}.d-warm{fill:var(--warm)}.d-hot{fill:var(--hot)}
.minis{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px}.mini{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:14px}.mini .spark{margin-left:auto}
.report-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:8px 28px;align-items:start}.report-main{min-width:0}.report-main>:first-child{margin-top:0}
.callout{border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:10px;padding:10px 14px;background:var(--soft);font-size:15px;margin:20px 0}
.pager{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:30px 0 6px}
.pager a{display:block;padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:var(--soft);text-decoration:none;font-size:13.5px;color:var(--muted)}
.pager a b{display:block;margin-top:2px;font-size:15.5px;color:var(--ink)}.pager a:hover{border-color:var(--accent)}.pager .next{grid-column:2;text-align:right}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px;margin:10px 0 0}.cards.one{grid-template-columns:minmax(0,1fr)}.day .cards{grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}
.card{display:flex;flex-direction:column;gap:6px;min-width:0;padding:14px 16px;border:1px solid var(--line);border-radius:14px;background:var(--soft);text-decoration:none;color:inherit}
.card:hover{border-color:var(--accent)}.card .meta{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;font-size:13.5px;color:var(--muted)}
.card b{font-size:17px;line-height:1.3;text-wrap:balance}.card p{margin:0;font-size:14.5px;line-height:1.45;color:var(--muted)}
.days{margin:8px 0 0 6px;padding-left:22px;border-left:2px solid var(--line)}
.day{position:relative;margin:0 0 28px}.day::before{content:"";position:absolute;left:-31px;top:8px;width:12px;height:12px;border-radius:50%;background:var(--accent);border:2px solid var(--bg)}
.day-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 12px;margin:0 0 10px;font-size:20px}.day-head small{font-size:14px;font-weight:400;color:var(--muted)}
.day-mood{margin-left:auto;font-size:13.5px;font-weight:400;color:var(--muted)}
.recs{list-style:none;margin:8px 0 0;padding:0;display:grid;gap:8px}
.rec{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;padding:10px 14px;border:1px solid var(--line);border-radius:12px;background:var(--soft);text-decoration:none;color:inherit}
.rec:hover{border-color:var(--accent)}.rec b{flex:1 1 200px;min-width:0;font-size:15.5px;color:var(--ink)}.rec time{font-size:13px;color:var(--muted);white-space:nowrap}
.avatars{display:inline-flex;flex-wrap:wrap;gap:4px}img.avatar{width:28px;height:28px;border-radius:7px;background:var(--portrait);border:1px solid var(--line)}
.card .avatars img.avatar{width:36px;height:36px;border-radius:8px}img.avatar.hired{outline:2px solid var(--ok);outline-offset:1px}
.subtabs{display:flex;flex-wrap:wrap;gap:4px 22px;margin:20px 0 0;border-bottom:1px solid var(--line)}
.subtabs a{padding:6px 0 9px;margin-bottom:-1px;border-bottom:3px solid transparent;text-decoration:none;font-weight:600;color:var(--muted)}
.subtabs a[aria-current]{color:var(--ink);border-bottom-color:var(--accent)}
.reports{list-style:none;padding:0}.reports li{margin:8px 0}.latest{font-size:15px;color:var(--muted);margin:6px 0 0}
@media (min-width:720px){.hero.two{grid-template-columns:3fr 2fr}.strip{grid-template-columns:1fr 1fr}}
@media (min-width:880px){.report-grid{grid-template-columns:minmax(0,1.65fr) minmax(0,1fr)}}
@media (max-width:540px){h1{font-size:28px}img.portrait{width:84px;height:84px}.pager{grid-template-columns:1fr}.pager .next{grid-column:1}.tabs a{padding:6px 10px;font-size:14.5px}}
@media (prefers-reduced-motion:reduce){.bar-fill{transition:none}}
</style>
</head>
<body>
<header class="site">
<a class="brand" href="{{ '/' | relative_url }}">{{ site.title }}</a>
<nav class="tabs" aria-label="Sections">
<a href="{{ '/' | relative_url }}"{% if page.section == "home" %} aria-current="true"{% endif %}>Home</a>
<a href="{{ '/reports/' | relative_url }}"{% if page.section == "reports" %} aria-current="true"{% endif %}>Reports</a>
<a href="{{ '/cast/' | relative_url }}"{% if page.section == "cast" %} aria-current="true"{% endif %}>Cast</a>
<a href="{{ '/story/' | relative_url }}"{% if page.section == "records" %} aria-current="true"{% endif %}>Records</a>
<a href="{{ '/log/' | relative_url }}"{% if page.section == "log" %} aria-current="true"{% endif %}>Log</a>
<a href="{{ '/usage.html' | relative_url }}"{% if page.section == "usage" %} aria-current="true"{% endif %}>Usage</a>
<a href="{{ '/requests.html' | relative_url }}"{% if page.section == "requests" %} aria-current="true"{% endif %}>Requests</a>
<a href="{{ '/about.html' | relative_url }}"{% if page.section == "about" %} aria-current="true"{% endif %}>About</a>
</nav>
<div class="notice">{{ site.disclosure }}</div>
</header>
<main>
{{ content }}
</main>
<footer>{{ site.title }} · <a href="{{ '/privacy.html' | relative_url }}">Privacy</a> · <a href="{{ '/support.html' | relative_url }}">Support</a> · <a href="{{ '/press.html' | relative_url }}">Press kit</a> · <a href="{{ '/feed.xml' | relative_url }}">RSS</a></footer>
</body>
</html>
"""


class Site:
    def __init__(self, out, cfg):
        self.out, self.cfg = out, cfg
        self.written = set()

    def write(self, rel_path, text):
        path = os.path.join(self.out, rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.written.add(os.path.normpath(rel_path).replace(os.sep, "/"))

    def copy(self, src, rel_path):
        path = os.path.join(self.out, rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copyfile(src, path)
        self.written.add(os.path.normpath(rel_path).replace(os.sep, "/"))

    def clean(self):
        """Remove everything we did not write this time, keeping git's files and a CNAME."""
        for dirpath, dirnames, filenames in os.walk(self.out):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for name in filenames:
                r = os.path.relpath(os.path.join(dirpath, name), self.out).replace(os.sep, "/")
                if r not in self.written and r != "CNAME":
                    os.remove(os.path.join(dirpath, name))
        for dirpath, dirnames, filenames in list(os.walk(self.out, topdown=False)):
            if dirpath != self.out and ".git" not in dirpath and not os.listdir(dirpath):
                os.rmdir(dirpath)


# ---------- the build ----------

def build(out, use_gh=True):
    cfg = load_config()
    scrub = scrubber(cfg)
    site = Site(out, cfg)
    reports = load_reports(scrub)
    story = load_story(scrub)
    workers = load_workers()
    events = load_events(scrub)
    board = load_json("ops/scoreboard.json")
    usage, usage_block = load_usage()
    usage_file = load_json("ops/usage.json")
    requests = load_requests(cfg, use_gh)
    moods = moods_by_worker(story)
    by_slug = {w["slug"]: w for w in workers}
    repo = cfg.get("company_repo") or ""
    goal = num(cfg.get("goal_usd"), 200)
    days_total = int(num(cfg.get("days_total"), 30))
    msg_url = f"https://github.com/{repo}/issues/new?labels=directive&title=Message+from+the+Investors" if repo else ""
    state = load_json("ops/state.json")
    try:
        day1 = dt.date.fromisoformat(state["day1"]) if state.get("day1") else None
    except ValueError:
        day1 = None

    def latest_mood(slug):
        return moods[slug][-1] if moods.get(slug) else (None, None, "", "")

    active = [w for w in workers if w["status"] == "active"]
    team_levels = [latest_mood(w["slug"])[1] for w in active if latest_mood(w["slug"])[1]]
    team_mood = round(sum(team_levels) / len(team_levels)) if team_levels else None

    def mood_on(date):
        """Team mood as of a date: each active worker's last diary on or before it."""
        levels = []
        for w in active:
            prior = [m for m in moods.get(w["slug"], []) if m[0][:10] <= date]
            if prior:
                levels.append(prior[-1][1])
        return round(sum(levels) / len(levels)) if levels else None

    history = [h for h in (board.get("history") or []) if isinstance(h, dict)]
    stage = board.get("stage") or ("selling" if num(board.get("revenue_usd")) > 0 else "research")
    launched = bool(board.get("launched")) or stage in ("launch", "selling")
    launched_day = None
    if board.get("launched") and day1:
        try:
            launched_day = (dt.date.fromisoformat(str(board["launched"])) - day1).days + 1
        except ValueError:
            pass
    revenue = num(board.get("revenue_usd"))
    spent = num(board.get("spent_usd"))
    day = int(num(board.get("day"), 0))
    days_left = int(num(board.get("days_left"), max(0, days_total - day)))

    # Jekyll config and layout
    site.write("_config.yml", "\n".join([
        f"title: {json.dumps(cfg['name'])}",
        f"description: {json.dumps(cfg['tagline'])}",
        f"url: {json.dumps(cfg.get('url') or '')}",
        f"disclosure: {json.dumps(cfg['disclosure'])}",
        "plugins: [jekyll-feed]",
        "feed: {path: feed.xml}",
        "markdown: kramdown",
        "future: true",
        "exclude: [README.md]",
        "defaults:",
        "  - scope: {path: \"\"}",
        "    values: {layout: default}",
        "  - scope: {path: \"\", type: posts}",
        "    values: {permalink: \"/reports/:title/\"}",
        "",
    ]))
    site.write("_layouts/default.html", LAYOUT)
    site.write("README.md", f"# {cfg['name']} site\n\nGenerated by tools/site_build.py in the company repository. Don't edit by hand.\n")

    # Portraits: the still copies as drawn on hire, and animated ones that carry today's mood
    for p in glob.glob(os.path.join(ROOT, "personnel", "portraits", "*.svg")):
        site.copy(p, os.path.join("assets", "portraits", "still", os.path.basename(p)))
    variants = assign_variants([w["name"] for w in workers])
    for w in workers:
        site.write(os.path.join("assets", "portraits", f"{w['slug']}.svg"),
                   portrait_svg(w["name"], w["temperament"], latest_mood(w["slug"])[1], variant=variants.get(w["name"], 0)))

    def portrait_img(slug, cls=""):
        c = f' class="{cls}"' if cls else ""
        return f'<img{c} src="{rel("/assets/portraits/" + slug + ".svg")}" alt="">'

    # Shared by several pages: day labels, record rows, hiring rounds, report cards
    def day_of_date(date_s):
        if not day1:
            return None
        try:
            n = (dt.date.fromisoformat(str(date_s)[:10]) - day1).days + 1
        except ValueError:
            return None
        return n if n >= 1 else None

    def day_label(date_s):
        n = day_of_date(date_s)
        return f"Day {n}" if n else nice_date(date_s)

    def rec_item(s, show_day=False):
        mood = f" {mood_chip(s['mood'], s.get('feeling'))}" if s.get("kind") == "diary" and s.get("mood") else ""
        when_txt = (day_label(s["when"][:10]) + " · " if show_day else "") + esc(s["when"][11:16])
        return (f'<li><a class="rec" href="{rel("/story/" + s["path"] + ".html")}">{record_badge(s.get("kind"))}'
                f'<b>{safe(s["title"])}</b><span class="avatars">{avatars(s["workers"], by_slug)}</span>{mood}<time>{when_txt}</time></a></li>')

    rounds = {}
    for s in story:
        parts = s["path"].split("/")
        if len(parts) >= 3 and parts[0] == "hiring":
            rounds.setdefault(parts[1], []).append(s)
    for w in workers:
        if w.get("round"):
            rounds.setdefault(str(w["round"]), [])

    def round_info(rid):
        recs = sorted(rounds.get(rid, []), key=lambda m: m["when"])
        cands = [w for w in workers if str(w.get("round", "")) == rid]
        hired = [w for w in cands if w["status"] != "candidate"]
        role = hired[0].get("role", "") if hired else ""
        for w in cands:
            if role:
                break
            role = re.sub(r"^candidate,?\s*(for\s+)?", "", str(w.get("role", "")), flags=re.I)
        role = role or re.sub(r"^\d{4}-\d{2}-\d{2}-", "", rid).replace("-", " ").capitalize()
        brief = next((s for s in recs if s["path"].endswith("/brief")), None)
        decision = next((s for s in recs if s["path"].endswith("/decision")), None)
        date = (brief or (recs[0] if recs else {})).get("date") or rid[:10]
        return {"id": rid, "role": role, "records": recs, "candidates": cands, "hired": hired, "brief": brief,
                "decision": decision, "interviews": [s for s in recs if s.get("kind") == "interview"], "date": date}

    round_list = sorted((round_info(rid) for rid in rounds), key=lambda x: (x["date"], x["id"]), reverse=True)
    round_by_id = {x["id"]: x for x in round_list}

    def names_list(ws):
        ns = [esc(w["name"]) for w in ws]
        if len(ns) < 2:
            return "".join(ns)
        return ", ".join(ns[:-1]) + " and " + ns[-1]

    def round_outcome(rd):
        n = len(rd["candidates"])
        bench = [w for w in rd["candidates"] if w["status"] == "candidate"]
        if rd["hired"]:
            out = f"{names_list(rd['hired'])} hired from a slate of {n}."
            if bench:
                out += f" {names_list(bench)} {'stays' if len(bench) == 1 else 'stay'} on the bench."
            return out
        return f"A slate of {n}; no hire yet." if n else "No candidates recorded yet."

    def round_card(rd):
        fs = "".join(f'<img class="avatar{" hired" if w["status"] != "candidate" else ""}" src="{rel("/assets/portraits/" + w["slug"] + ".svg")}" '
                     f'alt="{esc(w["name"])}" title="{esc(w["name"])}">' for w in rd["candidates"])
        return (f'<a class="card" href="{rel("/story/hiring/" + rd["id"] + "/")}"><span class="meta">{badge("Hiring round", "blue")}'
                f'<span>{day_label(rd["date"])} · {nice_date(rd["date"])}</span></span><b>{safe(rd["role"])}</b>'
                f'<span class="avatars">{fs}</span><p>{round_outcome(rd)}</p></a>')

    def report_card(r, compact=False):
        lead, headline = split_title(r["title"])
        meta = report_badge(r.get("kind", "report")) + (f"<span>{safe(lead)}</span>" if lead else "")
        if compact:
            n = r.get("day") or day_of_date(r["date"])
            meta += f"<span>{('Day ' + esc(n) + ' · ') if n else ''}{nice_date(r['date'])}, {esc(r['when'][11:16])}</span>"
        else:
            meta += f"<span>{esc(r['when'][11:16])}</span>"
        ex = "" if compact else excerpt(r["body"])
        return (f'<a class="card report" href="{rel("/reports/" + r["slug"] + "/")}"><span class="meta">{meta}</span>'
                f"<b>{safe(headline)}</b>" + (f"<p>{safe(ex)}</p>" if ex else "") + "</a>")

    # Reports as posts (newest first, RSS for free): a header that says which report this is,
    # the progress strip, the report beside what happened in its period, and links to the neighbours
    usage_days = usage_file.get("days") or {}
    weekly_budget = num(usage_file.get("weekly_budget_usd"), 150)
    hist_by_date = {h.get("date"): h for h in history if h.get("date")}
    for i, r in enumerate(reports):
        kind = r.get("kind", "report")
        rday = int(num(r.get("day"), 0))
        fallback = revenue if i == 0 else 0.0
        rev = num(r.get("revenue_usd"), num(hist_by_date.get(r["date"], {}).get("revenue_usd"), fallback))
        used = num(usage_days.get(r["date"]))
        tm = mood_on(r["date"])
        team_chip = mood_chip(tm) if tm else '<span class="mood-why">not recorded</span>'
        strip = ['<div class="strip">',
                 f'<div class="row"><span class="tag">Day {rday} of {days_total}</span>{day_track(rday, days_total, launched_day)}</div>',
                 f'<div class="row">{bar("Net proceeds", rev, goal, cls="money")}</div>',
                 f'<div class="row">{bar("Claude usage that day", used, weekly_budget / 7, note=f"${used:,.2f} of a 1/7 share")}</div>',
                 f'<div class="row"><span>Team morale that day:</span> {team_chip}</div>',
                 "</div>"]
        # This period: events, people, moods, and usage since the previous report
        # A report's window runs from the previous report to this one, each shifted by a grace
        # period: the diaries and events of a report session are written after its nominal time.
        end_t = (when_time(r["when"]) or dt.datetime(1970, 1, 1)) + REPORT_GRACE
        prev = reports[i + 1]["when"] if i + 1 < len(reports) else None
        start_t = ((when_time(prev) + REPORT_GRACE) if prev and when_time(prev)
                   else (dt.datetime.combine(day1, dt.time(0, 0)) if day1 else dt.datetime(1970, 1, 1)))
        in_window = [e for e in events if (lambda t: t and start_t < t <= end_t)(event_time(e))]
        aside = ['<div class="panel period" role="complementary" aria-label="This period">',
                 "<h3>What happened since the last report</h3>", rail(in_window, by_slug)]
        people = people_strip(in_window, by_slug, variants)
        if people:
            aside += ["<h3>People</h3>", people]
        ml = mood_list(story, by_slug, start_t, end_t)
        if ml:
            aside += ["<h3>How they felt</h3>", ml]
        aside.append("</div>")
        wide = []
        if kind in ("weekly", "final"):
            span = 30 if kind == "final" else 7
            rdate = dt.date.fromisoformat(r["date"]) if r.get("date") else None
            dlist = [(rdate - dt.timedelta(days=k)).isoformat() for k in range(span - 1, -1, -1)] if rdate else []
            vals = [num(usage_days.get(d)) for d in dlist]
            wide += [f"<h3>Claude usage, the last {span} days</h3>", daily_bars([d for d in dlist], vals, weekly_budget / 7)]
            day_of = (lambda when_s: (dt.date.fromisoformat(when_s[:10]) - day1).days + 1) if day1 else (lambda when_s: 0)
            sm = small_multiples(active, moods, max(1, rday - span + 1), rday, day_of)
            if sm:
                wide += [f"<h3>Mood over the {'month' if kind == 'final' else 'week'}</h3>", sm]
            if kind == "final":
                milestones = [e for e in events if str(e.get("type", "")).lower() in MILESTONE_TYPES]
                wide += ["<h3>The month, in milestones</h3>", rail(milestones, by_slug, limit=60)]
                if history:
                    wide += ["<h3>Net proceeds by day</h3>", revenue_chart(history, goal, days_total, day1)]
        older = reports[i + 1] if i + 1 < len(reports) else None
        newer = reports[i - 1] if i > 0 else None
        step = ""
        if older:
            step += f'<a href="{rel("/reports/" + older["slug"] + "/")}" rel="prev">‹ {safe(split_title(older["title"])[0] or "Older")}</a>'
        if newer:
            step += f'<a href="{rel("/reports/" + newer["slug"] + "/")}" rel="next">{safe(split_title(newer["title"])[0] or "Newer")} ›</a>'
        lead, headline = split_title(r["title"])
        kicker = (report_badge(kind, " report") + (f'<span class="num">{safe(lead)}</span>' if lead else "")
                  + f"<span>Day {rday} of {days_total} · {nice_date(r['date'])}, {esc(r['when'][11:16])}</span>")
        callout = ""
        if r.get("issue"):
            callout = (f'<div class="callout"><b>Investors:</b> this report\'s private copy, with its Questions for the Investors, '
                       f'is <a href="{esc(r["issue"])}">on GitHub</a>. Answer there by midnight.</div>')
        pager = ""
        if older or newer:
            pager = ('<div class="pager" role="navigation" aria-label="Older and newer reports">'
                     + (f'<a class="prev" href="{rel("/reports/" + older["slug"] + "/")}">← Older<b>{safe(older["title"])}</b></a>' if older else "")
                     + (f'<a class="next" href="{rel("/reports/" + newer["slug"] + "/")}">Newer →<b>{safe(newer["title"])}</b></a>' if newer else "")
                     + "</div>")
        head = {"layout": "default", "title": r["title"], "date": f"{r['when']}:00", "kind": kind,
                "day": r.get("day"), "number": r.get("number"), "section": "reports"}
        body = [crumbs("/reports/", "All reports", f'<span class="step">{step}</span>' if step else ""),
                page_head(kicker, safe(headline)), "\n".join(strip), "",
                '<div class="report-grid" markdown="1">', '<div class="report-main" markdown="1">', "",
                raw(r["body"]), callout, "", "</div>", "\n".join(aside), "</div>", ""]
        if wide:
            body += ['<div class="panel period wide">' + "\n".join(wide) + "</div>", ""]
        body.append(pager)
        site.write(os.path.join("_posts", f"{r['date']}-{r['slug']}.md"), fm(head) + "\n".join(body) + "\n")

    # Reports index: one block per day, newest first, each report a card with its opening line
    by_date = {}
    for r in reports:
        by_date.setdefault(r["date"], []).append(r)
    groups = []
    for date in sorted(by_date, reverse=True):
        rs = by_date[date]
        n = rs[0].get("day") or day_of_date(date)
        tm = mood_on(date)
        morale = f'<span class="day-mood">team morale {mood_chip(tm)}</span>' if tm else ""
        groups.append(f'<div class="day"><h2 class="day-head"><span>{("Day " + esc(n)) if n else nice_date(date)}</span>'
                      f'<small>{nice_date(date)} · {len(rs)} report{"s" if len(rs) != 1 else ""}</small>{morale}</h2>'
                      f'<div class="cards">{"".join(report_card(r) for r in rs)}</div></div>')
    rep = [fm({"layout": "default", "title": "Reports", "section": "reports"}), "# Reports", "",
           '<p class="lead">A report is published every evening, and every morning after a night when something happened. '
           "Newest first; every report has a permanent link.</p>", ""]
    rep += ([f'<div class="days">{"".join(groups)}</div>'] if groups else ["No reports yet. The first one is published at 6 p.m. on Day 1."]) + [""]
    site.write(os.path.join("reports", "index.md"), "\n".join(rep))

    # Home: the five things that matter, the latest report, the cast, then the earlier reports
    latest = reports[0] if reports else None
    open_count = len(requests) if requests is not None else None
    team_tile = mood_chip(team_mood, big=True) if team_mood else '<span class="mood-word lv0 big">No diaries yet</span>'
    tiles = [
        f'<div class="tile"><b>${revenue:,.0f}</b><span>of ${goal:,.0f} net proceeds</span>{bar("", revenue, goal, note=" ", cls="money")}</div>',
        f'<div class="tile"><b>{days_left}</b><span>days left · Day {day} of {days_total}</span></div>',
        f'<div class="tile"><b>{team_tile}</b><span>team morale, from the latest diaries</span></div>',
        (f'<div class="tile"><b>{open_count}</b><span>waiting on the Investors · <a href="{rel("/requests.html")}">see requests</a></span></div>'
         if open_count is not None else f'<div class="tile"><b>${spent:,.0f}</b><span>real spending so far</span></div>'),
    ]
    status_line = esc(board.get("app_name") or "No product chosen yet") + (f": {esc(board['status'])}" if board.get("status") else "")
    store = f' · <a href="{esc(board["app_store_url"])}">App Store</a>' if board.get("app_store_url") else ""
    if launched:
        hero = (f'<div class="hero two"><div class="panel"><h3 style="margin:0 0 6px">Net proceeds by day</h3>{revenue_chart(history, goal, days_total, day1)}</div>'
                f'<div class="panel"><h3 style="margin:0 0 6px">Where the company is</h3>{pipeline(stage)}{day_track(day, days_total, launched_day)}'
                f'<p class="latest">{status_line}{store}</p></div></div>')
    else:
        hero = (f'<div class="hero"><div class="panel"><h3 style="margin:0 0 6px">Where the company is</h3>{pipeline(stage)}'
                f'{day_track(day, days_total, launched_day)}'
                f'<p class="latest">Day {day} of {days_total}. {status_line}. Revenue starts at launch; ${spent:,.0f} spent so far.</p></div></div>')
    cast_strip = "".join(
        f'<a href="{rel("/cast/" + w["slug"] + ".html")}">{portrait_img(w["slug"])}<b>{esc(w["name"])}</b><small>{esc(w.get("role", ""))}</small>{mood_chip(latest_mood(w["slug"])[1], latest_mood(w["slug"])[3]) if latest_mood(w["slug"])[1] else ""}</a>'
        for w in active)
    index = [fm({"layout": "default", "title": "Home", "description": cfg["tagline"], "section": "home"}),
             f"# {cfg['name']}", "", f'<p class="lead">{esc(cfg["tagline"])}</p>', "",
             '<div class="tiles">' + "".join(tiles) + "</div>", hero, ""]
    if latest:
        index += ["## Latest report", "", f'<div class="cards one">{report_card(latest)}</div>', ""]
    if active:
        index += ["## The cast", "", '<div class="cast">' + cast_strip + "</div>", ""]
    if len(reports) > 1:
        index += ["## Earlier reports", "", '<div class="cards">' + "".join(report_card(r, compact=True) for r in reports[1:4]) + "</div>", ""]
    index += [f'<p><a href="{rel("/reports/")}">All reports</a>' + (f' · <a href="{rel("/requests.html")}">open requests</a> · <a href="{msg_url}">message the company</a>' if msg_url else "") + "</p>", ""]
    site.write("index.md", "\n".join(index))

    # Cast
    cast = [fm({"layout": "default", "title": "Cast", "section": "cast"}), "# The cast", "",
            '<p class="lead">Every worker is an AI-simulated character with a first name, a role, a personality, and a career goal. '
            "Portraits are drawn by code from a mathematical expression seeded by the name, and move in a way chosen by the worker's temperament; "
            "the word under each name is the feeling from their latest diary, in their own word.</p>", ""]
    for status, label in STATUS_GROUPS:
        group = [w for w in workers if w["status"] == status or (status == "former" and w["status"] not in ("active", "candidate"))]
        if not group:
            continue
        cast += [f"## {label}", ""]
        if status == "candidate":
            cast += [f'<p class="mood-why">Interviewed in a hiring round and not hired. They stay on the bench and may be reconsidered. '
                     f'<a href="{rel("/story/#hiring-rounds")}">See the hiring rounds</a>.</p>', ""]
        cast += ['<div class="cast">']
        for w in group:
            cast.append(f'<a href="{rel("/cast/" + w["slug"] + ".html")}">{portrait_img(w["slug"])}<b>{esc(w["name"])}</b><small>{esc(w.get("role", ""))}</small>'
                        f'{mood_chip(latest_mood(w["slug"])[1], latest_mood(w["slug"])[3]) if latest_mood(w["slug"])[1] else ""}</a>')
        cast += ["</div>", ""]
    site.write(os.path.join("cast", "index.md"), "\n".join(cast))

    for w in workers:
        slug = w["slug"]
        mine = [e for e in events if str(e.get("worker", "")).lower() == slug][:EVENT_LIMIT_PER_WORKER]
        records = [s for s in story if slug in s["workers"]]
        hist = moods.get(slug, [])
        mwhen, mlevel, mreason, mword = latest_mood(slug)
        status_label, status_tone = STATUS_BADGES.get(w.get("status", "active"), (str(w.get("status", "")).title(), "grey"))
        kicker = (badge(status_label, status_tone) + f"<span>{safe(w.get('role', ''))}</span>"
                  + (f"<span>reports to {esc(w['manager'])}</span>" if w.get("manager") else ""))
        page = [fm({"layout": "default", "title": w["name"], "section": "cast"}), crumbs("/cast/", "The cast"),
                f'<div class="person-head">{page_head(kicker, esc(w["name"]))}{portrait_img(slug, "portrait")}</div>', ""]
        if w.get("bio"):
            page += [scrub(str(w["bio"])), ""]
        page += [f'<div class="mood"><div>{mood_chip(mlevel, mword, mreason, big=True)}'
                 + (f'<div class="why">{mwhen}, from their diary</div>' if mwhen else "") + "</div>"
                 + (sparkline([m[1] for m in hist[-30:]]) if len(hist) > 1 else "") + "</div>", ""]
        rows = [("Portrait", f"{portrait_params(w['name'], variants.get(w['name'], 0))['family']} curve, seeded by the name"),
                ("Temperament", f"{w['temperament']}: {TEMPERAMENTS[w['temperament']][2]}"), ("Joined", w.get("joined")), ("Left", w.get("left"))]
        page += ["| | |", "| --- | --- |"] + [f"| {k} | {cell(scrub(str(v)))} |" for k, v in rows if v]
        rd = round_by_id.get(str(w["round"])) if w.get("round") else None
        if rd:
            page.append(f"| Hiring round | [{cell(rd['role'])}, {day_label(rd['date'])}]({rel('/story/hiring/' + rd['id'] + '/')}) |")
        elif w.get("round"):
            page.append(f"| Hiring round | {cell(scrub(str(w['round'])))} |")
        page += [f"| {k} | {cell(scrub(str(v)))} |" for k, v in (("Salary (credits, fictional)", w.get("salary")), ("Career goal", w.get("career_goal"))) if v] + [""]
        if hist:
            page += ["## Mood, from the diaries", "", "| When | Feeling | Why |", "| --- | --- | --- |"]
            page += [f"| {m[0]} | {mood_chip(m[1], m[3])} | {cell(m[2])} |" for m in reversed(hist[-10:])] + [""]
        page += [f"## Activity ({len(mine)} most recent)", ""]
        if mine:
            page += ["| When | What | |", "| --- | --- | --- |"]
            for e in mine:
                link = f"[link]({e['link']})" if e.get("link") and e["link"] != "(private)" else ""
                page.append(f"| {fmt_time(e['time'])} | <span class=\"tag t-{esc(e.get('type', ''))}\">{esc(e.get('type', ''))}</span> {cell(e['summary'])} | {link} |")
        else:
            page.append("Nothing logged yet.")
        page += ["", "## Diaries, meetings, and conversations", ""]
        page += (['<ul class="recs">' + "".join(rec_item(s, show_day=True) for s in records) + "</ul>"] if records else ["None yet."])
        memory = load_memory(slug, scrub) if cfg.get("publish_memory") else ""
        if memory:
            page += ["", "## What they remember", "", '<details markdown="1"><summary>The worker\'s own notes, as they stand today</summary>', "", raw(memory), "", "</details>"]
        site.write(os.path.join("cast", f"{slug}.md"), "\n".join(page) + "\n")

    # Story records: each says what kind of record it is, when, and who is in it, with a way back
    for s in story:
        parts = s["path"].split("/")
        rd = round_by_id.get(parts[1]) if len(parts) >= 3 and parts[0] == "hiring" else None
        back = crumbs("/story/hiring/" + rd["id"] + "/", "Hiring round: " + rd["role"]) if rd else crumbs("/story/", "Records")
        kicker = (record_badge(s.get("kind"))
                  + f"<span>{day_label(s['when'][:10])} · {nice_date(s['when'][:10])}, {esc(s['when'][11:16])}</span>")
        sub = person_chips(s["workers"], by_slug)
        if s.get("mood"):
            sub += f'<p class="mood">{mood_chip(s["mood"], s.get("feeling"), s["mood_reason"], big=True)}</p>'
        site.write(os.path.join("story", s["path"] + ".md"),
                   fm({"layout": "default", "title": s["title"], "section": "records"}) + back + page_head(kicker, safe(s["title"]), sub)
                   + "\n\n" + raw(s["body"]))

    # Records: the hiring rounds, then diaries, meetings, and conversations by day
    others = [s for s in story if not s["path"].startswith("hiring/")]
    rec_days = {}
    for s in others:
        rec_days.setdefault(s["when"][:10], []).append(s)
    rgroups = []
    for date in sorted(rec_days, reverse=True):
        items = sorted(rec_days[date], key=lambda m: m["when"], reverse=True)
        rgroups.append(f'<div class="day"><h2 class="day-head"><span>{day_label(date)}</span><small>{nice_date(date)} · '
                       f'{len(items)} record{"s" if len(items) != 1 else ""}</small></h2>'
                       f'<ul class="recs">{"".join(rec_item(s) for s in items)}</ul></div>')
    recs_page = [fm({"layout": "default", "title": "Records", "section": "records"}), "# Records", "",
                 '<p class="lead">Diaries, meetings, conversations, and hiring rounds, as the workers wrote them. '
                 "The reports quote from these records.</p>", ""]
    if round_list:
        recs_page += ['<h2 id="hiring-rounds">Hiring rounds</h2>', "",
                      f'<div class="cards">{"".join(round_card(rd) for rd in round_list)}</div>', ""]
    recs_page += ['<h2 id="by-day">Diaries, meetings, and conversations</h2>', "",
                  (f'<div class="days">{"".join(rgroups)}</div>' if rgroups else "Nothing written yet."), ""]
    site.write(os.path.join("story", "index.md"), "\n".join(recs_page))

    # One page per hiring round: the steps, the candidates with their scorecards, the records
    for rd in round_list:
        n = len(rd["candidates"])
        hired_w = rd["hired"][0] if rd["hired"] else None
        steps = [("Brief", rd["brief"] is not None, rel("/story/" + rd["brief"]["path"] + ".html") if rd["brief"] else ""),
                 (f"Slate of {n}" if n else "Slate", n > 0, ""),
                 (f"{len(rd['interviews'])} interviews" if rd["interviews"] else "Interviews", bool(rd["interviews"]), ""),
                 ("Decision", rd["decision"] is not None, rel("/story/" + rd["decision"]["path"] + ".html") if rd["decision"] else ""),
                 (f"Hired {esc(hired_w['name'])}" if hired_w else "Onboarding", hired_w is not None,
                  rel("/cast/" + hired_w["slug"] + ".html") if hired_w else "")]
        first_open = next((k for k, st in enumerate(steps) if not st[1]), len(steps))
        lis = []
        for k, (label, done, href) in enumerate(steps):
            cls = "done" if k < first_open else "now" if k == first_open else "todo"
            text = f'<a href="{href}">{label}</a>' if href else label
            lis.append(f'<li class="{cls}"><span class="dot"></span><span class="lbl">{text}</span></li>')
        cards = []
        for w in sorted(rd["candidates"], key=lambda x: (x["status"] == "candidate", x["name"])):
            scores = []
            for s in rd["interviews"]:
                if w["slug"] not in s["workers"]:
                    continue
                mean = scorecard_mean(s["body"])
                if mean is None:
                    continue
                mm = re.match(r"interview-([a-z0-9]+)-", s["path"].split("/")[-1])
                by = mm.group(1) if mm else (s["workers"][0] if s["workers"] else "")
                scores.append(f"{mean:.1f} ({esc(by_slug[by]['name'] if by in by_slug else by)})")
            status = badge("Hired", "green") if w["status"] != "candidate" else badge("On the bench", "grey")
            cards.append(f'<a href="{rel("/cast/" + w["slug"] + ".html")}">{portrait_img(w["slug"])}<b>{esc(w["name"])}</b>{status}'
                         + (f'<small class="score">Scorecard average {", ".join(scores)}</small>' if scores else "") + "</a>")
        page = [fm({"layout": "default", "title": "Hiring round: " + rd["role"], "section": "records"}),
                crumbs("/story/#hiring-rounds", "Records"),
                page_head(badge("Hiring round", "blue") + f"<span>{day_label(rd['date'])} · {nice_date(rd['date'])}</span>",
                          safe(rd["role"]), f'<p class="lead">{round_outcome(rd)}</p>'),
                '<ol class="pipe">' + "".join(lis) + "</ol>", "", "## Candidates", "",
                ('<div class="cast">' + "".join(cards) + "</div>" if cards else "No candidates recorded yet."), "",
                "## Records in this round", "",
                ('<ul class="recs">' + "".join(rec_item(s, show_day=True) for s in rd["records"]) + "</ul>" if rd["records"] else "None yet."), ""]
        site.write(os.path.join("story", "hiring", rd["id"], "index.md"), "\n".join(page))

    # Combined log, one table per day
    rows = events[: int(num(cfg.get("log_rows"), 500))]
    log = [fm({"layout": "default", "title": "Log", "section": "log"}), "# The log", "",
           f'<p class="lead">Every notable event, newest first ({len(rows)} shown of {len(events)}; '
           f'<a href="{rel("/log/events.json")}">all of them as JSON</a>). This is the operational record the reports are written from.</p>', ""]
    if rows:
        def day_key(e):
            t = event_time(e)
            return t.date().isoformat() if t else str(e.get("time", ""))[:10]
        counts = {}
        for e in rows:
            counts[day_key(e)] = counts.get(day_key(e), 0) + 1
        cur = None
        for e in rows:
            k = day_key(e)
            if k != cur:
                cur = k
                log += ["", f'## {day_label(k)} <small>{nice_date(k)} · {counts[k]} event{"s" if counts[k] != 1 else ""}</small>', "",
                        "| Time | Who | What | |", "| --- | --- | --- | --- |"]
            t = event_time(e)
            wslug = str(e.get("worker", "")).lower()
            who = (avatars([wslug], by_slug) + f" [{esc(by_slug[wslug]['name'])}]({rel('/cast/' + wslug + '.html')})") if wslug in by_slug else esc(e.get("worker", ""))
            link = f"[link]({e['link']})" if e.get("link") and e["link"] != "(private)" else ""
            log.append(f"| {t.strftime('%H:%M') if t else ''} | {who} | <span class=\"tag t-{esc(e.get('type', ''))}\">{esc(e.get('type', ''))}</span> {cell(e['summary'])} | {link} |")
    else:
        log.append("Nothing logged yet.")
    site.write(os.path.join("log", "index.md"), "\n".join(log) + "\n")
    site.write(os.path.join("log", "events.json"), json.dumps(events, indent=0) + "\n")

    # Usage
    pace = usage.get("pacing") or {}
    five_used, five_budget = num(usage.get("window_5h_usd")), usage.get("five_hour_budget_usd")
    caps = {k: num(v) for k, v in (usage.get("caps") or {}).items()}
    shares = usage.get("shares_7d") or {}
    up = [fm({"layout": "default", "title": "Usage", "section": "usage"}), "# Claude usage", "",
          '<p class="lead">One Claude Max subscription runs the company. The plan meters a rolling 5-hour window, a weekly window, '
          "and a weekly Fable window; the company aims to use the whole weekly allowance by each reset, never early (Tenet 7). "
          "Figures are Claude Code's own cost estimate at API rates.</p>", ""]
    if usage:
        up += ['<div class="panel">',
               (bar("Last 5 hours", five_used, num(five_budget)) if five_budget
                else bar("Last 5 hours", five_used, 0, note=f"${five_used:,.2f} · 5-hour budget not calibrated yet", cls="ok")),
               bar("Today", num(pace.get("today_used_usd")), num(pace.get("today_share_usd")),
                   note=f"${num(pace.get('today_used_usd')):,.2f} of today's share ${num(pace.get('today_share_usd')):,.2f}"),
               bar("This week", num(pace.get("used_week_usd")), num(pace.get("budget_usd"))),
               bar("Fable this week", num(usage.get("fable_week_usd")), num(usage.get("fable_allowance_usd"))),
               "</div>", ""]
        up += ["## Last 7 days, by category", ""]
        if any(num(v) > 0 for v in shares.values()):
            up += [stacked(shares, caps), ""]
        up += ["| Category | Share | Cap |", "| --- | --- | --- |"]
        for c, label in CATEGORY_LABELS:
            cap = f"{caps[c] * 100:.0f}%" if c in caps else "at least 87% (90% in a week without a hiring round)"
            up.append(f"| {c} | {num(shares.get(c)):.1%} | {cap} |")
        up.append("")
        if usage.get("weeks"):
            up += ["## Past weeks", ""]
            for wk in usage["weeks"][-8:]:
                hit = " · limit hit" if wk.get("weekly_limit_hit") else ""
                up.append(bar(f"Week of {wk['start'][:10]}", num(wk["spent_usd"]), num(wk["budget_usd"]),
                              note=f"${num(wk['spent_usd']):,.2f} of ${num(wk['budget_usd']):,.2f}{hit}"))
            up.append("")
    up += ["## The figures", "", usage_block or "No usage recorded yet.", ""]
    site.write("usage.md", "\n".join(up))

    # Requests
    rq = [fm({"layout": "default", "title": "Requests", "section": "requests"}), "# Requests for the Investors", ""]
    if requests is None:
        rq += ["Open requests are listed here when the site is built on the company's Mac mini.", ""]
    else:
        labels = {"emergency": "Emergency", "urgent": "Urgent request", "report": "A report's questions", "pitch": "The Pitch"}
        if requests:
            rq += ["Open items, most urgent first. Each one is answered on its GitHub issue, which only the Investors can see.", "",
                   "| | Request | Opened | Replies |", "| --- | --- | --- | --- |"]
            rq += [f"| <span class=\"tag\">{labels[r['kind']]}</span> | [{cell(esc(r['title']))}]({r['url']}) | {fmt_time(r['created'])} | {r['comments']} |" for r in requests]
        else:
            rq += ["Nothing is waiting on the Investors right now.", ""]
    if msg_url:
        rq += ["", f"**[Message the company]({msg_url})**: a new issue in the company repository. The company reads it within 15 minutes, "
               "acknowledges it, and acts on it (Commandment 57).", ""]
    site.write("requests.md", "\n".join(rq) + "\n")

    # Pages the company writes: about, privacy, support, press, under the About tab with their own tabs
    pages = {"about": "About", "privacy": "Privacy policy", "support": "Support", "press": "Press kit"}
    short = {"about": "About", "privacy": "Privacy", "support": "Support", "press": "Press kit"}
    for key, title in pages.items():
        src = os.path.join(ROOT, "site", "pages", f"{key}.md")
        if os.path.exists(src):
            meta, body = front_matter(read(src))
            body = scrub(body)
        else:
            meta, body = {}, {"about": f"# About\n\n{cfg['tagline']}\n\n{cfg['disclosure']}\n",
                              "privacy": "# Privacy policy\n\nTo be written before launch.\n",
                              "support": "# Support\n\nSupport details are posted here before launch.\n",
                              "press": "# Press kit\n\nThe press kit is published here at launch.\n"}[key]
        sub = "".join(f'<a href="{rel("/" + k + ".html")}"{" aria-current=" + chr(34) + "page" + chr(34) if k == key else ""}>{v}</a>' for k, v in short.items())
        site.write(f"{key}.md", fm({"layout": "default", "title": meta.get("title", title), "section": "about"})
                   + f'<div class="subtabs" role="navigation" aria-label="About the experiment">{sub}</div>\n\n' + raw(body))

    site.clean()
    return {"reports": len(reports), "workers": len(workers), "events": len(events), "story": len(story),
            "requests": len(requests) if requests else 0}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True, help="the site repository's working tree")
    p.add_argument("--no-gh", action="store_true", help="don't ask GitHub for open requests")
    args = p.parse_args()
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    stats = build(out, use_gh=not args.no_gh)
    print("site built: " + ", ".join(f"{k} {v}" for k, v in stats.items()))


if __name__ == "__main__":
    main()
