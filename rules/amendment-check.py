#!/usr/bin/env python3
"""Checks what a session changed in amendments.md (Commandment 59). The supervisor runs it after
every session, with the commit the session started from:

    python3 -I rules/amendment-check.py <commit>

amendments.md loads into every session as instructions, so only an Investor's own words may go in.
A new entry stays only if its header names an allowlisted account and links to an issue or comment
in the company's own repository, GitHub confirms that account wrote it, the quoted words appear in
it, and the entry holds nothing but the header, the quote, and the Affects and Effect lines. Any
other change goes back: a failing entry is removed, and an earlier entry or the file's opening text
that the session changed is restored. Each change prints one line, which the supervisor sends to
the Investors.

A message an Investor types into a session on the Mac mini can't be checked this way, so only the
sessions the supervisor starts are checked; an Investor at the Mac commits such an amendment from
that session. Investors own this file.
"""
import json
import os
import re
import shlex
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILE = os.path.join(ROOT, "amendments.md")
NONE_YET = "(No amendments yet.)"
HEADER = re.compile(r"^## (\d{4}-\d{2}-\d{2} \d{1,2}:\d{2}) ET\s+[—–-]+\s+@?([A-Za-z0-9-]{1,39})\s+[—–-]+\s+<?(\S+?)>?\s*$")
LINK = re.compile(r"^https://github\.com/([^/\s]+/[^/\s#]+)/issues/(\d+)(?:#issuecomment-(\d+))?$")


def run(args):
    try:
        out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, cwd=ROOT)
        return out.returncode, out.stdout, out.stderr
    except (OSError, subprocess.TimeoutExpired):
        return 1, "", ""


def split(text):
    """(opening text, [entry, ...]). An entry runs from its "## " header to the next; headers inside
    a code fence (the format example) belong to the opening text."""
    head, out, fence = [], [], False
    for line in text.replace("\r\n", "\n").splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            fence = not fence
        if not fence and line.startswith("## "):
            out.append(line)
        elif out:
            out[-1] += line
        else:
            head.append(line)
    return "".join(head), out


def plain(text):
    return " ".join(text.replace("\r", "").split())


def without_none_yet(head):
    return "".join(line for line in head.splitlines(keepends=True) if line.strip() != NONE_YET)


def allowlist():
    try:
        with open(os.path.join(ROOT, "investors", "allowlist.md"), encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return set()
    names = {line.strip().lstrip("@").strip().lower() for line in lines}
    return {n for n in names if re.fullmatch(r"[a-z0-9-]{1,39}", n)}


def company_repo():
    r = os.environ.get("COMPANY_REPO")
    if r:
        return r.lower()
    url = run(["git", "remote", "get-url", "origin"])[1].strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1).lower() if m else None


def message(link, slug, issue, comment):
    """{"user", "body", "title"} for the issue or comment at link, from GitHub; from the inbox's own
    log (ops/inbox/messages.jsonl) only if GitHub can't be reached."""
    path = f"repos/{slug}/issues/comments/{comment}" if comment else f"repos/{slug}/issues/{issue}"
    base = shlex.split(os.environ.get("GH_CMD") or "gh")
    code, out, err = run([*base, "api", "-X", "GET", path, "--jq", "{user: .user.login, body: .body, title: .title, url: .html_url} | @json"])
    found = []
    for line in out.splitlines() if code == 0 else []:
        try:
            found.append(json.loads(line))
        except ValueError:
            pass
    hits = [m for m in found if isinstance(m, dict) and (m.get("url") or "").strip() == link]
    if hits or len(found) == 1:
        return (hits or found)[0]
    if code == 0 or re.search(r"HTTP 4\d\d", err):   # GitHub answered: there is no such message
        return None
    print(f"amendment check: GitHub unreachable; checking {link} against the inbox's log", file=sys.stderr)
    try:
        with open(os.path.join(ROOT, "ops", "inbox", "messages.jsonl"), encoding="utf-8") as f:
            for line in f:
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if (m.get("url") or "").strip() == link:
                    return {"user": m.get("author"), "body": m.get("body"), "title": m.get("title")}
    except OSError:
        pass
    return None


def problem(entry, allowed, slug):
    """Why the entry can't stay, or None."""
    lines = entry.rstrip("\n").split("\n")
    m = HEADER.match(lines[0])
    if not m:
        return "its header isn't \"## YYYY-MM-DD HH:MM ET — <GitHub username> — <link>\""
    user, link = m.group(2).lower(), m.group(3)
    if user not in allowed:
        return f"{m.group(2)} isn't on the Investors' allowlist"
    lm = LINK.match(link)
    if not lm or not slug or lm.group(1).lower() != slug:
        return "its link isn't an issue or comment in the company's repository"
    quote, extra = [], []
    for line in lines[1:]:
        if line.startswith(">"):
            quote.append(line[1:])
        elif line.strip() and not re.match(r"^(Affects|Effect):", line):
            extra.append(line)
    if extra:
        return "it holds more than the header, the quoted words, and the Affects and Effect lines"
    words = plain(" ".join(quote))
    if not words:
        return "it quotes nothing"
    msg = message(link, lm.group(1), lm.group(2), lm.group(3))
    if not msg:
        return "GitHub has no message at its link"
    if (msg.get("user") or "").lower() != user:
        return f"the message at its link was written by {msg.get('user') or 'someone else'}, not {m.group(2)}"
    if words not in plain(msg.get("body") or "") and words not in plain(msg.get("title") or ""):
        return "the quoted words aren't in the message at its link"
    return None


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    code, old_text, _ = run(["git", "show", f"{base}:amendments.md"])
    if code != 0:
        old_text = ""
    try:
        with open(FILE, encoding="utf-8") as f:
            now_text = f.read().replace("\r\n", "\n")
    except OSError:
        now_text = ""
    if now_text == old_text.replace("\r\n", "\n"):
        return
    old_head, old = split(old_text)
    now_head, now = split(now_text)
    notes, keep = [], []
    now_set = {e.rstrip() for e in now}
    for e in old:
        if e.rstrip() not in now_set:
            notes.append("restored amendment: " + e.split("\n", 1)[0])
        keep.append(e)
    old_set = {e.rstrip() for e in old}
    allowed, slug = allowlist(), company_repo()
    for e in now:
        if e.rstrip() in old_set:
            continue
        why = problem(e, allowed, slug)
        if why:
            notes.append(f"removed amendment: {e.split(chr(10), 1)[0]} ({why})")
        else:
            keep.append(e)
    head = old_head if old_text else now_head
    if plain(without_none_yet(now_head)) != plain(without_none_yet(head)):
        notes.append("restored the opening text of amendments.md")
    if keep:
        head = without_none_yet(head)
    elif NONE_YET not in head:
        head = head.rstrip("\n") + "\n\n" + NONE_YET + "\n"
    body = "".join(e if e.endswith("\n") else e + "\n" for e in keep)
    text = head.rstrip("\n") + "\n\n" + body if keep else head
    text = re.sub(r"\n{3,}", "\n\n", text)
    if notes:
        with open(FILE, "w", encoding="utf-8") as f:
            f.write(text)
        print("\n".join(notes))


if __name__ == "__main__":
    main()
