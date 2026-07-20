#!/usr/bin/env python3
"""Build the RetroNews host sheet from ONE prepared 72x90 portrait.

The base art is the approved concept, downscaled to spec by prep_art.py. This
DERIVES the other cells from it rather than regenerating anything, which is the
only way registration survives: the skull, hair, headset and shirt are byte-
identical in every cell because they are literally the same pixels. Regenerate
per expression and a 1px drift becomes a visible 3px twitch at device scale
every time his mood changes.

    python scripts/build_host_sheet.py base.png dashboard/retronews_host.png

Sheet: 3 lid columns x 6 mood rows of 72x90 = 216x540, indexed by retronews.js
as column = eyelid, row = mood.

WHAT IS AND IS NOT DERIVED
The BLINK is derived honestly — the eye band is found by scanning for the row
with the most near-white sclera pixels, then lids are closed by pulling skin
down over it and stamping a lash line. That is real animation.
Mood rows currently reuse the neutral face: the sheet is structurally complete
and the mood system works, but only NEUTRAL is truly drawn. Hand-editing eyes
and mouth on the base is what fills the rest in, and it must be done ON THE BASE
so registration is preserved.
"""
from __future__ import annotations

import sys
from collections import Counter
from PIL import Image

W, H = 72, 90
MOODS = 6
LIDS = 3


def dominant_skin(img: Image.Image) -> tuple[int, int, int, int]:
    """Cheek colour: the most common warm tone in the middle third."""
    px = img.load()
    c = Counter()
    for y in range(int(H * 0.35), int(H * 0.62)):
        for x in range(int(W * 0.2), int(W * 0.8)):
            r, g, b, a = px[x, y]
            if a and r > 150 and g > 100 and b < 190 and r > b:
                c[(r, g, b, 255)] += 1
    return c.most_common(1)[0][0] if c else (240, 175, 110, 255)


def find_eye_band(img: Image.Image) -> tuple[int, int, int, int]:
    """Row range + x extent of the eyes, found by counting sclera-bright pixels
    in the upper-middle of the face rather than by hardcoding coordinates —
    hardcoding breaks the moment the art is re-cropped."""
    px = img.load()
    rows = []
    for y in range(int(H * 0.28), int(H * 0.60)):
        n = 0; xs = []
        for x in range(W):
            r, g, b, a = px[x, y]
            if a and r > 205 and g > 205 and b > 195:
                n += 1; xs.append(x)
        rows.append((n, y, xs))
    rows.sort(reverse=True)
    best = rows[0]
    ys = sorted(y for n, y, _ in rows[:5] if n >= max(2, best[0] // 3))
    x0 = min(best[2]) if best[2] else int(W * 0.25)
    x1 = max(best[2]) if best[2] else int(W * 0.75)
    return min(ys), max(ys), x0, x1


def eye_mask(base: Image.Image, y0: int, y1: int, x0: int, x1: int):
    """Per-COLUMN vertical extent of actual eye pixels.

    The first version filled the whole eye BOUNDING BOX, which swallowed the
    bridge of the nose between the eyes and rendered the blink as a band across
    his face. Working per column means the gap between the eyes has no eye
    pixels in it and is simply skipped — the two lids close independently,
    which is also what real eyelids do.
    """
    px = base.load()
    cols = {}
    for x in range(x0, x1 + 1):
        ys = []
        for y in range(y0 - 2, y1 + 3):
            if not (0 <= y < H):
                continue
            r, g, b, a = px[x, y]
            if not a:
                continue
            bright = r > 205 and g > 205 and b > 195          # sclera
            dark = r < 90 and g < 90 and b < 120              # pupil / lash
            if bright or dark:
                ys.append(y)
        if len(ys) >= 2:
            # Dilate 1px. The eye KEYLINE sits just outside the sclera/pupil the
            # scan detects, so without this a shut lid leaves an outline ring
            # behind and reads as "eyes with rings" rather than closed.
            cols[x] = (max(0, min(ys) - 1), min(H - 1, max(ys) + 1))
    return cols


def close_eyes(base: Image.Image, amount: float, skin, lash) -> Image.Image:
    """amount 0 = open, ~0.55 = half, 1 = shut. Closes each eye per column."""
    img = base.copy()
    if amount <= 0:
        return img
    y0, y1, x0, x1 = find_eye_band(base)
    cols = eye_mask(base, y0, y1, x0, x1)
    px = img.load()
    for x, (ey0, ey1) in cols.items():
        h = ey1 - ey0 + 1
        cover = max(1, int(round(h * amount)))
        for y in range(ey0, ey0 + cover):
            px[x, y] = skin
        px[x, min(ey0 + cover - 1, ey1)] = lash      # lash line rides the lid edge
    return img


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__); return 2
    base = Image.open(sys.argv[1]).convert("RGBA")
    if base.size != (W, H):
        print(f"base must be {W}x{H}, got {base.size}"); return 1

    skin = dominant_skin(base)
    y0, y1, x0, x1 = find_eye_band(base)
    lash = (38, 36, 72, 255)
    print(f"skin {skin[:3]}   eye band y{y0}..{y1}  x{x0}..{x1}")

    cells = [base, close_eyes(base, 0.55, skin, lash), close_eyes(base, 1.0, skin, lash)]

    sheet = Image.new("RGBA", (W * LIDS, H * MOODS), (0, 0, 0, 0))
    for row in range(MOODS):
        for col in range(LIDS):
            sheet.alpha_composite(cells[col], (col * W, row * H))
    sheet.save(sys.argv[2])

    data = list(sheet.getdata())
    cols = {p[:3] for p in data if p[3] > 0}
    semi = sum(1 for p in data if 0 < p[3] < 255)
    print(f"sheet {sheet.size[0]}x{sheet.size[1]}  colours={len(cols)}  semi-alpha={semi}")
    print("  " + ("PASS" if semi == 0 and len(cols) <= 32 else "FAIL"))
    print("  NOTE: blink is derived; mood rows still reuse NEUTRAL until the eyes"
          "\n        and mouth are hand-edited ON THE BASE (keeps registration).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
