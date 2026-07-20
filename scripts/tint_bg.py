#!/usr/bin/env python3
"""Re-tint the RetroNews backdrop into the shell's warm greys.

    python scripts/tint_bg.py dashboard/retronews_bg.png [--write]

WHY THIS EXISTS
The city was generated for the original blue/purple palette and measured ~95%
blue/purple. Behind a warm-charcoal stage it is the loudest thing on screen and
the only one nobody asked for — and it shows through a LOT: the safe box is 51%
of the canvas, so nearly half of what a viewer sees is backdrop.

WHAT MAKES A BACKDROP RECEDE — and it is not simply "darker".
It is LOW CONTRAST plus LOW SATURATION. The panels win attention through hard
bevels and high-contrast type, so a backdrop with a NARROW tonal range sits
behind them even at a similar mean brightness. Crushing the city to near-black
would also work, but half the frame would then be an empty rectangle.

So: map luminance into a narrow warm band whose top stays BELOW --lit (the panel
bevel highlight). Nothing in the backdrop is ever as bright as the edge
of a panel, which is what keeps the panels reading as objects on top of it.

Window lights and water reflections are found by WARMTH, not brightness. They
are warm (r > b) against a cool purple sky, whereas a luminance threshold picks
the brightest thing in frame — which here is a flat region of sky, so the first
version selected nothing and flattened every light into grey. Those lights are
most of what makes the art work, and they are allowed to stay warm.

A handful of point lights brighter than a panel edge is CORRECT — that is how
night-city art reads depth — so the check is that under 1% of pixels exceed
--lit, not that none do.

Pixel-art constraints are preserved and then VERIFIED, exactly as prep_art.py
does: exact dimensions, a small palette, and ZERO semi-alpha pixels.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from PIL import Image

# Derived from retronews.css :root so the backdrop cannot drift from the shell.
# Track the shell. These are not free constants — the ceiling MUST stay below
# --lit or the backdrop stops receding, and the floor sits just above --shade so
# the darkest part of the city is not blacker than a panel outline.
SHELL_FLOOR = (0x24, 0x1c, 0x12)     # just above --shade #201810
SHELL_CEIL  = (0x5e, 0x4d, 0x36)     # deliberately BELOW --lit #9b8158
GLOW        = (0xc8, 0xa0, 0x58)     # amber for window lights and reflections
GLOW_WARMTH = 18                     # r-b in the SOURCE that marks a light
COLORS      = 16


def lum(p) -> float:
    return (0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]) / 255.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--write", action="store_true",
                    help="overwrite src (otherwise writes <src>.tinted.png)")
    ap.add_argument("--colors", type=int, default=COLORS)
    a = ap.parse_args()

    img = Image.open(a.src).convert("RGBA")
    w, h = img.size
    px = img.load()
    print(f"source  {w}x{h}")

    before = Counter(p[:3] for p in img.getdata() if p[3])
    sat_before = sum(
        ((max(c) - min(c)) / max(1, max(c))) * n for c, n in before.items()
    ) / max(1, sum(before.values()))

    # Normalise over the image's ACTUAL range, not 0..1 — the source may not use
    # the full scale, and stretching first is what keeps the city legible after
    # it is squeezed into a narrow band.
    ls = [lum(px[x, y]) for y in range(h) for x in range(w) if px[x, y][3]]
    lo, hi = min(ls), max(ls)
    span = max(1e-6, hi - lo)
    warm = sum(1 for y in range(h) for x in range(w)
               if px[x, y][3] and px[x, y][0] - px[x, y][2] >= GLOW_WARMTH)
    print(f"luminance range {lo:.3f}..{hi:.3f}   warm pixels {warm} "
          f"({100.0 * warm / (w * h):.1f}%)")

    out = Image.new("RGBA", (w, h))
    op = out.load()
    for y in range(h):
        for x in range(w):
            p = px[x, y]
            if not p[3]:
                op[x, y] = (0, 0, 0, 0)
                continue
            t = (lum(p) - lo) / span
            base = [SHELL_FLOOR[i] + (SHELL_CEIL[i] - SHELL_FLOOR[i]) * t
                    for i in range(3)]
            warmth = p[0] - p[2]
            if warmth >= GLOW_WARMTH:
                # Scale toward amber by HOW warm it is, so a faint cloud edge
                # stays nearly grey while a lit window goes full amber.
                k = min(1.0, (warmth - GLOW_WARMTH) / 60.0) * (0.35 + 0.65 * t)
                rgb = tuple(int(base[i] + (GLOW[i] - base[i]) * k) for i in range(3))
            else:
                rgb = tuple(int(v) for v in base)
            op[x, y] = rgb + (255,)

    # Quantise — this is what keeps it hard-edged pixel art rather than a smooth
    # ramp, and it is the same reason prep_art.py quantises after resizing.
    alpha = out.getchannel("A")
    rgbq = out.convert("RGB").quantize(colors=a.colors, method=Image.MEDIANCUT,
                                       dither=Image.NONE).convert("RGB")
    out = rgbq.convert("RGBA")
    out.putalpha(alpha.point(lambda v: 255 if v >= 128 else 0))

    dst = a.src if a.write else a.src.replace(".png", ".tinted.png")
    out.save(dst)

    data = list(out.getdata())
    after = Counter(p[:3] for p in data if p[3])
    sat_after = sum(((max(c) - min(c)) / max(1, max(c))) * n
                    for c, n in after.items()) / max(1, sum(after.values()))
    semi = sum(1 for p in data if 0 < p[3] < 255)
    lit_lum = lum((0x9b, 0x81, 0x58, 255))   # --lit
    brightest = max(lum(c + (255,)) for c in after)
    over = sum(n for c, n in after.items() if lum(c + (255,)) > lit_lum)
    over_pct = 100.0 * over / max(1, sum(after.values()))
    ok = out.size == (w, h) and semi == 0 and len(after) <= a.colors \
        and over_pct < 1.0

    print(f"output  {dst}")
    print(f"  colours   {len(before)} -> {len(after)}")
    print(f"  mean sat  {sat_before:.3f} -> {sat_after:.3f}")
    print(f"  brightest {brightest:.3f}  vs --lit {lit_lum:.3f}")
    print(f"  above --lit {over_pct:.2f}% of pixels  "
          f"({'point lights only, recedes' if over_pct < 1.0 else 'TOO MUCH — competes'})")
    print(f"  semi-alpha {semi}")
    print("  " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
