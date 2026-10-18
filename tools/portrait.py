#!/usr/bin/env python3
"""Draw a worker's portrait from a mathematical expression, seeded by their name.

  python3 tools/portrait.py maya                           # still portrait to personnel/portraits/maya.svg
  python3 tools/portrait.py maya --temperament restless --mood 2 --out /tmp/maya.svg
  python3 tools/portrait.py --list-temperaments

The shape is a superformula silhouette (Gielis, 2003): r(t) = (|cos(m t/4)|^n2 + |sin(m t/4)|^n3)^(-1/n1),
with m, n1, n2, n3 and the palette drawn from a random generator seeded by the lowercase first
name, so the same name always gives the same portrait and no generative model is involved
(Commandment 9). A second, smaller layer gives depth.

Motion: the portrait "breathes" with SVG animation chosen by the worker's temperament, a word the
CEO picks from the persona and records in personnel/registry.json, so each character moves in
their own way. Mood (1 to 5, from the worker's latest diary) nudges the tempo: high mood slower and
fuller, low mood quicker and tighter. The animation stops for viewers who ask for reduced motion;
a still copy is always inside the file. Company-owned (Commandment 3); the portrait style, as a
style, needs creative approval once (Commandment 15).
"""
import argparse
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# temperament -> (kind, amplitude, base duration in seconds, description)
TEMPERAMENTS = {
    "calm": ("scale", 0.035, 11.0, "a slow, even breath"),
    "steady": ("drift", 2.2, 9.0, "a gentle rise and fall, like treading water"),
    "restless": ("wobble", 5.0, 5.0, "a small side-to-side rock that never quite settles"),
    "sharp": ("snap", 0.06, 4.0, "quick pulses with long stillness between them"),
    "dreamy": ("spin", 360.0, 26.0, "a slow continuous turn"),
    "driven": ("lean", 0.045, 7.0, "a breath with a forward lean on every beat"),
}
MOOD_TEMPO = {1: 0.6, 2: 0.8, 3: 1.0, 4: 1.15, 5: 1.3}      # multiplies the duration
MOOD_AMPLITUDE = {1: 0.7, 2: 0.85, 3: 1.0, 4: 1.1, 5: 1.2}  # multiplies the amplitude


def params(name):
    r = random.Random(name.strip().lower())
    return {
        "m": r.choice([3, 4, 5, 5, 6, 7, 8]),
        "n1": r.uniform(0.35, 2.2),
        "n2": r.uniform(0.5, 3.0),
        "n3": r.uniform(0.5, 3.0),
        "hue": r.randint(0, 359),
        "hue2": (r.randint(0, 359)),
        "rot": r.uniform(0, 360),
        "inner": r.uniform(0.45, 0.62),
        "light": r.choice([True, False]),
    }


def default_temperament(name):
    return random.Random("temperament:" + name.strip().lower()).choice(sorted(TEMPERAMENTS))


def outline(p, radius=38.0, n=240, phase=0.0):
    """Points of the superformula, centred on the origin, as an SVG points string."""
    pts = []
    m, n1, n2, n3 = p["m"], p["n1"], p["n2"], p["n3"]
    for i in range(n):
        t = 2 * math.pi * i / n + phase
        rr = (abs(math.cos(m * t / 4)) ** n2 + abs(math.sin(m * t / 4)) ** n3) ** (-1 / n1)
        pts.append(f"{radius * rr * math.cos(t):.2f},{radius * rr * math.sin(t):.2f}")
    return " ".join(pts)


def motion(temperament, mood):
    kind, amp, dur, _ = TEMPERAMENTS.get(temperament, TEMPERAMENTS["calm"])
    mood = mood if mood in MOOD_TEMPO else 3
    dur = dur * MOOD_TEMPO[mood]
    amp = amp * MOOD_AMPLITUDE[mood]
    d = f"{dur:.1f}s"
    if kind == "scale":
        return (f'<animateTransform attributeName="transform" type="scale" values="1;{1 + amp:.3f};1" '
                f'keyTimes="0;0.5;1" calcMode="spline" keySplines="0.42 0 0.58 1;0.42 0 0.58 1" dur="{d}" repeatCount="indefinite"/>')
    if kind == "drift":
        return (f'<animateTransform attributeName="transform" type="translate" values="0 0;0 {-amp:.2f};0 0" '
                f'keyTimes="0;0.5;1" calcMode="spline" keySplines="0.42 0 0.58 1;0.42 0 0.58 1" dur="{d}" repeatCount="indefinite"/>')
    if kind == "wobble":
        return (f'<animateTransform attributeName="transform" type="rotate" values="{-amp:.2f};{amp:.2f};{-amp:.2f}" '
                f'keyTimes="0;0.5;1" calcMode="spline" keySplines="0.45 0 0.55 1;0.45 0 0.55 1" dur="{d}" repeatCount="indefinite"/>')
    if kind == "snap":
        return (f'<animateTransform attributeName="transform" type="scale" values="1;{1 + amp:.3f};1;1" '
                f'keyTimes="0;0.12;0.3;1" calcMode="spline" keySplines="0.2 0 0.4 1;0.4 0 0.8 1;0 0 1 1" dur="{d}" repeatCount="indefinite"/>')
    if kind == "spin":
        return f'<animateTransform attributeName="transform" type="rotate" from="0" to="{amp:.0f}" dur="{d}" repeatCount="indefinite"/>'
    if kind == "lean":
        return (f'<animateTransform attributeName="transform" type="scale" values="1;{1 + amp:.3f};1" '
                f'keyTimes="0;0.5;1" calcMode="spline" keySplines="0.42 0 0.58 1;0.42 0 0.58 1" dur="{d}" repeatCount="indefinite"/>'
                f'<animateTransform attributeName="transform" type="skewX" values="0;-3;0" keyTimes="0;0.5;1" '
                f'calcMode="spline" keySplines="0.42 0 0.58 1;0.42 0 0.58 1" dur="{d}" repeatCount="indefinite" additive="sum"/>')
    return ""


def portrait_svg(name, temperament=None, mood=None, animated=True):
    p = params(name)
    temperament = temperament if temperament in TEMPERAMENTS else default_temperament(name)
    bg = f"hsl({p['hue']},45%,{93 if p['light'] else 16}%)"
    fill = f"hsl({p['hue']},58%,{46 if p['light'] else 62}%)"
    fill2 = f"hsl({p['hue2']},55%,{58 if p['light'] else 40}%)"
    outer = outline(p)
    inner = outline(p, radius=38.0 * p["inner"], phase=math.pi / p["m"])
    body = (f'<g transform="rotate({p["rot"]:.1f})"><polygon points="{outer}" fill="{fill}" opacity="0.92"/>'
            f'<polygon points="{inner}" fill="{fill2}" opacity="0.85"/></g>')
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img" aria-label="portrait of ' + name + '">']
    if animated:
        parts.append("<style>.motion{display:inline}.still{display:none}"
                     "@media (prefers-reduced-motion: reduce){.motion{display:none}.still{display:inline}}</style>")
    parts.append(f'<rect width="100" height="100" rx="14" fill="{bg}"/>')
    parts.append(f'<g transform="translate(50 50)"><g class="still">{body}</g>')
    if animated:
        parts.append(f'<g class="motion">{body}{motion(temperament, mood)}</g>')
    parts.append("</g></svg>")
    return "".join(parts) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?", help="the worker's first name")
    ap.add_argument("--temperament", choices=sorted(TEMPERAMENTS))
    ap.add_argument("--mood", type=int, choices=[1, 2, 3, 4, 5])
    ap.add_argument("--still", action="store_true", help="no animation")
    ap.add_argument("--out", help="output path (default personnel/portraits/<name>.svg)")
    ap.add_argument("--list-temperaments", action="store_true")
    args = ap.parse_args()
    if args.list_temperaments:
        for k, (_, _, dur, desc) in TEMPERAMENTS.items():
            print(f"{k:9s} {desc} (about {dur:.0f}s a cycle)")
        return
    if not args.name:
        ap.error("a name is required")
    svg = portrait_svg(args.name, args.temperament, args.mood, animated=not args.still)
    out = args.out or os.path.join(ROOT, "personnel", "portraits", f"{args.name.strip().lower()}.svg")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"{out} ({args.temperament or default_temperament(args.name)}, mood {args.mood or 'none'})")


if __name__ == "__main__":
    main()
