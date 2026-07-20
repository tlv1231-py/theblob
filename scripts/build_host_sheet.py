#!/usr/bin/env python3
"""Build the RetroNews host sheet from per-mood 72x90 portraits.

    python scripts/build_host_sheet.py dashboard/retronews_host.png \
        NEUTRAL=art/neutral.png HAPPY=art/happy.png ...

Sheet: 3 lid columns x 7 rows of 72x90 = 216x630, indexed by retronews.js as
column = eyelid, row = mood. Row order is fixed by MOOD_ROW in retronews.js.

The 7th row is TALK — NEUTRAL with the mouth open. It is a MOUTH state, not a
mood, and never enters hostMood: the face is static and the mouth swaps over the
top of it, which is how GBA portraits animated speech.

REGISTRATION IS THE WHOLE GAME.
Each mood is a separate image, so the skull/hair/headset/shirt are NOT
automatically identical the way they were when every cell came from one base.
They must be EDITS of the same portrait, and they still land a few source pixels
off — measured -1..-2 x, +2..+3 y across all four variants, i.e. a systematic
reframe rather than per-image wobble. That offset is corrected at CROP time in
prep_art.py (before the downscale), which is the only place sub-output-pixel
precision exists: once you are at 72x90 a 1px shift is 3 device pixels and there
is nothing left to align with. Feed this script art that is already aligned.

WHAT IS DERIVED, AND WHAT REFUSES TO BE
The BLINK is derived per mood: the eye band is found by scanning for sclera-
bright pixels, then lids close per COLUMN (a bounding box would swallow the nose
bridge and read as a band across his face).
Moods whose eyes are ALREADY shut have no sclera to find — HAPPY is squeezed
into arcs, SLEEPY is closed outright. For those, blink derivation is SKIPPED and
all three lid columns hold the same cell. That is not a fallback, it is correct:
you do not blink with your eyes already closed.
SLEEPY itself is derived from NEUTRAL by closing the lids fully, rather than
generated. Closed eyes at this size ARE the whole expression.
"""
from __future__ import annotations

import sys
from collections import Counter
from PIL import Image

W, H = 72, 90
LIDS = 3
# Must match MOOD_ROW in dashboard/retronews.js.
ROWS = ["NEUTRAL", "HAPPY", "SURPRISED", "SMUG", "WORRIED", "SLEEPY", "TALK"]
# Too few eye columns to trust the scan => eyes are already closed.
MIN_EYE_COLS = 8


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


def find_eye_band(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Row range + x extent of the eyes, found by counting sclera-bright pixels
    in the upper-middle of the face rather than by hardcoding coordinates —
    hardcoding breaks the moment the art is re-cropped.

    Returns None when the face has NO sclera at all. That is not an error case
    to paper over — it is how a shut-eyed mood identifies itself, and HAPPY hit
    it immediately (its eyes are lash arcs, no white anywhere).
    """
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
    if best[0] == 0:
        return None
    keep = [(n, y, xs) for n, y, xs in rows[:5] if n >= max(2, best[0] // 3)]
    ys = sorted(y for _, y, _ in keep)
    # x extent must come from EVERY kept row, not just the brightest one. Taking
    # it from `best` alone gave the width of the eye at its widest SINGLE line,
    # so the tapering outer corners fell outside the mask and kept their sclera:
    # the "fully shut" lid left slivers of eye-white behind, and derived-SLEEPY
    # reported 8 still-open columns, which is what exposed this.
    xs_all = [x for _, _, xs in keep for x in xs]
    x0 = min(xs_all) if xs_all else int(W * 0.25)
    x1 = max(xs_all) if xs_all else int(W * 0.75)
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

    def dark(y: int, x: int) -> bool:
        if not (0 <= y < H):
            return False
        r, g, b, a = px[x, y]
        return bool(a) and r < 110 and g < 110 and b < 140

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
            if bright or dark(y, x):
                ys.append(y)
        if len(ys) < 2:
            continue
        # GROW through the eye KEYLINE instead of dilating a fixed amount.
        # A fixed 1px dilation was not enough: the dark outline is 2-3px thick
        # at this scale and sits outside the sclera rows the band scan finds, so
        # the lid filled the white and left the ring — reading as a blank
        # staring oval, which is far creepier than an open eye. Growing while
        # pixels stay dark swallows the whole outline and stops at cheek skin,
        # so it cannot run up into the EYEBROW (there is a skin gap between).
        top, bot = min(ys), max(ys)
        while dark(top - 1, x):
            top -= 1
        while dark(bot + 1, x):
            bot += 1
        cols[x] = (max(0, top), min(H - 1, bot))
    return cols


def eye_region(base: Image.Image, y0: int, y1: int, x0: int, x1: int, skin):
    """Per-column extent of the WHOLE eye blob, flood-filled from the sclera.

    Replaces a per-column scan of the sclera's own columns, which could not
    close the eye: the keyline is a RING, so its left and right arcs live in
    columns that contain no sclera and no pupil at all. Those columns were never
    in the mask, the lid filled everything except them, and the result was an
    empty socket outline — visibly worse than leaving the eye open.

    Flooding over non-skin pixels from the sclera follows the ring because the
    ring touches what it encloses. The upward bound is y0-3, which stops it
    reaching the EYEBROW: brow and eye are separated by a row of cheek skin, but
    they nearly touch at the outer corner and a leak there would erase his brows.
    """
    px = base.load()

    def nonskin(x: int, y: int) -> bool:
        p = px[x, y]
        return bool(p[3]) and (abs(p[0] - skin[0]) + abs(p[1] - skin[1])
                               + abs(p[2] - skin[2])) > 60

    ylo, yhi = max(0, y0 - 3), min(H - 1, y1 + 5)
    xlo, xhi = max(0, x0 - 3), min(W - 1, x1 + 3)
    stack = [(x, y) for x in range(xlo, xhi + 1) for y in range(ylo, yhi + 1)
             if px[x, y][3] and px[x, y][0] > 205 and px[x, y][1] > 205
             and px[x, y][2] > 195]
    seen = set(stack)
    while stack:
        x, y = stack.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (xlo <= nx <= xhi and ylo <= ny <= yhi
                    and (nx, ny) not in seen and nonskin(nx, ny)):
                seen.add((nx, ny)); stack.append((nx, ny))

    cols: dict[int, tuple[int, int]] = {}
    for x, y in seen:
        a, b = cols.get(x, (y, y))
        cols[x] = (min(a, y), max(b, y))
    return cols


def close_eyes(base: Image.Image, amount: float, skin, lash) -> Image.Image:
    """amount 0 = open, ~0.55 = half, 1 = shut. Closes each eye per column."""
    img = base.copy()
    band = find_eye_band(base)
    if amount <= 0 or band is None:
        return img                      # no open eye to close
    y0, y1, x0, x1 = band
    cols = eye_region(base, y0, y1, x0, x1, skin[:3])
    px = img.load()
    for x, (ey0, ey1) in cols.items():
        h = ey1 - ey0 + 1
        if amount >= 1.0:
            # Erase the eye outright, then lay ONE lash line across the middle.
            # Filling top-down and stopping short is what left the lower arc of
            # the ring in place; a shut eye keeps no part of the open drawing.
            for y in range(ey0, ey1 + 1):
                px[x, y] = skin
            px[x, (ey0 + ey1) // 2] = lash
        else:
            cover = max(1, int(round(h * amount)))
            for y in range(ey0, ey0 + cover):
                px[x, y] = skin
            px[x, min(ey0 + cover - 1, ey1)] = lash  # lash rides the lid edge
    return img


def lower_brows(img: Image.Image, n: int = 1) -> Image.Image:
    """Drop NEUTRAL's eyebrows one pixel, closer to the eye.

    As generated, NEUTRAL's brows sit at y31-33 with the lash at y36 — a wide
    gap, held high, and thinning to the OUTER ends so the inner ends read as
    raised. That is the startled/worried brow, and next to SURPRISED in the same
    sheet it is nearly the same pose: he looked frightened at rest, which is a
    poor face for an anchor who is on screen most of the time.

    One pixel is the whole fix. Two was tried and merges the brow into the lash
    line, which reads as a glare rather than a neutral.

    NEUTRAL ONLY, and applied at BUILD time rather than to the source art:
    SURPRISED and WORRIED are supposed to have raised brows, and leaving
    art/host/NEUTRAL.png as generated keeps this reversible if better art arrives.
    TALK and SLEEPY both derive FROM NEUTRAL, so they inherit the fix for free —
    which is the argument for doing it here and not in three places.

    Zone is y31-34, x24-48: tight to the brow. A looser box caught the hair
    fringe hanging at y29-30 and shifted that down too, leaving specks on the
    forehead.
    """
    g = img.copy()
    px, src = g.load(), img.load()
    skin = dominant_skin(img)
    Y0, Y1, X0, X1 = 31, 34, 24, 48
    pts = [(x, y) for y in range(Y0, Y1 + 1) for x in range(X0, X1 + 1)
           if src[x, y][3] and src[x, y][0] < 130 and src[x, y][1] < 125]
    if not pts:
        return g
    for x, y in pts:
        px[x, y] = skin
    for x, y in pts:
        px[x, y + n] = src[x, y]
    return g


# The headset mic is a solid dark block starting here. It sits at the same
# height as the mouth and would otherwise be read as part of it.
MIC_X = 41


def mouth_pixels(img: Image.Image):
    """The closed mouth: dark ink in the lower face, LEFT of the mic."""
    px = img.load()
    out = []
    for y in range(50, 59):
        for x in range(28, MIC_X):
            p = px[x, y]
            if p[3] and p[0] < 140 and p[1] < 130:
                out.append((x, y))
    return out


def open_mouth(img: Image.Image, rows: int = 1) -> Image.Image:
    """Hang a cavity under the lip line.

    His mouth is FOUR PIXELS WIDE, so "open" is one dark row beneath the lip —
    not a drawn cavity. Two rows was tried and reads as a black box.

    This is derivation by ADDITION, which is why it is riskier than the blink
    (removal): closing an eye covers something that exists, opening a mouth
    invents geometry. It is kept to the minimum that reads as movement, and only
    under columns that already HAVE a lip, so the shape follows the mouth rather
    than stamping a rectangle.

    NEUTRAL only, deliberately. SMUG's smirk is diagonal and a rectangular cavity
    below it reads as two disconnected shapes — and he never talks in SMUG
    anyway: the speech arc puts every typed character inside the NEUTRAL beat.
    """
    g = img.copy()
    px = g.load()
    m = mouth_pixels(img)
    if not m:
        return g
    ink = img.load()[m[0][0], m[0][1]]
    lowest = {}
    for x, y in m:
        lowest[x] = max(lowest.get(x, -1), y)
    for x, ylow in lowest.items():
        for k in range(1, rows + 1):
            if ylow + k < H:
                px[x, ylow + k] = ink
    return g


def sclera_cols(img: Image.Image) -> int:
    """Columns containing VISIBLE WHITE OF THE EYE.

    Deliberately not `len(eye_mask(...))`: that counts dark pixels too, and a
    squeezed-shut happy eye is a dark LASH ARC, so it scored 9 columns against
    neutral's 10 and the two were indistinguishable. Sclera is the only signal
    that actually means "this eye is open" — HAPPY and SLEEPY have none.
    """
    band = find_eye_band(img)
    if band is None:
        return 0
    px = img.load()
    y0, y1, _, _ = band
    n = 0
    for x in range(W):
        for y in range(max(0, y0 - 2), min(H, y1 + 3)):
            r, g, b, a = px[x, y]
            if a and r > 205 and g > 205 and b > 195:
                n += 1
                break
    return n


def lid_cells(img: Image.Image, name: str) -> list[Image.Image]:
    """Three lid states, or three copies when the eyes are already shut."""
    n = sclera_cols(img)
    if n < MIN_EYE_COLS:
        print(f"  {name:10s} eyes already closed ({n} cols) — blink skipped")
        return [img, img, img]
    skin, lash = dominant_skin(img), (38, 36, 72, 255)
    print(f"  {name:10s} blink derived from {n} eye columns")
    return [img, close_eyes(img, 0.55, skin, lash), close_eyes(img, 1.0, skin, lash)]


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__); return 2
    dst = sys.argv[1]
    src = {}
    for arg in sys.argv[2:]:
        k, _, v = arg.partition("=")
        src[k.upper()] = v

    if "NEUTRAL" not in src:
        print("NEUTRAL is required — SLEEPY is derived from it"); return 1

    moods: dict[str, Image.Image] = {}
    for name, path in src.items():
        im = Image.open(path).convert("RGBA")
        if im.size != (W, H):
            print(f"{name}: must be {W}x{H}, got {im.size}"); return 1
        moods[name] = im

    # SLEEPY is closed eyes on the neutral face. Deriving it beats generating it:
    # it cannot drift, because it IS the neutral pixels.
    # Calm his brows FIRST, so TALK and SLEEPY inherit it — both derive from
    # NEUTRAL and would otherwise keep the startled pose.
    moods["NEUTRAL"] = lower_brows(moods["NEUTRAL"], 1)
    print("  NEUTRAL    brows lowered 1px (was reading as startled)")

    # TALK is NEUTRAL with the mouth open — derived, never generated, so it
    # cannot drift from the face it belongs to.
    if "TALK" not in moods:
        moods["TALK"] = open_mouth(moods["NEUTRAL"], 1)
        print("  TALK       derived from NEUTRAL (mouth opened 1px)")

    if "SLEEPY" not in moods:
        n = moods["NEUTRAL"]
        moods["SLEEPY"] = close_eyes(n, 1.0, dominant_skin(n), (38, 36, 72, 255))
        print("  SLEEPY     derived from NEUTRAL (lids fully closed)")

    sheet = Image.new("RGBA", (W * LIDS, H * len(ROWS)), (0, 0, 0, 0))
    missing = []
    for row, name in enumerate(ROWS):
        img = moods.get(name)
        if img is None:
            missing.append(name)
            img = moods["NEUTRAL"]
            print(f"  {name:10s} MISSING — falls back to NEUTRAL")
        for col, cell in enumerate(lid_cells(img, name)):
            sheet.alpha_composite(cell, (col * W, row * H))
    sheet.save(dst)

    data = list(sheet.getdata())
    cols = {p[:3] for p in data if p[3] > 0}
    semi = sum(1 for p in data if 0 < p[3] < 255)
    ok = semi == 0 and len(cols) <= 40 and not missing
    print(f"sheet {sheet.size[0]}x{sheet.size[1]}  colours={len(cols)}  semi-alpha={semi}")
    print("  " + (f"PASS — all {len(ROWS)} rows drawn" if ok
                  else f"FAIL — missing {missing}" if missing else "FAIL — check above"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
