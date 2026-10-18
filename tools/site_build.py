#!/usr/bin/env python3
"""Build the public site from the company's records. No Claude, no dependencies.

  python3 tools/site_build.py --out ../site        # write the Jekyll source into the site repo
  python3 tools/site_build.py --out /tmp/site --no-gh

The output is a Jekyll site that GitHub Pages renders on push. It is rebuilt from
scratch on every run (everything in --out except .git and CNAME is replaced).

What it reads (the data contract; the Handbook may not change these shapes):
  site.json                 company name, tagline, repo, site URL, options
  reports/*.md              the public report, without its questions; front matter: title, number, day, date, time, kind, issue
  story/*.md                front matter: title, date, time, kind, workers (comma list)
  personnel/registry.json   [{name, role, manager, status (active|candidate|former), salary, career_goal, joined, left, bio}]
  personnel/portraits/*.svg one per worker
  .claude/agent-memory/<name>/MEMORY.md   what each worker remembers (published if publish_memory)
  log/events.jsonl          {time, worker, type, summary, link}
  ops/scoreboard.json       {revenue_usd, spent_usd, day, days_left, app_name, app_store_url, status}
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

DEFAULT_SITE = {
    "name": "The Company",
    "tagline": "An AI-run company with 30 days to build and sell an iOS app.",
    "company_repo": "",          # "org/company": enables the Requests page and the message link
    "url": "",                    # "https://org.github.io/site"
    "publish_memory": True,
    "log_rows": 500,
    "disclosure": "Everyone who works here is an AI-simulated character. The business is real and is an "
                  "experiment run by two private individuals. Every report is true to the operational log.",
}
EVENT_LIMIT_PER_WORKER = 200


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
        if isinstance(v, (list, dict)):
            v = json.dumps(v)
        else:
            v = json.dumps(str(v))
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


def run(cmd, timeout=60):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


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
        rel = os.path.relpath(path, os.path.join(ROOT, "story"))
        if rel.startswith("private" + os.sep):
            continue
        meta, body = front_matter(read(path))
        meta.setdefault("title", os.path.splitext(os.path.basename(path))[0].replace("-", " "))
        meta["workers"] = [w.strip().lower() for w in re.split(r"[,\s]+", meta.get("workers", "")) if w.strip()]
        meta["when"] = when(meta)
        meta["path"] = os.path.splitext(rel)[0]
        meta["body"] = scrub(body)
        out.append(meta)
    out.sort(key=lambda m: m["when"], reverse=True)
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


def load_json(rel):
    p = os.path.join(ROOT, rel)
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


# ---------- writers ----------

LAYOUT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% if page.title %}{{ page.title }} · {% endif %}{{ site.title }}</title>
<meta name="description" content="{{ page.description | default: site.description }}">
{% feed_meta %}
<style>
:root{--ink:#1b1b1b;--muted:#5d5d5d;--line:#e3e3e3;--bg:#fff;--accent:#2b5bd7;--soft:#f5f6f8}
@media (prefers-color-scheme:dark){:root{--ink:#e8e8e8;--muted:#a6a6a6;--line:#333;--bg:#121212;--accent:#8ab0ff;--soft:#1c1c1c}}
*{box-sizing:border-box}body{margin:0;font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}
a{color:var(--accent)}header,main,footer{max-width:880px;margin:0 auto;padding:0 16px}
header{padding-top:20px}header .brand{font-weight:700;font-size:20px;text-decoration:none;color:var(--ink)}
nav a{margin-right:14px;font-size:15px}.notice{background:var(--soft);border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:16px 0;font-size:14px;color:var(--muted)}
.score{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}.score div{flex:1 1 140px;background:var(--soft);border:1px solid var(--line);border-radius:8px;padding:10px 14px}
.score b{display:block;font-size:22px}.score span{font-size:13px;color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:15px;margin:12px 0}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
img.portrait{width:96px;height:96px;border-radius:12px;float:right;margin:0 0 12px 16px;background:var(--soft)}
.cast{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px}.cast a{display:block;text-decoration:none;color:inherit;border:1px solid var(--line);border-radius:10px;padding:12px}
.cast img{width:72px;height:72px;border-radius:10px;display:block;margin-bottom:8px;background:var(--soft)}.cast small{color:var(--muted)}
details{margin:12px 0}summary{cursor:pointer}footer{padding:24px 16px 40px;color:var(--muted);font-size:14px}blockquote{border-left:3px solid var(--line);margin:0;padding-left:12px;color:var(--muted)}
.tag{font-size:12px;padding:1px 7px;border:1px solid var(--line);border-radius:10px;color:var(--muted)}
</style>
</head>
<body>
<header>
<a class="brand" href="{{ '/' | relative_url }}">{{ site.title }}</a>
<nav><a href="{{ '/' | relative_url }}">Reports</a><a href="{{ '/cast/' | relative_url }}">Cast</a><a href="{{ '/log/' | relative_url }}">Log</a><a href="{{ '/usage.html' | relative_url }}">Usage</a><a href="{{ '/requests.html' | relative_url }}">Requests</a><a href="{{ '/about.html' | relative_url }}">About</a></nav>
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

    def write(self, rel, text):
        path = os.path.join(self.out, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.written.add(rel)

    def copy(self, src, rel):
        path = os.path.join(self.out, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copyfile(src, path)
        self.written.add(rel)

    def clean(self):
        """Remove everything we did not write this time, keeping git's files and a CNAME."""
        for dirpath, dirnames, filenames in os.walk(self.out):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for name in filenames:
                rel = os.path.relpath(os.path.join(dirpath, name), self.out)
                if rel not in self.written and rel != "CNAME":
                    os.remove(os.path.join(dirpath, name))
        for dirpath, dirnames, filenames in list(os.walk(self.out, topdown=False)):
            if dirpath != self.out and ".git" not in dirpath and not os.listdir(dirpath):
                os.rmdir(dirpath)


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
    requests = load_requests(cfg, use_gh)
    by_slug = {w["slug"]: w for w in workers}
    repo = cfg.get("company_repo") or ""
    msg_url = (f"https://github.com/{repo}/issues/new?labels=directive&title=Message+from+the+Investors" if repo else "")

    # Jekyll config and layout
    site.write("_config.yml", "\n".join([
        f"title: {json.dumps(cfg['name'])}",
        f"description: {json.dumps(cfg['tagline'])}",
        f"url: {json.dumps(cfg.get('url') or '')}",
        f"disclosure: {json.dumps(cfg['disclosure'])}",
        "plugins: [jekyll-feed]",
        "feed: {path: feed.xml}",
        "permalink: /reports/:title/",
        "markdown: kramdown",
        "exclude: [README.md]",
        "defaults:",
        "  - scope: {path: \"\"}",
        "    values: {layout: default}",
        "",
    ]))
    site.write("_layouts/default.html", LAYOUT)
    site.write("README.md", f"# {cfg['name']} site\n\nGenerated by tools/site_build.py in the company repository. Don't edit by hand.\n")

    # Portraits
    for p in glob.glob(os.path.join(ROOT, "personnel", "portraits", "*.svg")):
        site.copy(p, os.path.join("assets", "portraits", os.path.basename(p)))

    # Reports as posts (newest first on the index, RSS for free)
    for r in reports:
        kind = r.get("kind", "report")
        head = {"layout": "default", "title": r["title"], "date": f"{r['when']}:00", "kind": kind,
                "day": r.get("day"), "number": r.get("number")}
        extra = ""
        if r.get("issue"):
            extra = (f"\n\n> **Investors:** this report's private copy, with its Questions for the Investors, is "
                     f"[on GitHub]({r['issue']}). Answer there by midnight.\n")
        site.write(os.path.join("_posts", f"{r['date']}-{r['slug']}.md"), fm(head) + extra + "\n" + raw(r["body"]))

    # Index: scoreboard + report list
    score = ""
    if board:
        goal = 200.0
        rev = float(board.get("revenue_usd", 0) or 0)
        score = "\n".join([
            '<div class="score">',
            f'<div><b>${rev:,.2f}</b><span>net proceeds, of ${goal:,.0f}</span></div>',
            f'<div><b>Day {esc(board.get("day", "?"))}</b><span>{esc(board.get("days_left", "?"))} days left</span></div>',
            f'<div><b>${float(board.get("spent_usd", 0) or 0):,.2f}</b><span>real spending so far</span></div>',
            f'<div><b>{esc(board.get("status", "building"))}</b><span>{esc(board.get("app_name", "the app"))}'
            + (f' · <a href="{esc(board["app_store_url"])}">App Store</a>' if board.get("app_store_url") else "") + '</span></div>',
            "</div>", ""])
    index = [fm({"layout": "default", "title": "Reports", "description": cfg["tagline"]}), f"# {cfg['name']}", "",
             cfg["tagline"], "", score,
             "A report is published every evening, and every morning after a night when something happened. "
             "The newest is first; every report has a permanent link.", "",
             "{% for post in site.posts %}",
             "- **[{{ post.title }}]({{ post.url | relative_url }})** <span class=\"tag\">{{ post.kind }}</span> "
             "· Day {{ post.day }} · {{ post.date | date: \"%b %-d, %Y %H:%M\" }}",
             "{% endfor %}", ""]
    if msg_url:
        index += ["", f"Investors: [open requests](requests.html) · [message the company]({msg_url})", ""]
    site.write("index.md", "\n".join(index))

    # Cast
    cast = [fm({"layout": "default", "title": "Cast"}), "# The cast", "",
            "Every worker is an AI-simulated character with a first name, a role, a personality, and a career goal. "
            "Portraits are drawn by code from a mathematical expression seeded by the name.", ""]
    for status, label in (("active", "Working here now"), ("candidate", "Considered, not hired"), ("former", "Former workers")):
        group = [w for w in workers if w["status"] == status or (status == "former" and w["status"] not in ("active", "candidate"))]
        if not group:
            continue
        cast += [f"## {label}", "", '<div class="cast">']
        for w in group:
            img = f'<img src="{{{{ "/assets/portraits/{w["slug"]}.svg" | relative_url }}}}" alt="">' if os.path.exists(
                os.path.join(ROOT, "personnel", "portraits", f"{w['slug']}.svg")) else ""
            cast.append(f'<a href="{{{{ "/cast/{w["slug"]}.html" | relative_url }}}}">{img}<b>{esc(w["name"])}</b><br>'
                        f'<small>{esc(w.get("role", ""))}</small></a>')
        cast += ["</div>", ""]
    site.write(os.path.join("cast", "index.md"), "\n".join(cast))

    for w in workers:
        slug = w["slug"]
        mine = [e for e in events if str(e.get("worker", "")).lower() == slug][:EVENT_LIMIT_PER_WORKER]
        records = [s for s in story if slug in s["workers"]]
        img = (f'<img class="portrait" src="{{{{ "/assets/portraits/{slug}.svg" | relative_url }}}}" alt="">'
               if os.path.exists(os.path.join(ROOT, "personnel", "portraits", f"{slug}.svg")) else "")
        page = [fm({"layout": "default", "title": w["name"]}), img, f"# {esc(w['name'])}", "",
                f"**{esc(w.get('role', ''))}**" + (f" · reports to {esc(w['manager'])}" if w.get("manager") else "")
                + (f" · {esc(w['status'])}" if w.get("status") != "active" else ""), ""]
        if w.get("bio"):
            page += [scrub(str(w["bio"])), ""]
        rows = [("Joined", w.get("joined")), ("Left", w.get("left")), ("Salary (credits, fictional)", w.get("salary")),
                ("Career goal", w.get("career_goal"))]
        page += ["| | |", "| --- | --- |"] + [f"| {k} | {cell(scrub(str(v)))} |" for k, v in rows if v] + [""]
        page += [f"## Activity ({len(mine)} most recent)", ""]
        if mine:
            page += ["| When | What | |", "| --- | --- | --- |"]
            for e in mine:
                link = f"[link]({e['link']})" if e.get("link") and e["link"] != "(private)" else ""
                page.append(f"| {fmt_time(e['time'])} | <span class=\"tag\">{esc(e.get('type', ''))}</span> {cell(e['summary'])} | {link} |")
        else:
            page.append("Nothing logged yet.")
        page += ["", "## Diaries, meetings, and conversations", ""]
        page += [f"- [{esc(s['title'])}]({{{{ \"/story/{s['path']}.html\" | relative_url }}}}) · {s['when']} · {esc(s.get('kind', ''))}"
                 for s in records] or ["None yet."]
        memory = load_memory(slug, scrub) if cfg.get("publish_memory") else ""
        if memory:
            page += ["", "## What they remember", "", "<details><summary>The worker's own notes, as they stand today</summary>", "",
                     raw(memory), "", "</details>"]
        site.write(os.path.join("cast", f"{slug}.md"), "\n".join(page) + "\n")

    # Story records
    for s in story:
        who = ", ".join(f"[{esc(by_slug[x]['name'])}]({{{{ \"/cast/{x}.html\" | relative_url }}}})" if x in by_slug else x
                        for x in s["workers"])
        head = fm({"layout": "default", "title": s["title"]})
        site.write(os.path.join("story", s["path"] + ".md"),
                   head + f"# {esc(s['title'])}\n\n*{s['when']}* · {esc(s.get('kind', 'record'))}" + (f" · {who}" if who else "")
                   + "\n\n" + raw(s["body"]))

    # Combined log
    rows = events[: int(cfg.get("log_rows", 500))]
    log = [fm({"layout": "default", "title": "Log"}), "# The log", "",
           f"Every notable event, newest first ({len(rows)} shown of {len(events)}; "
           "[all of them as JSON](events.json)). This is the operational record the reports are written from.", ""]
    if rows:
        log += ["| When | Who | What | |", "| --- | --- | --- | --- |"]
        for e in rows:
            wslug = str(e.get("worker", "")).lower()
            who = f"[{esc(by_slug[wslug]['name'])}]({{{{ \"/cast/{wslug}.html\" | relative_url }}}})" if wslug in by_slug else esc(e.get("worker", ""))
            link = f"[link]({e['link']})" if e.get("link") and e["link"] != "(private)" else ""
            log.append(f"| {fmt_time(e['time'])} | {who} | <span class=\"tag\">{esc(e.get('type', ''))}</span> {cell(e['summary'])} | {link} |")
    else:
        log.append("Nothing logged yet.")
    site.write(os.path.join("log", "index.md"), "\n".join(log) + "\n")
    site.write(os.path.join("log", "events.json"), json.dumps(events, indent=0) + "\n")

    # Usage
    pace = usage.get("pacing", {})
    up = [fm({"layout": "default", "title": "Usage"}), "# Claude usage", "",
          "The company runs on one Claude Max subscription. The plan meters a rolling 5-hour window, a weekly window, "
          "and a weekly Fable window; the company aims to use the whole weekly allowance by each reset (Tenet 7). "
          "Figures are Claude Code's own cost estimate at API rates, the unit the company budgets in.", ""]
    up += [usage_block or "No usage recorded yet.", ""]
    shares = usage.get("shares_7d") or {}
    if shares:
        up += ["## Last 7 days, by category", "", "| Category | Share | Cap |", "| --- | --- | --- |"]
        caps = usage.get("caps") or {}
        for c in ("project", "reports", "meetings", "hiring", "talk"):
            up.append(f"| {c} | {shares.get(c, 0):.1%} | {('%.0f%%' % (caps[c] * 100)) if c in caps else 'at least 87%'} |")
        up.append("")
    if usage.get("weeks"):
        up += ["## Past weeks", "", "| Week of | Spent | Budget | Fable | Limit hit |", "| --- | --- | --- | --- | --- |"]
        for wk in usage["weeks"][-8:]:
            up.append(f"| {wk['start'][:10]} | ${wk['spent_usd']:.2f} | ${wk['budget_usd']:.2f} | ${wk['fable_spent_usd']:.2f} | "
                      f"{'weekly' if wk.get('weekly_limit_hit') else ''} {'Fable' if wk.get('fable_limit_hit') else ''} |")
        up.append("")
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
            rq += [f"| <span class=\"tag\">{labels[r['kind']]}</span> | [{cell(esc(r['title']))}]({r['url']}) | {fmt_time(r['created'])} | {r['comments']} |"
                   for r in requests]
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

    site.write(".nojekyll-check", "")  # harmless marker so an empty site still has a file to commit
    site.written.discard(".nojekyll-check")
    os.remove(os.path.join(out, ".nojekyll-check"))
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
