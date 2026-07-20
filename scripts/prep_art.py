#!/usr/bin/env python3
"""Turn an AI-generated "pixel art style" image into ACTUAL pixel art at spec.

Image models hand you a large, smooth image that merely LOOKS like pixel art:
soft edges, thousands of colours, anti-aliased everything. Dropped straight onto
the stage it reads as a blurry photo of pixel art. This does the conversion, and
then verifies it rather than trusting it.

    python scripts/prep_art.py IN.png OUT.png --size 270x480 --colors 24
    python scripts/prep_art.py IN.png OUT.png --size 72x90 --colors 20 --key-corners

WHY BOX-AVERAGE AND NOT NEAREST-NEIGHBOUR.
The obvious move is NEAREST, since "nearest = crisp". It is wrong here: NEAREST
throws away 99% of the source pixels and keeps one arbitrary sample per output
pixel, so thin features (a window, an eye highlight) either vanish or alias into
noise depending on where the grid happens to land. BOX averages the whole source
cell, which preserves structure — and the QUANTIZE step after it is what makes
the result hard-edged. Anti-aliasing is not "soft-looking pixels", it is
BLENDED EDGE pixels; once every pixel is snapped to a small palette there are no
blend values left, so the output is genuinely aliased. Averaging first gives a
better image AND still satisfies the constraint.

VERIFICATION is the point of the tool. It asserts exact dimensions, the colour
cap, and ZERO semi-alpha pixels — that last one is the tell that anti-aliasing
survived, and it is invisible until the sprite is on air with fringed edges.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from PIL import Image


def parse_size(s: str) -> tuple[int, int]:
    w, h = s.lower().split("x")
    return int(w), int(h)


def key_out_corners(img: Image.Image, tol: int = 26) -> Image.Image:
    """Make the flat background transparent by sampling the four corners.

    Only removes a colour that ALL FOUR corners agree on — a portrait on a flat
    field has one, a scene does not, and guessing wrong would punch holes in the
    art itself.
    """
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    r0, g0, b0 = corners[0][:3]
    for c in corners[1:]:
        if abs(c[0] - r0) + abs(c[1] - g0) + abs(c[2] - b0) > tol:
            print("  key: corners disagree — leaving background opaque")
            return img
    out = Image.new("RGBA", (w, h))
    op = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            op[x, y] = (0, 0, 0, 0) if abs(r - r0) + abs(g - g0) + abs(b - b0) <= tol \
                else (r, g, b, 255)
    print(f"  key: removed background rgb({r0},{g0},{b0})")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--size", required=True, help="WxH, e.g. 270x480")
    ap.add_argument("--colors", type=int, default=24)
    ap.add_argument("--crop", help="LEFT,TOP,RIGHT,BOTTOM in source pixels")
    ap.add_argument("--key-corners", action="store_true",
                    help="make a flat corner-matched background transparent")
    a = ap.parse_args()

    W, H = parse_size(a.size)
    img = Image.open(a.src)
    print(f"source  {img.size[0]}x{img.size[1]} {img.mode}")

    if a.crop:
        box = tuple(int(v) for v in a.crop.split(","))
        img = img.crop(box)
        print(f"crop    -> {img.size[0]}x{img.size[1]}")

    if a.key_corners:
        img = key_out_corners(img)
    img = img.convert("RGBA")

    # 1. BOX average down to target. Preserves structure; see the note above.
    img = img.resize((W, H), Image.BOX)

    # 2. Quantize. This is what makes it hard-edged — every pixel becomes one of
    #    N palette entries, so no blended edge values remain.
    alpha = img.getchannel("A")
    rgb = img.convert("RGB").quantize(colors=a.colors, method=Image.MEDIANCUT,
                                      dither=Image.NONE).convert("RGB")
    out = rgb.convert("RGBA")
    # 3. Alpha is binarised: a semi-transparent pixel IS an anti-aliased pixel.
    out.putalpha(alpha.point(lambda v: 255 if v >= 128 else 0))
    out.save(a.dst)

    # ── verify, do not trust ────────────────────────────────────────────────
    data = list(out.getdata())
    cols = {p[:3] for p in data if p[3] > 0}
    semi = sum(1 for p in data if 0 < p[3] < 255)
    ok = out.size == (W, H) and semi == 0 and len(cols) <= a.colors
    print(f"output  {out.size[0]}x{out.size[1]}  colours={len(cols)}  semi-alpha={semi}")
    top = Counter(p[:3] for p in data if p[3] > 0).most_common(6)
    print("  dominant: " + "  ".join("#%02x%02x%02x" % c for c, _ in top))
    print("  " + ("PASS — real pixel art at spec" if ok else "FAIL — check above"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
