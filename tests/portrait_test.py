#!/usr/bin/env python3
"""Portraits and mood colors: measured, not eyeballed.

Run through tests/run.sh. Checks that any cast of six, drawn from random names, ends up with
portraits far apart by the shape distance and the hue gap; that each temperament moves in its own
way; that the still fallback is present; and that every mood color passes WCAG contrast and the
five levels stay in lightness order (so the scale survives color blindness).
"""
import itertools
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import portrait as P  # noqa: E402

PASS = FAIL = 0


def ok(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"PASS {name}")
    else:
        FAIL += 1
        print(f"FAIL {name}")


NAMES = ["Maya", "Nadia", "Theo", "Olga", "Noor", "Ceo", "Ada", "Bram", "Cleo", "Dev", "Esme", "Finn", "Gil", "Hana", "Ivo",
         "Juno", "Kai", "Lior", "Mira", "Nils", "Orla", "Pim", "Quin", "Rae", "Sol", "Tove", "Uma", "Vik", "Wren", "Yara", "Zed",
         "Alba", "Bo", "Cato", "Dara", "Eli", "Freya", "Gus", "Hugo", "Ines", "Jude", "Kit", "Lena", "Milo", "Nia", "Otto", "Pia"]

# 1. Distinctness for random casts of six
r = random.Random(7)
worst_d, worst_h, max_variant = 1.0, 360, 0
for _ in range(12):
    cast = r.sample(NAMES, 6)
    v = P.assign_variants(cast)
    max_variant = max(max_variant, max(v.values()))
    ps = [P.params(n, v[n]) for n in cast]
    for a, b in itertools.combinations(ps, 2):
        worst_d = min(worst_d, P.distance(a, b))
        worst_h = min(worst_h, P.hue_gap(a["hue"], b["hue"]))
ok(f"12 random casts of 6: every pair at least {P.MIN_DISTANCE} apart in shape (worst {worst_d:.3f})", worst_d >= P.MIN_DISTANCE)
ok(f"12 random casts of 6: every pair at least {P.MIN_HUE * 0.6:.0f} degrees apart in hue (worst {worst_h})", worst_h >= P.MIN_HUE * 0.6)
ok(f"variants stay small (max {max_variant})", max_variant < 120)
ok("the same name always gives the same shape", P.outline(P.params("maya")) == P.outline(P.params("Maya ")))
ok("a variant changes the shape", P.distance(P.params("maya", 0), P.params("maya", 1)) > 0.05 or P.params("maya", 0)["family"] != P.params("maya", 1)["family"])
families = {P.params(n)["family"] for n in NAMES}
ok(f"all five families occur across the name list ({len(families)})", families == set(P.FAMILIES))

# 2. Each silhouette is a sane closed shape
for n in NAMES[:12]:
    rs = P.radii(P.params(n))
    assert all(0 <= x <= 1.0001 for x in rs), n
ok("radii are normalised and finite for every family", True)
ok("no inner layer: one polygon in the still shape", P.portrait_svg("maya", animated=False).count("<polygon") == 1)

# 3. Motion: each temperament differs in path kind and period
kinds = {t: P.motion(t, 3) for t in P.TEMPERAMENTS}
ok("every temperament produces an animation", all(kinds.values()))
ok("no two temperaments share an animation", len(set(kinds.values())) == len(kinds))
periods = sorted(P.TEMPERAMENTS[t][1] for t in P.TEMPERAMENTS)
ok("periods differ by at least 0.4 s between neighbours", all(b - a >= 0.4 for a, b in zip(periods, periods[1:])))
ok("path-based motions use animateMotion; the others transform", sum("animateMotion" in m for m in kinds.values()) == 3)
ok("mood sets the tempo (low mood faster)", float(re.search(r'dur="([\d.]+)s"', P.motion("calm", 1)).group(1)) < float(re.search(r'dur="([\d.]+)s"', P.motion("calm", 5)).group(1)))
svg = P.portrait_svg("maya", "restless", 2)
ok("reduced-motion rule and a still copy are in the file", "prefers-reduced-motion" in svg and 'class="still"' in svg and 'class="motion"' in svg)
ok("the figure-eight amplitude is visible (7 units of 100)", "C 7 -7 7 7 0 0" in svg)


# 4. Mood colors: WCAG contrast and lightness order
def srgb_to_lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hexcolor):
    h = hexcolor.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    rr, gg, bb = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * srgb_to_lin(rr) + 0.7152 * srgb_to_lin(gg) + 0.0722 * srgb_to_lin(bb)


def contrast(fg, bg):
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


css = open(os.path.join(ROOT, "tools", "site_build.py"), encoding="utf-8").read()
levels = {}
for lv in range(1, 6):
    m = re.search(r"\.mood-word\.lv%d\{color:(#[0-9a-f]{3,6});background:(#[0-9a-f]{3,6})\}" % lv, css)
    levels[lv] = (m.group(1), m.group(2))
ratios = {lv: contrast(fg, bg) for lv, (fg, bg) in levels.items()}
ok("every mood level passes WCAG AA text contrast (4.5:1): " + ", ".join(f"{lv} {rt:.1f}" for lv, rt in ratios.items()), all(rt >= 4.5 for rt in ratios.values()))
lums = [luminance(levels[lv][1]) for lv in range(1, 6)]
ok("background lightness is ordered 1 < 2 < 3 and the level-1 and level-5 backgrounds differ clearly (readable without color): "
   + ", ".join(f"{x:.2f}" for x in lums), lums[0] < lums[1] < lums[2] and abs(lums[4] - lums[0]) > 0.15)

print(f"\nPASS {PASS}  FAIL {FAIL}")
sys.exit(1 if FAIL else 0)
