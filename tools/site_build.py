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
from portrait import portrait_svg, default_temperament, TEMPERAMENTS  # noqa: E402

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
        return d.strftime("%b %-d, %H:%M")
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
        meta["path"] = os.path.splitext(rel_path)[0]
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
:root{--ink:#1b1b1b;--muted:#5f5f5f;--line:#e4e4e4;--bg:#fff;--accent:#2b5bd7;--soft:#f4f5f8;--ok:#2f9e5b;--warm:#d9a21b;--hot:#d9442b;--pink:#c04fb0}
@media (prefers-color-scheme:dark){:root{--ink:#ececec;--muted:#a8a8a8;--line:#333;--bg:#111;--accent:#8ab0ff;--soft:#1b1b1b;--ok:#4fc27a;--warm:#e6b94a;--hot:#ef6a52;--pink:#e07bd2}}
*{box-sizing:border-box}body{margin:0;font:17px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}
a{color:var(--accent)}header,main,footer{max-width:960px;margin:0 auto;padding:0 18px}
header{padding-top:22px;display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 22px}header .brand{font-weight:800;font-size:22px;letter-spacing:-.01em;text-decoration:none;color:var(--ink)}
nav a{margin-right:16px;font-size:15px;text-decoration:none}nav a:hover{text-decoration:underline}
.notice{flex-basis:100%;background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:9px 14px;margin:14px 0 0;font-size:13.5px;color:var(--muted)}
h1{font-size:34px;letter-spacing:-.02em;margin:18px 0 8px}h2{font-size:22px;margin:30px 0 10px}h3{font-size:17px;margin:22px 0 8px}
.lead{font-size:19px;color:var(--muted);margin:0 0 18px}
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
.strip{display:grid;grid-template-columns:1fr;gap:4px 18px;background:var(--soft);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:12px 0 18px;font-size:14px}
.strip .row{display:flex;align-items:center;gap:12px}.strip .bar{flex:1;margin:4px 0}.strip .track{flex:1}
table{border-collapse:collapse;width:100%;font-size:15px;margin:12px 0}th,td{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top}
img.portrait{width:120px;height:120px;border-radius:16px;float:right;margin:0 0 12px 18px;background:var(--soft)}
.cast{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px}.cast a{display:block;text-decoration:none;color:inherit;border:1px solid var(--line);border-radius:14px;padding:12px;background:var(--soft)}
.cast img{width:100%;aspect-ratio:1;border-radius:12px;display:block;margin-bottom:8px;background:var(--bg)}.cast small{color:var(--muted);display:block}
.mood{display:flex;align-items:center;gap:12px;margin:8px 0 14px;flex-wrap:wrap}.mood .why{color:var(--muted);font-size:14.5px}.mood .spark{margin-left:auto}
.mood-word{font-weight:700;padding:1px 8px;border-radius:8px;white-space:nowrap}.mood-word.big{font-size:20px;padding:2px 10px}.mood-why{color:var(--muted)}
.mood-word.lv0{color:var(--muted);background:var(--line)}.mood-word.lv1{color:#fff;background:#c43d2b}.mood-word.lv2{color:#2b1a00;background:#e59a3a}.mood-word.lv3{color:#2b2400;background:#e7cf4a}.mood-word.lv4{color:#0f2e1a;background:#7fd19a}.mood-word.lv5{color:#082a12;background:#3fbf6e}
.cast .mood-word{display:inline-block;margin-top:6px;font-size:13px}
details{margin:12px 0}summary{cursor:pointer}footer{padding:28px 18px 44px;color:var(--muted);font-size:14px}blockquote{border-left:3px solid var(--line);margin:0;padding-left:12px;color:var(--muted)}
.tag{font-size:12px;padding:1px 7px;border:1px solid var(--line);border-radius:10px;color:var(--muted);white-space:nowrap}
.reports{list-style:none;padding:0}.reports li{margin:8px 0}.latest{font-size:15px;color:var(--muted);margin:6px 0 0}
@media (min-width:720px){.hero.two{grid-template-columns:3fr 2fr}.strip{grid-template-columns:1fr 1fr}}
@media (prefers-reduced-motion:reduce){.bar-fill{transition:none}}
</style>
</head>
<body>
<header>
<a class="brand" href="{{ '/' | relative_url }}">{{ site.title }}</a>
<nav><a href="{{ '/' | relative_url }}">Home</a><a href="{{ '/reports/' | relative_url }}">Reports</a><a href="{{ '/cast/' | relative_url }}">Cast</a><a href="{{ '/log/' | relative_url }}">Log</a><a href="{{ '/usage.html' | relative_url }}">Usage</a><a href="{{ '/requests.html' | relative_url }}">Requests</a><a href="{{ '/about.html' | relative_url }}">About</a></nav>
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
        self.written.add(rel_path)

    def copy(self, src, rel_path):
        path = os.path.join(self.out, rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copyfile(src, path)
        self.written.add(rel_path)

    def clean(self):
        """Remove everything we did not write this time, keeping git's files and a CNAME."""
        for dirpath, dirnames, filenames in os.walk(self.out):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for name in filenames:
                r = os.path.relpath(os.path.join(dirpath, name), self.out)
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
    for w in workers:
        site.write(os.path.join("assets", "portraits", f"{w['slug']}.svg"),
                   portrait_svg(w["name"], w["temperament"], latest_mood(w["slug"])[1]))

    def portrait_img(slug, cls=""):
        c = f' class="{cls}"' if cls else ""
        return f'<img{c} src="{rel("/assets/portraits/" + slug + ".svg")}" alt="">'

    # Reports as posts (newest first, RSS for free), each with a generated progress strip
    usage_days = usage_file.get("days") or {}
    weekly_budget = num(usage_file.get("weekly_budget_usd"), 150)
    hist_by_date = {h.get("date"): h for h in history if h.get("date")}
    for r in reports:
        kind = r.get("kind", "report")
        rday = int(num(r.get("day"), 0))
        fallback = revenue if r is reports[0] else 0.0
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
        head = {"layout": "default", "title": r["title"], "date": f"{r['when']}:00", "kind": kind,
                "day": r.get("day"), "number": r.get("number")}
        extra = ""
        if r.get("issue"):
            extra = (f"\n> **Investors:** this report's private copy, with its Questions for the Investors, is "
                     f"[on GitHub]({r['issue']}). Answer there by midnight.\n")
        site.write(os.path.join("_posts", f"{r['date']}-{r['slug']}.md"),
                   fm(head) + "\n".join(strip) + "\n" + extra + "\n" + raw(r["body"]))

    # Reports index
    site.write(os.path.join("reports", "index.md"), "\n".join([
        fm({"layout": "default", "title": "Reports"}), "# Reports", "",
        '<p class="lead">A report is published every evening, and every morning after a night when something happened. Newest first; every report has a permanent link.</p>', "",
        '<ul class="reports">', "{% for post in site.posts %}",
        '<li><b><a href="{{ post.url | relative_url }}">{{ post.title }}</a></b> <span class="tag">{{ post.kind }}</span> · Day {{ post.day }} · {{ post.date | date: "%b %-d, %Y %H:%M" }}</li>',
        "{% endfor %}", "</ul>", ""]))

    # Home: the five things that matter, then the cast, then the reports
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
    index = [fm({"layout": "default", "title": "Home", "description": cfg["tagline"]}),
             f"# {cfg['name']}", "", f'<p class="lead">{esc(cfg["tagline"])}</p>', "",
             '<div class="tiles">' + "".join(tiles) + "</div>", hero, ""]
    if latest:
        index += ["## Latest", "",
                  f'<p><b><a href="{rel("/reports/" + latest["slug"] + "/")}">{esc(latest["title"])}</a></b> <span class="tag">{esc(latest.get("kind", ""))}</span> · {latest["when"]}</p>', ""]
    if active:
        index += ["## The cast", "", '<div class="cast">' + cast_strip + "</div>", ""]
    index += ["## Reports", "", '<ul class="reports">', "{% for post in site.posts limit:8 %}",
              '<li><b><a href="{{ post.url | relative_url }}">{{ post.title }}</a></b> <span class="tag">{{ post.kind }}</span> · Day {{ post.day }} · {{ post.date | date: "%b %-d, %H:%M" }}</li>',
              "{% endfor %}", "</ul>",
              f'<p><a href="{rel("/reports/")}">All reports</a>' + (f' · <a href="{rel("/requests.html")}">open requests</a> · <a href="{msg_url}">message the company</a>' if msg_url else "") + "</p>", ""]
    site.write("index.md", "\n".join(index))

    # Cast
    cast = [fm({"layout": "default", "title": "Cast"}), "# The cast", "",
            '<p class="lead">Every worker is an AI-simulated character with a first name, a role, a personality, and a career goal. '
            "Portraits are drawn by code from a mathematical expression seeded by the name, and move in a way chosen by the worker's temperament; "
            "the word under each name is the feeling from their latest diary, in their own word.</p>", ""]
    for status, label in STATUS_GROUPS:
        group = [w for w in workers if w["status"] == status or (status == "former" and w["status"] not in ("active", "candidate"))]
        if not group:
            continue
        cast += [f"## {label}", "", '<div class="cast">']
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
        page = [fm({"layout": "default", "title": w["name"]}), portrait_img(slug, "portrait"), f"# {esc(w['name'])}", "",
                f"**{esc(w.get('role', ''))}**" + (f" · reports to {esc(w['manager'])}" if w.get("manager") else "")
                + (f" · {esc(w['status'])}" if w.get("status") != "active" else ""), ""]
        if w.get("bio"):
            page += [scrub(str(w["bio"])), ""]
        page += [f'<div class="mood"><div>{mood_chip(mlevel, mword, mreason, big=True)}'
                 + (f'<div class="why">{mwhen}, from their diary</div>' if mwhen else "") + "</div>"
                 + (sparkline([m[1] for m in hist[-30:]]) if len(hist) > 1 else "") + "</div>", ""]
        rows = [("Temperament", f"{w['temperament']}: {TEMPERAMENTS[w['temperament']][3]}"), ("Joined", w.get("joined")), ("Left", w.get("left")),
                ("Hiring round", w.get("round")), ("Salary (credits, fictional)", w.get("salary")), ("Career goal", w.get("career_goal"))]
        page += ["| | |", "| --- | --- |"] + [f"| {k} | {cell(scrub(str(v)))} |" for k, v in rows if v] + [""]
        if hist:
            page += ["## Mood, from the diaries", "", "| When | Feeling | Why |", "| --- | --- | --- |"]
            page += [f"| {m[0]} | {mood_chip(m[1], m[3])} | {cell(m[2])} |" for m in reversed(hist[-10:])] + [""]
        page += [f"## Activity ({len(mine)} most recent)", ""]
        if mine:
            page += ["| When | What | |", "| --- | --- | --- |"]
            for e in mine:
                link = f"[link]({e['link']})" if e.get("link") and e["link"] != "(private)" else ""
                page.append(f"| {fmt_time(e['time'])} | <span class=\"tag\">{esc(e.get('type', ''))}</span> {cell(e['summary'])} | {link} |")
        else:
            page.append("Nothing logged yet.")
        page += ["", "## Diaries, meetings, and conversations", ""]
        page += [f"- [{esc(s['title'])}]({rel('/story/' + s['path'] + '.html')}) · {s['when']} · {esc(s.get('kind', ''))}" for s in records] or ["None yet."]
        memory = load_memory(slug, scrub) if cfg.get("publish_memory") else ""
        if memory:
            page += ["", "## What they remember", "", "<details><summary>The worker's own notes, as they stand today</summary>", "", raw(memory), "", "</details>"]
        site.write(os.path.join("cast", f"{slug}.md"), "\n".join(page) + "\n")

    # Story records
    for s in story:
        who = ", ".join(f"[{esc(by_slug[x]['name'])}]({rel('/cast/' + x + '.html')})" if x in by_slug else x for x in s["workers"])
        head = fm({"layout": "default", "title": s["title"]})
        mood_line = ""
        if s.get("mood"):
            mood_line = "\n\n" + mood_chip(s["mood"], s.get("feeling"), s["mood_reason"])
        site.write(os.path.join("story", s["path"] + ".md"),
                   head + f"# {esc(s['title'])}\n\n*{s['when']}* · {esc(s.get('kind', 'record'))}" + (f" · {who}" if who else "") + mood_line
                   + "\n\n" + raw(s["body"]))

    # Combined log
    rows = events[: int(num(cfg.get("log_rows"), 500))]
    log = [fm({"layout": "default", "title": "Log"}), "# The log", "",
           f'<p class="lead">Every notable event, newest first ({len(rows)} shown of {len(events)}; '
           f'<a href="{rel("/log/events.json")}">all of them as JSON</a>). This is the operational record the reports are written from.</p>', ""]
    if rows:
        log += ["| When | Who | What | |", "| --- | --- | --- | --- |"]
        for e in rows:
            wslug = str(e.get("worker", "")).lower()
            who = f"[{esc(by_slug[wslug]['name'])}]({rel('/cast/' + wslug + '.html')})" if wslug in by_slug else esc(e.get("worker", ""))
            link = f"[link]({e['link']})" if e.get("link") and e["link"] != "(private)" else ""
            log.append(f"| {fmt_time(e['time'])} | {who} | <span class=\"tag\">{esc(e.get('type', ''))}</span> {cell(e['summary'])} | {link} |")
    else:
        log.append("Nothing logged yet.")
    site.write(os.path.join("log", "index.md"), "\n".join(log) + "\n")
    site.write(os.path.join("log", "events.json"), json.dumps(events, indent=0) + "\n")

    # Usage
    pace = usage.get("pacing") or {}
    five_used, five_budget = num(usage.get("window_5h_usd")), usage.get("five_hour_budget_usd")
    caps = {k: num(v) for k, v in (usage.get("caps") or {}).items()}
    shares = usage.get("shares_7d") or {}
    up = [fm({"layout": "default", "title": "Usage"}), "# Claude usage", "",
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
    rq = [fm({"layout": "default", "title": "Requests"}), "# Requests for the Investors", ""]
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

    # Pages the company writes: about, privacy, support, press
    pages = {"about": "About", "privacy": "Privacy policy", "support": "Support", "press": "Press kit"}
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
        site.write(f"{key}.md", fm({"layout": "default", "title": meta.get("title", title)}) + raw(body))

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
