"""
Bake THE BLOB into two 48x48-cell sprite sheets.

    dashboard/blob_body.png   192x336   4 cols (breath) x 7 rows (mood)  body+brows+mouth
    dashboard/blob_eyes.png   144x336   3 cols (lid)    x 7 rows (mood)  eyes+glints

The silhouette/shading math is ported from dashboard/blob.js so the baked art IS
the established character rather than a lookalike. Everything the engine does
procedurally (bob, jitter, glance, particles, bloom, scale) is deliberately NOT
baked -- see "DO NOT DRAW THESE" in the brief.

Registration: the centre is PIXEL (24,25), i.e. cx/cy = 24.5/25.5 in continuous
coords. That is the only reading under which the brief's own numbers agree
(span x8-40 = 33px wide) and it matches the mirror axis of blob.js's face
(x -> 48-x). blob.js's *body* uses cx=24.0 and so mirrors about 23.5 -- its face
is 1px right of its body. These sheets fix that; everything mirrors about x=24.

    python scripts/gen_blob_sprites.py
"""

import math
import numpy as np
from PIL import Image
from pathlib import Path

CELL = 48
ROWS = ['IDLE', 'HAPPY', 'SCARED', 'ALERT', 'SLEEP', 'SMUG', 'BRACE']
BODY_COLS, EYE_COLS = 4, 3

OUT_DIR = Path(__file__).resolve().parents[1] / 'dashboard'

# ── Locked palette. These 10 and nothing else. ────────────────────────────────
P = {
    'OUT':  (0x2A, 0x00, 0x3D),
    'LO':   (0x8A, 0x00, 0x6C),
    'MID':  (0xFF, 0x00, 0xCC),   # identity colour
    'HI':   (0xFF, 0x6E, 0xE2),
    'SPEC': (0xFF, 0xC8, 0xF8),
    'EYE':  (0x0A, 0x00, 0x10),
    'GRN':  (0x00, 0xFF, 0x9D),
    'RED':  (0xFF, 0x33, 0x66),
    'CYN':  (0x00, 0xE5, 0xFF),
    'WHT':  (0xFF, 0xFF, 0xFF),
}
RAMP = [P['OUT'], P['LO'], P['MID'], P['HI'], P['SPEC']]   # dark -> light

# 4x4 Bayer, as in blob.js. Shading is DITHERED against the ramp, never lerped.
BAYER = [v / 16 - 0.5 for v in
         [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]]

CX, CY = 24.5, 25.5          # continuous -> centre pixel is (24,25)
FX, FY = 24, 23              # face anchor: fy = round(cy)-2, as in blob.js
LX, LY, LZ = -0.55, -0.68, 0.48      # single light source, upper-left
LLEN = math.sqrt(LX * LX + LY * LY + LZ * LZ)

BASE_R = 13.0                # tuned so the widest mood still lands inside x8-40
BREATHE = 0.055              # ~0.8px at the rim. Breathing, not bouncing.

# ── Shading ───────────────────────────────────────────────────────────────────
# blob.js uses lam*0.92+0.30 straight off the sphere normal. Baked, that leaves
# MID at 14.8% -- the LEAST common body colour, behind SPEC at 23.8% -- and he
# reads as pale pastel instead of #FF00CC. The brief says MID is "the bulk of
# him", so this is re-solved rather than ported:
#
#   WRAP  a directional light on a sphere is inherently bimodal (bright
#         upper-left rim, dark lower-right rim, thin mid-band), so no exposure
#         alone can centre him on MID -- lowering ambient just dumps him into
#         LO. Wrapping lifts the dark side and fattens the mid-band.
#   SPEC  is now PAINTED as an explicit hot spot rather than being the top of a
#         stretched diffuse ramp. Compressing the ramp enough to reach MID
#         plurality otherwise annihilated the highlight (SPEC -> 1.1%). This is
#         also just how 8-bit sprites are actually shaded: a discrete highlight
#         blob, not a physically-derived falloff.
#
# Solved against a target of LO 20 / MID 40 / HI 28 / SPEC 8. Result: 18.7 /
# 42.6 / 29.1 / 9.7. Re-run scripts/verify_blob_sprites.py if you touch these --
# it asserts MID stays the plurality.
SH_WRAP, SH_GAIN, SH_AMB, SH_SPEC = 0.80, 0.65, 0.16, 0.50


def jround(v):
    """JS Math.round. Python's round() is banker's rounding and would break the
    brow mirror (round(2.75) must be 3, and the -tilt/+inner pairing depends on
    it landing the same both sides)."""
    return math.floor(v + 0.5)


# ── Per-mood body deformation ─────────────────────────────────────────────────
# Ported from blob.js minus bob/jitter. `dim` walks the ramp down for SLEEP.
# `accent` is the rim light; None = stays pink (see notes re: IDLE/SMUG).
SHAPE = {
    'IDLE':   dict(sx=0.00, sy=0.00, dr=0.0, accent=None,     tremble=0.0, sag=0.0, dim=0),
    'HAPPY':  dict(sx=-0.05, sy=0.10, dr=0.0, accent='GRN',   tremble=0.0, sag=0.0, dim=0),
    'SCARED': dict(sx=0.13, sy=-0.16, dr=0.0, accent='RED',   tremble=0.030, sag=0.0, dim=0),
    'ALERT':  dict(sx=0.00, sy=0.00, dr=1.0, accent='CYN',    tremble=0.0, sag=0.0, dim=0),
    'SLEEP':  dict(sx=0.08, sy=-0.12, dr=-0.5, accent=None,   tremble=0.0, sag=0.035, dim=1),
    'SMUG':   dict(sx=0.06, sy=-0.03, dr=0.0, accent=None,    tremble=0.0, sag=0.0, dim=0),
    'BRACE':  dict(sx=0.10, sy=-0.13, dr=-0.6, accent='CYN',  tremble=0.0, sag=0.0, dim=0),
}

# Each mood gets its own fixed harmonic phase so its silhouette is its own lumpy
# egg rather than a clean sphere.
#
# The phase is FROZEN across the 4 breath columns, and that is load-bearing. It
# was advancing (a live, crawling edge, which looked better in isolation) -- but
# the harmonics are not symmetric, so advancing the phase walks the lumps around
# the rim and drags the centre of mass with them. Measured: SLEEP's bbox centre
# travelled y24.5 -> y26.5 across the loop. That is a BOB, baked in, on top of
# the one the engine already applies. Frozen phase means the breath is a pure
# radial scale about a fixed centre, so cols 0 and 2 are pixel-identical (both
# "neutral", as the brief specifies) and nothing drifts.
MOOD_PHASE = {m: i * 0.9 for i, m in enumerate(ROWS)}
# SCARED is the exception: at 1.8 its lumpy upper-right dipped under its own
# raised inner brow tip (the mirror tip at x21 was fine -- the egg is asymmetric,
# so a brow can clear one side and not the other). Which lump sits where is an
# arbitrary art knob, so it is retuned rather than flattening the brow. Swept for
# a value that clears all 4 breath frames; 2.85-3.60 all work.
MOOD_PHASE['SCARED'] = 3.30

# ── Brows. `tilt` drives the INNER end: + down (anger/focus), - up (worry). ───
BROWS = {
    'IDLE':   dict(drop=0,  tilt=0.00, th=1, on=True),
    'HAPPY':  dict(drop=-2, tilt=-0.15, th=1, on=True),
    # SCARED was drop=-3/tilt=-0.55 (ported from blob.js). Baked, its inner ends
    # reached y13 -- and SCARED squashes to sy=0.84, which brings the silhouette
    # top down to exactly y13. The brow was being drawn ON the outline. blob.js
    # gets away with it because its brow rides a live bob; a still frame does
    # not. This mood has only ~6px of forehead to work with: drop=0/tilt=-0.45
    # keeps the inner ends raised (worry, not anger) and reads high against
    # SCARED's big eyes, while staying inside the head.
    'SCARED': dict(drop=0, tilt=-0.45, th=1, on=True),
    'ALERT':  dict(drop=-3, tilt=0.00, th=2, on=True),
    # drop=1, not 0: the raised RIGHT brow is lift-3 above the base, so drop=0
    # threw its outer end to y16 and onto the head's upper-right rim. Lowering
    # the pair by 1 keeps the full 3px asymmetry -- which IS the mood -- intact.
    'SMUG':   dict(drop=1,  tilt=0.15, th=1, on=True),   # right brow lifts 3
    'BRACE':  dict(drop=1,  tilt=0.55, th=2, on=True),
    'SLEEP':  dict(drop=2,  tilt=0.00, th=1, on=False),  # a sleeping face is slack
}


class Cell:
    """A 48x48 RGBA buffer. Writes are palette-only and alpha is always 0 or 255."""

    def __init__(self):
        self.a = np.zeros((CELL, CELL, 4), dtype=np.uint8)

    def px(self, x, y, c):
        if 0 <= x < CELL and 0 <= y < CELL:
            self.a[y, x] = (c[0], c[1], c[2], 255)

    def rect(self, x, y, w, h, c):
        for j in range(h):
            for i in range(w):
                self.px(x + i, y + j, c)

    def rows(self, spans, c):
        """spans: [(y, x0, x1_inclusive), ...]"""
        for y, x0, x1 in spans:
            for x in range(x0, x1 + 1):
                self.px(x, y, c)


def draw_body(cell, mood, col):
    """Silhouette + dithered shading + dithered rim accent. No face."""
    s = SHAPE[mood]
    breathe = math.sin(col * math.pi / 2) * BREATHE   # 0, +amp, 0, -amp -> seamless
    ph = MOOD_PHASE[mood]                             # frozen -- see MOOD_PHASE

    sx = 1.0 + s['sx'] + breathe * 0.5
    sy = 1.0 + s['sy'] + breathe
    R = BASE_R + s['dr']
    accent = P[s['accent']] if s['accent'] else None

    for y in range(CELL):
        for x in range(CELL):
            dx = (x + 0.5 - CX) / sx
            dy = (y + 0.5 - CY) / sy
            d = math.hypot(dx, dy)
            if d == 0:
                d = 1e-6
            th = math.atan2(dy, dx)

            # Sine harmonics aliasing against the pixel grid. The jaggies ARE
            # the aesthetic -- never smooth this.
            wob = (1
                   + 0.055 * math.sin(3 * th + ph * 1.10)
                   + 0.038 * math.sin(5 * th - ph * 0.80)
                   + 0.026 * math.sin(2 * th + ph * 0.55))
            if s['tremble']:
                wob += s['tremble'] * math.sin(9 * th + ph * 9)
            if s['sag']:
                wob += s['sag'] * math.sin(th)        # +y is down -> bottom bulges
            r = R * wob
            if d > r:
                continue

            # Outline drawn INSIDE the silhouette so the edge stays crisp.
            if d > r - 1.15:
                cell.px(x, y, P['OUT'])
                continue

            nd = d / r
            nz = math.sqrt(max(0.0, 1 - nd * nd))
            lam = (dx / r) * LX + (dy / r) * LY + nz * LZ
            lw = lam * (1 - SH_WRAP) + SH_WRAP * (lam * 0.5 + 0.5)
            v = max(0.0, min(1.0, lw * SH_GAIN + SH_AMB))
            bay = BAYER[(y % 4) * 4 + (x % 4)]

            idx = jround(v * (len(RAMP) - 1) + bay * 1.05)
            idx = max(1, min(len(RAMP) - 1, idx))
            if max(0.0, lam) ** 6 > SH_SPEC + bay * 0.30:
                idx = 4                                  # painted highlight
            if s['dim']:
                idx = max(1, min(3, idx - s['dim']))
            c = RAMP[idx]

            # Rim accent: a thin light on the LOWER-RIGHT edge only, dithered to
            # a pure palette colour rather than lerped. blob.js lerps here, which
            # is why ~32% of its pixels are off-ramp (a known deviation in
            # BLOB.md). Dithering keeps the locked-palette guarantee.
            if accent is not None:
                nx, ny = dx / d, dy / d
                facing = -(nx * LX + ny * LY) / LLEN     # >0 = away from the key
                rim = (nd ** 3.2) * max(0.0, facing)
                if rim > 0.42 + bay * 0.34:
                    c = accent
            cell.px(x, y, c)


BROW_W = 5      # was 6 (x16-21). At brow height the head is 6-9px above centre
                # and so already narrowing; 6px-wide brows overhung the upper
                # corners and their outer ends landed on the outline. 5px also
                # matches the eye width exactly.


def draw_brows(cell, mood):
    """A brow is a run of 1px columns stepped by `slope` -- NOT a rotated line.
    Rounding each column to a whole pixel is what keeps it on the grid and
    jagged; a real diagonal would anti-alias and stop reading as 8-bit.

    The right brow is the left one MIRRORED (x -> 48-x), then lifted for SMUG.
    blob.js instead re-derives it from a negated slope plus an `inner` offset,
    which only mirrors exactly when jr(i*t) + jr((w-1-i)*t) == jr((w-1)*t)
    happens to hold -- true for its tilt +/-0.55 but FALSE for +/-0.15, so its
    HAPPY brows are quietly 1px asymmetric. Mirroring the geometry is exact for
    any tilt and any width, and it is the same design intent: one pair of brows,
    not two independent marks.
    """
    B = BROWS[mood]
    if not B['on']:
        return
    by = FY - 4 + B['drop']
    lift = 3 if mood == 'SMUG' else 0      # SMUG lifts ONLY the right brow

    left = [(FX - 7 + i, by + jround(i * B['tilt'])) for i in range(BROW_W)]
    for x, y in left:
        cell.rect(x, y, 1, B['th'], P['EYE'])
    for x, y in left:
        cell.rect(48 - x, y - lift, 1, B['th'], P['EYE'])


def draw_mouth(cell, mood):
    my = FY + 8                             # y31
    E = P['EYE']
    if mood == 'HAPPY':                     # big OPEN smile
        cell.rows([(my - 1, 20, 20), (my - 1, 28, 28),
                   (my, 21, 27), (my + 1, 22, 26), (my + 2, 23, 25)], E)
    elif mood == 'SCARED':                  # small open worried mouth
        cell.rows([(my - 1, 23, 25), (my, 22, 26), (my + 1, 23, 25)], E)
    elif mood == 'ALERT':                   # small "o" -- hollow, or it is a blob
        cell.rows([(my - 1, 23, 25), (my, 23, 23), (my, 25, 25), (my + 1, 23, 25)], E)
    elif mood == 'SLEEP':                   # tiny
        cell.rows([(my, 23, 25)], E)
    elif mood == 'SMUG':                    # one-sided smirk
        cell.rows([(my, 21, 25), (my - 1, 26, 27)], E)
    elif mood == 'BRACE':                   # small tight line -- held breath
        cell.rows([(my, 23, 25), (my + 1, 23, 25)], E)
    else:                                   # IDLE -- small neutral
        cell.rows([(my, 22, 26)], E)


# ── Eyes ──────────────────────────────────────────────────────────────────────
# Written once for the LEFT eye, then offset for the right.
#
# The EYE SHAPE mirrors about pixel 24, but the GLINTS only translate: the key
# light is upper-left globally, so both eyes catch it on their own upper-left.
# Mirroring the glint would imply two light sources and instantly flatten him.
#
# The offset is DERIVED, not a constant: a left span [a,b] mirrors to [48-b,48-a],
# so dx = 48-a-b. It is 10 for a 5-wide eye but 11 for SCARED's 6-wide one --
# hardcoding 10 put the wide pair a pixel off-centre from the body.


def eye_shape(mood, lid):
    """-> (spans, key_glint, bounce_glint, bounce_colour) for the LEFT eye."""
    E, W, H = 'EYE', 'WHT', 'HI'

    if mood == 'SLEEP':
        # Closed in all 3 columns. A gentle 1px trough reads as sleep rather
        # than as a blink caught mid-frame.
        return [(24, 18, 20), (25, 17, 17), (25, 21, 21)], None, None, None

    if lid == 2:                                    # shut -- a 1px line
        w = (16, 21) if mood == 'SCARED' else (17, 21)
        return [(24, w[0], w[1])], None, None, None

    if mood == 'HAPPY':
        # Happy carets. A caret is a squeezed-SHUT eye -- it has no sphere to
        # wrap light around, so it carries no glints (see note in the report).
        if lid == 0:
            return ([(24, 17, 17), (23, 18, 18), (22, 19, 19), (23, 20, 20), (24, 21, 21),
                     (25, 17, 17), (24, 18, 18), (23, 19, 19), (24, 20, 20), (25, 21, 21)],
                    None, None, None)
        return ([(24, 17, 17), (23, 18, 20), (24, 21, 21),
                 (25, 17, 17), (24, 18, 20), (25, 21, 21)], None, None, None)

    if mood == 'SCARED':                            # WIDE -- 6x6, bigger than idle
        if lid == 0:
            sp = [(21, 17, 20)] + [(y, 16, 21) for y in range(22, 26)] + [(26, 17, 20)]
            return sp, (17, 22), (20, 25), H
        sp = [(y, 16, 21) for y in (24, 25)] + [(26, 17, 20)]
        return sp, (17, 24), (20, 26), H

    if mood == 'ALERT':                             # tall + narrow = focus, not fear
        # The lower-right bounce is CYN here: that IS the "CYN spark". Adding a
        # third mark to a 5x6 eye would just make it busy, and recolouring the
        # bounce reads as the terminal in front of him lighting his eye.
        if lid == 0:
            sp = [(21, 18, 20)] + [(y, 17, 21) for y in range(22, 26)] + [(26, 18, 20)]
            return sp, (18, 22), (20, 25), 'CYN'
        sp = [(y, 17, 21) for y in (24, 25)] + [(26, 18, 20)]
        return sp, (18, 24), (20, 26), 'CYN'

    if mood == 'SMUG':                              # half-lidded, self-satisfied
        if lid == 0:
            sp = [(y, 17, 21) for y in (24, 25)] + [(26, 18, 20)]
            return sp, (18, 24), (20, 26), H
        return [(y, 17, 21) for y in (24, 25)], (18, 24), None, None

    if mood == 'BRACE':                             # NARROWED slot -- focus
        # The slot sits at y24-26, not y23-25. Brows MIRROR but glints TRANSLATE,
        # so BRACE's inner brow (which descends, that being the scowl) is high
        # over the left eye's glint and LOW over the right eye's -- at y23 the
        # right key was buried and that eye went unreadable inside the brow mass.
        # Dropping one row clears both keys and the wedge still meets the eye.
        if lid == 0:
            return [(y, 17, 21) for y in (24, 25, 26)], (18, 24), (20, 26), H
        return [(y, 17, 21) for y in (25, 26)], (18, 25), None, None

    # IDLE -- round, open
    if lid == 0:
        sp = [(22, 18, 20)] + [(y, 17, 21) for y in (23, 24, 25)] + [(26, 18, 20)]
        return sp, (18, 23), (20, 25), H
    # half-lid: bottom ~60% with the lid across it. It MUST keep its glint --
    # a blank half-lid puts us back to the eye simply vanishing.
    sp = [(y, 17, 21) for y in (24, 25)] + [(26, 18, 20)]
    return sp, (18, 24), (20, 26), H


def draw_eyes(cell, mood, lid):
    spans, key, bounce, bcol = eye_shape(mood, lid)
    a = min(x0 for _, x0, _ in spans)
    b = max(x1 for _, _, x1 in spans)
    dxs = (0, 48 - a - b)                                   # mirror about pixel 24
    for dx in dxs:
        cell.rows([(y, x0 + dx, x1 + dx) for y, x0, x1 in spans], P['EYE'])
    for dx in dxs:
        if key:
            cell.px(key[0] + dx, key[1], P['WHT'])          # key, upper-left
        if bounce:
            cell.px(bounce[0] + dx, bounce[1], P[bcol])     # bounce, lower-right


def build():
    body = np.zeros((CELL * len(ROWS), CELL * BODY_COLS, 4), dtype=np.uint8)
    eyes = np.zeros((CELL * len(ROWS), CELL * EYE_COLS, 4), dtype=np.uint8)

    for r, mood in enumerate(ROWS):
        for c in range(BODY_COLS):
            cell = Cell()
            draw_body(cell, mood, c)
            draw_mouth(cell, mood)
            draw_brows(cell, mood)          # AFTER the mouth; may overlap the eye
            body[r * CELL:(r + 1) * CELL, c * CELL:(c + 1) * CELL] = cell.a
        for c in range(EYE_COLS):
            cell = Cell()
            draw_eyes(cell, mood, c)
            eyes[r * CELL:(r + 1) * CELL, c * CELL:(c + 1) * CELL] = cell.a

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    Image.fromarray(body, 'RGBA').save(OUT_DIR / 'blob_body.png')
    Image.fromarray(eyes, 'RGBA').save(OUT_DIR / 'blob_eyes.png')
    print(f'blob_body.png {body.shape[1]}x{body.shape[0]}')
    print(f'blob_eyes.png {eyes.shape[1]}x{eyes.shape[0]}')


if __name__ == '__main__':
    build()
