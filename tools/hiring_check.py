#!/usr/bin/env python3
"""Check that every hire went through a complete hiring round (Commandment 18).

  python3 tools/hiring_check.py                 # the live repository
  python3 tools/hiring_check.py --root <dir>    # another checkout or a test fixture
  python3 tools/hiring_check.py --round <id>    # one round only

The round's records (Operations Guide, section 5) are:

  personnel/registry.json            the hired worker and every candidate carry "round": "<id>";
                                     candidates not hired have "status": "candidate"
  story/hiring/<id>/brief.md         the role brief and scorecard, written before any candidate
  story/hiring/<id>/interview-<interviewer>-<candidate>.md
                                     one per interviewer per candidate, kind: interview,
                                     workers: <interviewer>, <candidate>; ends with a "## Scorecard"
                                     table of at least three scored competencies
  story/hiring/<id>/decision.md      the CEO's decision memo and the offer

For every active or former worker with a round, the check requires: the brief exists and
its first commit is older than any candidate's first commit (git history; skipped with a
note when a file isn't committed yet); at least two candidates in the round; one
interview with a scorecard for each candidate; a decision memo; and the hired worker's
registry career goal traceable to their interviews or the decision memo (most of its
words appear there). A worker without a round is allowed only for the CEO (role "CEO").

Prints one line per failure and exits 1; exits 0 when every round is complete.
No Claude, no dependencies. Company-owned; tests/run.sh checks it.
"""
import argparse
import json
import os
import re
import subprocess
import sys

WORD = re.compile(r"[a-z0-9']+")


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def front_matter(text):
    meta, body = {}, text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
            body = parts[2]
    return meta, body


def first_commit_time(root, relpath):
    """Unix time the file was first added, or None if git doesn't know it."""
    try:
        out = subprocess.run(["git", "log", "--diff-filter=A", "--follow", "--format=%ct", "--", relpath],
                             cwd=root, capture_output=True, text=True, check=False).stdout.split()
    except OSError:
        return None
    return min(int(t) for t in out) if out else None


def has_scorecard(body):
    """A '## Scorecard' heading followed by a table with at least three rows that carry a number."""
    m = re.search(r"^##\s+Scorecard\s*$", body, flags=re.M | re.I)
    if not m:
        return False
    rows = [l for l in body[m.end():].splitlines() if l.strip().startswith("|") and not re.match(r"^\|[\s\-:|]+\|$", l.strip())]
    scored = [r for r in rows if re.search(r"\|\s*\d+(\.\d+)?\s*(/\s*\d+)?\s*\|", r)]
    return len(scored) >= 3


def goal_traceable(goal, texts):
    words = [w for w in WORD.findall(goal.lower()) if len(w) >= 4]
    if not words:
        return True
    corpus = " ".join(texts).lower()
    found = sum(1 for w in words if w in corpus)
    return found >= max(1, round(0.6 * len(words)))


def check_round(root, rid, rows, failures):
    rdir = os.path.join(root, "story", "hiring", rid)
    rel = lambda *p: os.path.join("story", "hiring", rid, *p)
    fail = lambda msg: failures.append(f"{rid}: {msg}")
    if not os.path.isdir(rdir):
        fail(f"no round directory {rel()}")
        return
    brief = os.path.join(rdir, "brief.md")
    if not os.path.exists(brief):
        fail("no brief.md (the role brief and scorecard)")
    decision = os.path.join(rdir, "decision.md")
    if not os.path.exists(decision):
        fail("no decision.md (the CEO's decision memo)")
    candidates = [r for r in rows if r.get("round") == rid]
    if len(candidates) < 2:
        fail(f"only {len(candidates)} candidate(s) in the registry; a round needs at least two")
    hired = [r for r in candidates if r.get("status", "active") != "candidate"]
    if len(hired) != 1:
        fail(f"{len(hired)} worker(s) hired from this round; expected exactly one")

    interviews = {}
    for name in sorted(os.listdir(rdir)):
        if not name.startswith("interview-") or not name.endswith(".md"):
            continue
        meta, body = front_matter(read(os.path.join(rdir, name)))
        if meta.get("kind", "").lower() != "interview":
            fail(f"{name}: kind is {meta.get('kind') or 'missing'}, expected interview")
        workers = [slugify(w) for w in re.split(r"[,\s]+", meta.get("workers", "")) if w.strip()]
        if len(workers) < 2:
            fail(f"{name}: workers must list the interviewer and the candidate")
        if not has_scorecard(body):
            fail(f"{name}: no '## Scorecard' table with at least three scored competencies")
        for w in workers:
            interviews.setdefault(w, []).append((name, body))

    brief_time = first_commit_time(root, rel("brief.md")) if os.path.exists(brief) else None
    for c in candidates:
        slug = slugify(c.get("name", ""))
        if slug not in interviews:
            fail(f"{c.get('name')}: no interview record names them in workers")
        for folder in ("candidates", "agents", os.path.join("agents", "former")):
            dossier = os.path.join("personnel", folder, f"{slug}.md")
            if os.path.exists(os.path.join(root, dossier)):
                t = first_commit_time(root, dossier)
                if brief_time is None or t is None:
                    print(f"note: {rid}: {dossier} or the brief is not committed yet; order not checked")
                elif t < brief_time:
                    fail(f"{dossier} was committed before brief.md; the scorecard must come first")
                break
        else:
            fail(f"{c.get('name')}: no dossier in personnel/candidates/ or personnel/agents/")

    for h in hired:
        goal = str(h.get("career_goal") or "").strip()
        if not goal:
            fail(f"{h.get('name')}: no career_goal in the registry")
            continue
        texts = [b for _, b in interviews.get(slugify(h["name"]), [])]
        if os.path.exists(decision):
            texts.append(read(decision))
        if not goal_traceable(goal, texts):
            fail(f"{h.get('name')}: career goal is not traceable to their interviews or the decision memo")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    p.add_argument("--round", help="check one round id only")
    args = p.parse_args(argv)
    root = os.path.abspath(args.root)
    reg = os.path.join(root, "personnel", "registry.json")
    if not os.path.exists(reg):
        print("No personnel/registry.json; nothing to check.")
        return 0
    data = json.loads(read(reg))
    rows = [r for r in (data.get("workers", data) if isinstance(data, dict) else data) if isinstance(r, dict) and r.get("name")]
    failures = []
    for r in rows:
        if r.get("status", "active") == "candidate" or r.get("round"):
            continue
        if str(r.get("role", "")).strip().lower() != "ceo":
            failures.append(f"{r['name']}: active or former worker with no hiring round (only the CEO is hired without one)")
    rounds = sorted({r["round"] for r in rows if r.get("round")})
    if args.round:
        rounds = [args.round]
    for rid in rounds:
        check_round(root, rid, rows, failures)
    for f in failures:
        print("FAIL " + f)
    if failures:
        return 1
    print(f"OK: {len(rounds)} hiring round(s) complete, {len(rows)} registry row(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
