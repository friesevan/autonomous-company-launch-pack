#!/usr/bin/env python3
"""Print single Commandments, sections, or search results from CLAUDE.md.

Workers never load the full Commandments. This tool lets anyone read just the
rule they need, plus any amendment that changes it.

Usage:
  python3 rules/lookup.py 9            Commandment 9 in full
  python3 rules/lookup.py 9 25 48      several Commandments
  python3 rules/lookup.py t6           Tenet 6
  python3 rules/lookup.py "The Pitch"  an unnumbered section, by heading
  python3 rules/lookup.py --map        one line per Commandment, grouped by Part
  python3 rules/lookup.py --search art Commandments and Tenets mentioning a word
  python3 rules/lookup.py --amendments every amendment in effect

Investors own this file (Commandment 59 and the Operations Guide).
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAUDE_MD = os.path.join(ROOT, "CLAUDE.md")
AMENDMENTS_MD = os.path.join(ROOT, "amendments.md")

NUMBERED = re.compile(r"^\*\*(\d+)\.\s+(.+?)\*\*")
TENET = re.compile(r"^\*\*Tenet\s+(\d+):\s+(.+?)\*\*")
HEADING = re.compile(r"^(#{1,4})\s+(.*)$")


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().splitlines()
    except FileNotFoundError:
        return []


def blocks(lines):
    """Split the Commandments into numbered rules, tenets, and headed sections."""
    rules, tenets, sections, order = {}, {}, {}, []
    part, sub = "", ""
    for i, line in enumerate(lines):
        h = HEADING.match(line)
        n = NUMBERED.match(line)
        t = TENET.match(line)
        if h:
            level = len(h.group(1))
            title = h.group(2).strip()
            if level == 2:
                part, sub = title, ""
            elif level == 3:
                sub = title
            sections[title.lower()] = (level, i)
            continue
        if n:
            num = int(n.group(1))
            label = f"{part} / {sub}" if sub else part
            rules[num] = {"title": n.group(2).strip().rstrip("."), "start": i, "part": label}
            order.append(num)
            continue
        if t:
            num = int(t.group(1))
            tenets[num] = {"title": t.group(2).strip().rstrip("."), "start": i}
            continue
    return rules, tenets, sections, order


def rule_text(lines, start, stop_on_tenet=False):
    out = [lines[start]]
    for line in lines[start + 1:]:
        if HEADING.match(line) or NUMBERED.match(line):
            break
        if stop_on_tenet and TENET.match(line):
            break
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def section_text(lines, level, start):
    out = [lines[start]]
    for line in lines[start + 1:]:
        h = HEADING.match(line)
        if h and len(h.group(1)) <= level:
            break
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def amendments():
    """Return amendment entries as (header, body, affects) tuples."""
    lines = read(AMENDMENTS_MD)
    entries, cur = [], None
    in_code = False
    for line in lines:
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if line.startswith("## "):
            if cur:
                entries.append(cur)
            cur = [line, []]
        elif cur is not None:
            cur[1].append(line)
    if cur:
        entries.append(cur)
    result = []
    for header, body in entries:
        text = "\n".join(body).strip()
        m = re.search(r"^Affects:\s*(.+)$", text, re.M | re.I)
        affects = m.group(1).lower() if m else "all"
        result.append((header, text, affects))
    return result


def affecting(numbers):
    found = []
    for header, text, affects in amendments():
        nums = set(int(x) for x in re.findall(r"\d+", affects))
        if "all" in affects or nums & set(numbers):
            found.append((header, text))
    return found


def print_amendments_for(numbers):
    hits = affecting(numbers)
    total = len(amendments())
    if hits:
        print("\n--- Amendments in effect that change this (they override the text above) ---")
        for header, text in hits:
            print(header)
            print(text)
            print()
    elif total:
        print(f"\n(No amendment changes this. {total} amendment(s) in effect elsewhere: --amendments)")


def main(argv):
    lines = read(CLAUDE_MD)
    if not lines:
        print("CLAUDE.md not found next to rules/.", file=sys.stderr)
        return 2
    rules, tenets, sections, order = blocks(lines)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if argv[0] == "--map":
        part = None
        for num in order:
            r = rules[num]
            if r["part"] != part:
                part = r["part"]
                print(f"\n{part}")
            print(f"  {num:>2}. {r['title']}")
        print("\nTenets: " + "; ".join(f"T{n} {t['title']}" for n, t in sorted(tenets.items())))
        return 0
    if argv[0] == "--amendments":
        entries = amendments()
        if not entries:
            print("No amendments in effect.")
        for header, text, _ in entries:
            print(header)
            print(text)
            print()
        return 0
    if argv[0] == "--search":
        if len(argv) < 2:
            print("Usage: --search <word or phrase>", file=sys.stderr)
            return 2
        needle = " ".join(argv[1:]).lower()
        hits = 0
        for num in order:
            body = rule_text(lines, rules[num]["start"])
            if needle in body.lower():
                hits += 1
                print(f"{num:>2}. {rules[num]['title']}")
        for num, t in sorted(tenets.items()):
            body = rule_text(lines, t["start"], stop_on_tenet=True)
            if needle in body.lower():
                hits += 1
                print(f"T{num}. {t['title']}")
        if not hits:
            print(f"No Commandment or Tenet mentions '{needle}'.")
        return 0 if hits else 1
    status = 0
    printed = []
    for arg in argv:
        key = arg.strip().lower()
        if re.fullmatch(r"\d+", key):
            num = int(key)
            if num in rules:
                print(rule_text(lines, rules[num]["start"]))
                print()
                printed.append(num)
            else:
                print(f"No Commandment {num}. Try --map.", file=sys.stderr)
                status = 1
        elif re.fullmatch(r"t(enet)?\s*\d+", key):
            num = int(re.findall(r"\d+", key)[0])
            if num in tenets:
                print(rule_text(lines, tenets[num]["start"], stop_on_tenet=True))
                print()
            else:
                print(f"No Tenet {num}.", file=sys.stderr)
                status = 1
        else:
            match = None
            for title, (level, start) in sections.items():
                if key == title or key in title:
                    match = (level, start)
                    break
            if match:
                print(section_text(lines, *match))
                print()
            else:
                print(f"No section matching '{arg}'. Try --map or --search.", file=sys.stderr)
                status = 1
    if printed:
        print_amendments_for(printed)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
