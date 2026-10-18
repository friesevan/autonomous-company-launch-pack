#!/usr/bin/env python3
"""Draw a worker's portrait from a mathematical curve, seeded by their name.

  python3 tools/portrait.py maya                              # still portrait to personnel/portraits/maya.svg
  python3 tools/portrait.py maya --temperament restless --mood 2 --out /tmp/maya.svg
  python3 tools/portrait.py --list-temperaments
  python3 tools/portrait.py --distance maya theo               # how different two portraits are (0 to 1)

The silhouette is one closed curve from one of five families, chosen and parameterised by a
random generator seeded with the lowercase first name, so the same name always gives the same
portrait and no generative model is involved (Commandment 9):

  superformula   r = (|cos(mt/4)|^n2 + |sin(mt/4)|^n3)^(-1/n1)          Gielis, 2003
  rose           r = 1 + a cos(k t)                                      rhodonea, with a soft core
  epitrochoid    the path of a point on a circle rolling outside another
  hypotrochoid   the same, rolling inside (spirograph curves)
  lissajous      x = sin(a t + d), y = sin(b t), a smoothed closed figure

Distinctness is measured, not hoped for: `distance(a, b)` compares two silhouettes by the
correlation of their radius functions at the best rotation (0 = identical, 1 = unrelated), and
`assign_variants(names)` walks a cast in order and re-seeds any portrait that comes within
MIN_DISTANCE of an earlier one or within MIN_HUE degrees of its hue, so a cast of six is always
far apart. The variant index is deterministic for a given cast order; the site records it.

Motion: the portrait moves by SVG animation chosen by the worker's temperament (a word the CEO
picks from the persona and records in personnel/registry.json), each a different path, period
and amplitude, so no two temperaments move alike. Mood (1 to 5, from the latest diary) sets
the tempo. The animation stops for viewers who ask for reduced motion; the still shape is always
inside the file. Company-owned (Commandment 3); the style is approved once (Commandment 15).
"""
import argparse
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAMILIES = ("superformula", "rose", "epitrochoid", "hypotrochoid", "lissajous")
MIN_DISTANCE = 0.22   # rotation-invariant shape distance below which two portraits read as alike
MIN_HUE = 36          # degrees of hue separation within a cast
SAMPLES = 180

# temperament -> (path kind, period in seconds, description). Each class differs in path shape,
# period, and amplitude, so the motions are told apart at a glance.
TEMPERAMENTS = {
    "calm": ("breathe", 7.0, "a slow, deep breath: swells and settles, nothing else moves"),
    "steady": ("bob", 5.0, "rises and sinks on a straight line, like treading water"),
    "restless": ("figure8", 3.6, "traces a figure of eight and rocks from side to side, never still"),
    "sharp": ("snap", 3.0, "quick snaps between long holds"),
    "dreamy": ("orbit", 14.0, "a slow turn while drifting in a circle"),
    "driven": ("lunge", 4.2, "leans forward and pushes, over and over"),
}
MOOD_TEMPO = {1: 0.65, 2: 0.82, 3: 1.0, 4: 1.15, 5: 1.3}      # multiplies the period


# ---------- the curve ----------

def params(name, variant=0):
    """Deterministic family and parameters for a name (and a variant salt)."""
    seed = name.strip().lower() + (f"#{variant}" if variant else "")
    r = random.Random(seed)
    family = FAMILIES[r.randrange(len(FAMILIES))]
    p = {"family": family, "hue": r.randint(0, 359), "rot": r.uniform(0, 360),
         "light": r.random() < 0.55, "sat": r.randint(48, 70)}
    if family == "superformula":
        p.update(m=r.choice([3, 4, 5, 6, 7, 8, 9]), n1=r.uniform(0.25, 1.6), n2=r.uniform(0.4, 3.5), n3=r.uniform(0.4, 3.5))
    elif family == "rose":
        p.update(k=r.choice([2, 3, 4, 5, 6, 7]), a=r.uniform(0.35, 0.75), soft=r.uniform(1.2, 2.6))
    elif family == "epitrochoid":
        p.update(k=r.choice([3, 4, 5, 6, 7, 8]), d=r.uniform(0.35, 0.95))
    elif family == "hypotrochoid":
        p.update(k=r.choice([3, 4, 5, 6, 7]), d=r.uniform(0.3, 0.9))
    else:
        p.update(a=r.choice([1, 2, 3]), b=r.choice([2, 3, 4]), d=r.uniform(0.3, 1.4), fat=r.uniform(0.25, 0.5))
    return p


def _xy(p, t):
    f = p["family"]
    if f == "superformula":
        rr = (abs(math.cos(p["m"] * t / 4)) ** p["n2"] + abs(math.sin(p["m"] * t / 4)) ** p["n3"]) ** (-1 / p["n1"])
        return rr * math.cos(t), rr * math.sin(t)
    if f == "rose":
        rr = 1 + p["a"] * (abs(math.cos(p["k"] * t / 2)) ** p["soft"]) * 2 - p["a"]
        return rr * math.cos(t), rr * math.sin(t)
    if f == "epitrochoid":
        k, d = p["k"], p["d"]
        return (k + 1) * math.cos(t) - d * math.cos((k + 1) * t), (k + 1) * math.sin(t) - d * math.sin((k + 1) * t)
    if f == "hypotrochoid":
        k, d = p["k"], p["d"]
        return (k - 1) * math.cos(t) + d * math.cos((k - 1) * t), (k - 1) * math.sin(t) - d * math.sin((k - 1) * t)
    a, b, d = p["a"], p["b"], p["d"]
    return math.sin(a * t + d), math.sin(b * t)


def radii(p, n=SAMPLES):
    """The silhouette as a radius function of angle, normalised, from a thickened outline.

    Epitrochoids, hypotrochoids and Lissajous figures are thin curves, so their silhouette is the
    curve swept by a disc: for each angle we take the farthest point of the curve near that angle.
    """
    pts = [_xy(p, 2 * math.pi * i / 1440) for i in range(1440)]
    if p["family"] in ("superformula", "rose"):
        rs = [math.hypot(x, y) for x, y in pts[::1440 // n]]
    else:
        fat = p.get("fat", 0.32) if p["family"] == "lissajous" else 0.22
        bins = [0.0] * n
        for x, y in pts:
            ang = math.atan2(y, x) % (2 * math.pi)
            rad = math.hypot(x, y)
            lo = int((ang - fat) / (2 * math.pi) * n)
            hi = int((ang + fat) / (2 * math.pi) * n)
            for j in range(lo, hi + 1):
                bins[j % n] = max(bins[j % n], rad)
        rs = bins
    m = max(rs) or 1.0
    return [r / m for r in rs]


def outline(p, radius=40.0):
    """Points of the silhouette centred on the origin, as an SVG points string, smoothed."""
    rs = radii(p)
    n = len(rs)
    sm = [(rs[i - 1] + rs[i] + rs[(i + 1) % n]) / 3 for i in range(n)]
    pts = []
    for i, rr in enumerate(sm):
        t = 2 * math.pi * i / n
        pts.append(f"{radius * rr * math.cos(t):.2f},{radius * rr * math.sin(t):.2f}")
    return " ".join(pts)


_RADII = {}


def cached_radii(p, n=SAMPLES):
    key = (n, tuple(sorted((k, round(v, 6) if isinstance(v, float) else v) for k, v in p.items())))
    if key not in _RADII:
        _RADII[key] = radii(p, n)
    return _RADII[key]


def distance(a, b, n=SAMPLES):
    """Rotation-invariant shape distance between two parameter sets (or names): 0 same, 1 unrelated."""
    pa = params(a) if isinstance(a, str) else a
    pb = params(b) if isinstance(b, str) else b
    ra, rb = cached_radii(pa, n), cached_radii(pb, n)
    ma, mb = sum(ra) / n, sum(rb) / n
    da, db = [r - ma for r in ra], [r - mb for r in rb]
    na, nb = math.sqrt(sum(x * x for x in da)) or 1e-9, math.sqrt(sum(x * x for x in db)) or 1e-9
    best = -1.0
    for shift in range(0, n, 2):
        c = sum(da[i] * db[(i + shift) % n] for i in range(n)) / (na * nb)
        best = max(best, c)
    d = (1 - best) / 2
    if pa["family"] != pb["family"]:
        d = min(1.0, d + 0.15)
    return d


def hue_gap(h1, h2):
    d = abs(h1 - h2) % 360
    return min(d, 360 - d)


def assign_variants(names, min_distance=MIN_DISTANCE, min_hue=MIN_HUE):
    """Variant index per name so every portrait in the cast is distinct from the ones before it."""
    chosen = {}
    taken = []
    for name in names:
        variant = 0
        while variant < 120:
            p = params(name, variant)
            hue_ok = min_hue if variant < 40 else min_hue * 0.6   # a crowded cast relaxes the hue spacing before the shape
            if all(hue_gap(p["hue"], q["hue"]) >= hue_ok for q in taken) and all(distance(p, q) >= min_distance for q in taken):
                break
            variant += 1
        chosen[name] = variant
        taken.append(params(name, variant))
    return chosen


# ---------- motion ----------

def motion(temperament, mood):
    kind, period, _ = TEMPERAMENTS.get(temperament, TEMPERAMENTS["calm"])
    mood = mood if mood in MOOD_TEMPO else 3
    d = f"{period * MOOD_TEMPO[mood]:.2f}s"
    ease = 'calcMode="spline" keySplines="0.42 0 0.58 1;0.42 0 0.58 1"'
    if kind == "breathe":
        return (f'<animateTransform attributeName="transform" type="scale" values="1;1.11;1" keyTimes="0;0.5;1" {ease} '
                f'dur="{d}" repeatCount="indefinite"/>')
    if kind == "bob":
        return (f'<animateMotion path="M 0 6 L 0 -6 L 0 6" keyPoints="0;0.5;1" keyTimes="0;0.5;1" {ease} dur="{d}" repeatCount="indefinite"/>'
                f'<animateTransform attributeName="transform" type="scale" values="1 0.97;1 1.03;1 0.97" keyTimes="0;0.5;1" {ease} '
                f'dur="{d}" repeatCount="indefinite" additive="sum"/>')
    if kind == "figure8":
        return (f'<animateMotion path="M 0 0 C 7 -7 7 7 0 0 C -7 -7 -7 7 0 0" dur="{d}" repeatCount="indefinite"/>'
                f'<animateTransform attributeName="transform" type="rotate" values="-8;8;-8" keyTimes="0;0.5;1" {ease} '
                f'dur="{d}" repeatCount="indefinite" additive="sum"/>')
    if kind == "snap":
        return (f'<animateTransform attributeName="transform" type="scale" values="1;1.14;0.98;1;1" keyTimes="0;0.08;0.18;0.3;1" '
                f'calcMode="spline" keySplines="0.1 0 0.3 1;0.4 0 0.8 1;0.4 0 0.6 1;0 0 1 1" dur="{d}" repeatCount="indefinite"/>')
    if kind == "orbit":
        return (f'<animateMotion path="M 0 -5 A 5 5 0 1 1 0 5 A 5 5 0 1 1 0 -5" dur="{d}" repeatCount="indefinite"/>'
                f'<animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="{d}" repeatCount="indefinite" additive="sum"/>')
    if kind == "lunge":
        return (f'<animateTransform attributeName="transform" type="skewX" values="0;-9;0;2;0" keyTimes="0;0.3;0.55;0.75;1" '
                f'calcMode="spline" keySplines="0.3 0 0.2 1;0.4 0 0.6 1;0.4 0 0.6 1;0.4 0 0.6 1" dur="{d}" repeatCount="indefinite"/>'
                f'<animateTransform attributeName="transform" type="scale" values="1;1.07;1;1" keyTimes="0;0.3;0.55;1" {ease} '
                f'dur="{d}" repeatCount="indefinite" additive="sum"/>')
    return ""


def default_temperament(name):
    return random.Random("temperament:" + name.strip().lower()).choice(sorted(TEMPERAMENTS))


def portrait_svg(name, temperament=None, mood=None, animated=True, variant=0):
    p = params(name, variant)
    temperament = temperament if temperament in TEMPERAMENTS else default_temperament(name)
    bg = f"hsl({p['hue']},40%,{94 if p['light'] else 15}%)"
    fill = f"hsl({p['hue']},{p['sat']}%,{44 if p['light'] else 64}%)"
    shape = f'<polygon points="{outline(p)}" fill="{fill}" transform="rotate({p["rot"]:.1f})"/>'
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img" aria-label="portrait of {name}">']
    if animated:
        parts.append("<style>.motion{display:inline}.still{display:none}"
                     "@media (prefers-reduced-motion: reduce){.motion{display:none}.still{display:inline}}</style>")
    parts.append(f'<rect width="100" height="100" rx="14" fill="{bg}"/>')
    parts.append(f'<g transform="translate(50 50)"><g class="still">{shape}</g>')
    if animated:
        parts.append(f'<g class="motion"><g>{shape}{motion(temperament, mood)}</g></g>')
    parts.append("</g></svg>")
    return "".join(parts) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="*", help="the worker's first name (two names with --distance)")
    ap.add_argument("--temperament", choices=sorted(TEMPERAMENTS))
    ap.add_argument("--mood", type=int, choices=[1, 2, 3, 4, 5])
    ap.add_argument("--variant", type=int, default=0)
    ap.add_argument("--still", action="store_true", help="no animation")
    ap.add_argument("--out", help="output path (default personnel/portraits/<name>.svg)")
    ap.add_argument("--list-temperaments", action="store_true")
    ap.add_argument("--distance", action="store_true", help="print the shape distance between two names")
    args = ap.parse_args()
    if args.list_temperaments:
        for k, (_, period, desc) in TEMPERAMENTS.items():
            print(f"{k:9s} {desc} (about {period:.0f}s a cycle)")
        return
    if args.distance:
        if len(args.name) != 2:
            ap.error("--distance needs two names")
        print(f"{distance(args.name[0], args.name[1]):.3f}  ({params(args.name[0])['family']} vs {params(args.name[1])['family']})")
        return
    if len(args.name) != 1:
        ap.error("one name is required")
    name = args.name[0]
    svg = portrait_svg(name, args.temperament, args.mood, animated=not args.still, variant=args.variant)
    out = args.out or os.path.join(ROOT, "personnel", "portraits", f"{name.strip().lower()}.svg")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(svg)
    p = params(name, args.variant)
    print(f"{out} ({p['family']}, {args.temperament or default_temperament(name)}, mood {args.mood or 'none'})")


if __name__ == "__main__":
    main()
