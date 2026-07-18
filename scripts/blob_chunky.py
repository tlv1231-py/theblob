"""
HALF-RES CHUNK style, all 7 moods, faces authored natively on the 24-grid.

Why native and not downsampled: the earlier chunky mockup rendered at 48 and
took every 2nd pixel, which ate the glints -- a 1px key glint has a 50% chance
of simply not surviving the decimation, and BLOB.md puts ~90% of the character
in the eyes. Low-res pixel art is AUTHORED at its resolution; it is never
resampled down to it. So every face here is an explicit pixel table.

Registration: 24-grid centre pixel is (12,12), continuous (12.0,12.5), giving a
48-space centre of (24.0,25.0) after the 2x block upscale. This is NOT the
brief's (24.5,25.5) -- it CANNOT be. 24.5/2 = 12.25 is neither a pixel centre
nor a boundary on the 24-grid, so a half-res character is asymmetric about it.
Half-res forces the centre onto a 2px grid. Mirror is i -> 23-i.

Budget: 24x24 = 576 logical px vs 2304. Everything is half-size: the eye is 4x4
where it was 5x5, the brow is 3 wide where it was 5, the mouth is 2.

    python scripts/blob_chunky.py <outdir>
"""

import math
import sys
import numpy as np
from PIL import Image
from pathlib import Path

G = 24                      # logical grid
CX, CY = 12.0, 12.5         # -> 48-space (24.0, 25.0). Mirror: i -> 23-i.
LX, LY, LZ = -0.55, -0.68, 0.48
ROWS = ['IDLE', 'HAPPY', 'SCARED', 'ALERT', 'SLEEP', 'SMUG', 'BRACE']

P = {'OUT': (0x2A, 0x00, 0x3D), 'LO': (0x8A, 0x00, 0x6C), 'MID': (0xFF, 0x00, 0xCC),
     'HI': (0xFF, 0x6E, 0xE2), 'SPEC': (0xFF, 0xC8, 0xF8), 'EYE': (0x0A, 0x00, 0x10),
     'GRN': (0x00, 0xFF, 0x9D), 'RED': (0xFF, 0x33, 0x66), 'CYN': (0x00, 0xE5, 0xFF),
     'WHT': (0xFF, 0xFF, 0xFF)}
RAMP = [P['OUT'], P['LO'], P['MID'], P['HI'], P['SPEC']]
BAYER4 = [v / 16 - 0.5 for v in [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]]
BAYER2 = [v / 4 - 0.5 for v in [0, 2, 3, 1]]

# THE dither does not survive half-res. A 4x4 Bayer cell is 1/6 of his width at
# 48px and 1/3 of it at 24px -- the lattice stops reading as shading and starts
# competing with the character. This is why Game Boy and NES sprites use flat
# colour regions: ordered dither needs resolution to average out, and there
# isn't any here. 'cel' and 'bayer2' are the two ways out.
DITHER = 'cel'             # 'bayer4' | 'bayer2' | 'cel'
# Measured, not asserted: at 24x24 bayer4 reads as noise, bayer2 is still busy,
# cel reads as a character on sight. The resolution was always what made him
# 8-bit; the dither was riding along.


def dith(x, y):
    if DITHER == 'bayer4':
        return BAYER4[(y % 4) * 4 + (x % 4)]
    if DITHER == 'bayer2':
        return BAYER2[(y % 2) * 2 + (x % 2)]
    return 0.0             # cel -- hard bands, no dither at all


def jr(v):
    return math.floor(v + 0.5)


SHAPE = {
    'IDLE':   dict(sx=0.00, sy=0.00, dr=0.0, acc=None,  trem=0.0, sag=0.0, dim=0, ph=0.0),
    'HAPPY':  dict(sx=-0.05, sy=0.10, dr=0.0, acc='GRN', trem=0.0, sag=0.0, dim=0, ph=0.9),
    # sy eased -0.16 -> -0.10: at 48px the squash left room for brows above a
    # 6px eye, but half-res eyes are proportionally taller and the forehead ran
    # out. Still reads squashed-wider-and-shorter; just not at the cost of the face.
    'SCARED': dict(sx=0.13, sy=-0.10, dr=0.0, acc='RED', trem=0.030, sag=0.0, dim=0, ph=3.3),
    'ALERT':  dict(sx=0.00, sy=0.00, dr=0.5, acc='CYN', trem=0.0, sag=0.0, dim=0, ph=2.7),
    'SLEEP':  dict(sx=0.08, sy=-0.12, dr=-0.3, acc=None, trem=0.0, sag=0.035, dim=1, ph=3.6),
    'SMUG':   dict(sx=0.06, sy=-0.03, dr=0.0, acc=None,  trem=0.0, sag=0.0, dim=0, ph=4.5),
    'BRACE':  dict(sx=0.10, sy=-0.13, dr=-0.3, acc='CYN', trem=0.0, sag=0.0, dim=0, ph=5.4),
}
# 7.1 is the contract ceiling: it wants a span of x8-40 in 48-space = radius 16
# = 8.0 on this grid, and the wobble peaks at 1.119x, so 8.0/1.119 = 7.15.
# Sitting at the ceiling is deliberate here -- the eye pair is 10 logical px
# wide and a smaller head leaves it no margin, which is what made the first
# pass read as eyes with a body attached.
BASE_R = 7.1
BREATHE = 0.055

# ── Faces, authored on the 24-grid. Left eye only; the right is the mirror. ───
# Eyes are 4 wide (i=7..10) -- 71% of head width across the pair. At this
# resolution an eye can only be expressive by being BIG; there is no room for
# subtlety, so the whole budget goes here. Mirror(7)=16, mirror(10)=13, so the
# right eye is i=13..16 and the pair is symmetric with a 2px nose gap.
#
# Glints TRANSLATE (dx=+6), never mirror -- the key is upper-left globally.
# 1 logical px = 2 screen px at 48, 32 at stream size. A glint is not small here.
# THE EYE IS 4x5, NOT 4x4, AND THAT IS FORCED. At 4x4 a rounded eye is 12px;
# the two glints take 2 of them and the remaining 10 form a broken ring -- each
# eye renders as a pinwheel. Verified against the alternatives: 4x4+2 glints is
# broken, 4x4 solid reads as sunglasses, 4x5 holds. BLOB.md's two-glint rule
# needs ~20px of eye to survive, so half-res sets the floor at 4x5.
E = {
    'IDLE':   dict(sp=[(10, 8, 9), (11, 7, 10), (12, 7, 10), (13, 7, 10), (14, 8, 9)],
                   k=(8, 11), b=(9, 13), bc='HI'),
    # squeezed shut with joy -- a caret has no sphere, so no glint (see report)
    'HAPPY':  dict(sp=[(11, 8, 9), (12, 7, 7), (12, 8, 9), (12, 10, 10),
                       (13, 7, 7), (13, 10, 10)], k=None, b=None, bc=None),
    # WIDE: taller AND squarer than idle -- more mass is the only way to read
    # "bigger than idle" when you cannot add width without closing the nose gap.
    # 4x6 = 20px vs idle's 16, so it reads bigger without eating the face. At
    # 4x7 it was 7 of SCARED's 13 head rows -- the pair merged into one dark
    # band and read as chaos, not fear. "Bigger than idle" has a ceiling when
    # idle is already 4x5 on a 24-grid.
    # SCARED's 14 usable head rows, budgeted: brows 7-8 | gap 9 | eyes 10-15 |
    # mouth 16-17 | margin 18-19. Every row is spoken for; this is what "half the
    # canvas" actually costs.
    'SCARED': dict(sp=[(10, 8, 9), (11, 7, 10), (12, 7, 10), (13, 7, 10),
                       (14, 7, 10), (15, 8, 9)], k=(8, 11), b=(9, 14), bc='HI'),
    # the bounce is CYN: that IS the spark. A third mark has nowhere to go here.
    'ALERT':  dict(sp=[(10, 8, 9), (11, 7, 10), (12, 7, 10), (13, 7, 10), (14, 8, 9)],
                   k=(8, 11), b=(9, 13), bc='CYN'),
    'SLEEP':  dict(sp=[(13, 8, 9), (14, 7, 7), (14, 10, 10)], k=None, b=None, bc=None),
    'SMUG':   dict(sp=[(12, 7, 10), (13, 7, 10), (14, 8, 9)], k=(8, 12), b=(9, 13), bc='HI'),
    'BRACE':  dict(sp=[(12, 7, 10), (13, 7, 10)], k=(8, 12), b=(10, 13), bc='HI'),
}
# Brows: 3 wide, left i=8..10 (mirror -> 13..15). `lift` is right-brow only.
B = {
    'IDLE':   dict(sp=[(9, 8, 10)], lift=0),
    'HAPPY':  dict(sp=[(8, 8, 9), (9, 10, 10)], lift=0),
    # j=7-8. At j=6-7 the raised inner end sat on the outline: SCARED's head is
    # the short one, so its forehead is the tightest in the set.
    'SCARED': dict(sp=[(8, 8, 9), (7, 10, 10)], lift=0),          # inner end UP = worry
    'ALERT':  dict(sp=[(8, 8, 10), (9, 8, 10)], lift=0),          # thick + straight
    'SLEEP':  dict(sp=[], lift=0),                                # slack
    'SMUG':   dict(sp=[(10, 8, 10)], lift=2),                     # ONLY the right lifts
    'BRACE':  dict(sp=[(9, 8, 8), (10, 9, 10), (11, 10, 10)], lift=0),   # down + in wedge
}
M = {
    'IDLE':   [(16, 11, 12)],
    'HAPPY':  [(16, 10, 13), (17, 11, 12)],
    'SCARED': [(16, 11, 12), (17, 11, 12)],
    'ALERT':  [(16, 11, 12), (17, 11, 12)],
    'SLEEP':  [(16, 11, 12)],
    'SMUG':   [(16, 10, 12), (15, 13, 13)],
    'BRACE':  [(16, 11, 12)],
}


class C:
    def __init__(self):
        self.a = np.zeros((G, G, 4), np.uint8)

    def px(self, x, y, c):
        if 0 <= x < G and 0 <= y < G:
            self.a[y, x] = (*c, 255)

    def rows(self, sp, c):
        for y, a, b in sp:
            for x in range(a, b + 1):
                self.px(x, y, c)


def body(c, mood, col):
    s = SHAPE[mood]
    br = math.sin(col * math.pi / 2) * BREATHE
    sx, sy = 1 + s['sx'] + br * 0.5, 1 + s['sy'] + br
    R = BASE_R + s['dr']
    acc = P[s['acc']] if s['acc'] else None
    for y in range(G):
        for x in range(G):
            dx, dy = (x + 0.5 - CX) / sx, (y + 0.5 - CY) / sy
            d = math.hypot(dx, dy) or 1e-6
            th = math.atan2(dy, dx)
            wob = (1 + 0.055 * math.sin(3 * th + s['ph'] * 1.1)
                     + 0.038 * math.sin(5 * th - s['ph'] * 0.8)
                     + 0.026 * math.sin(2 * th + s['ph'] * 0.55))
            if s['trem']:
                wob += s['trem'] * math.sin(9 * th + s['ph'] * 9)
            if s['sag']:
                wob += s['sag'] * math.sin(th)
            r = R * wob
            if d > r:
                continue
            if d > r - 0.62:            # outline: half of 1.15, to match the res
                c.px(x, y, P['OUT'])
                continue
            nd = d / r
            nz = math.sqrt(max(0.0, 1 - nd * nd))
            lam = (dx / r) * LX + (dy / r) * LY + nz * LZ
            lw = lam * 0.20 + 0.80 * (lam * 0.5 + 0.5)
            v = max(0.0, min(1.0, lw * 0.65 + 0.16))
            bay = dith(x, y)
            i = max(1, min(4, jr(v * 4 + bay * 1.05)))
            if max(0.0, lam) ** 6 > 0.50 + bay * 0.30:
                i = 4
            if s['dim']:
                i = max(1, min(3, i - s['dim']))
            col_ = RAMP[i]
            if acc is not None:
                nx, ny = dx / d, dy / d
                face_ = -(nx * LX + ny * LY) / math.sqrt(LX * LX + LY * LY + LZ * LZ)
                if (nd ** 3.2) * max(0.0, face_) > 0.42 + bay * 0.34:
                    col_ = acc
            c.px(x, y, col_)


def mirror(sp):
    return [(y, 23 - b, 23 - a) for y, a, b in sp]


def face(c, mood):
    c.rows(M[mood], P['EYE'])
    e = E[mood]
    dx = 23 - max(b for _, _, b in e['sp']) - min(a for _, a, _ in e['sp'])
    c.rows(e['sp'], P['EYE'])
    c.rows(mirror(e['sp']), P['EYE'])
    for o in (0, dx):
        if e['k']:
            c.px(e['k'][0] + o, e['k'][1], P['WHT'])
        if e['b']:
            c.px(e['b'][0] + o, e['b'][1], P[e['bc']])
    b = B[mood]
    c.rows(b['sp'], P['EYE'])
    c.rows([(y - b['lift'], a, bb) for y, a, bb in mirror(b['sp'])], P['EYE'])


def render(mood, col=0):
    c = C()
    body(c, mood, col)
    face(c, mood)
    return c.a


def up(a, z):
    return a.repeat(z, 0).repeat(z, 1)


if __name__ == '__main__':
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for m in ROWS:
        Image.fromarray(up(render(m), 2), 'RGBA').save(out / f'{m.lower()}.png')
        print(f'{m:7} ok')
