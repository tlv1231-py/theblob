"""
Design mockups: one IDLE cell per direction, so we can pick a look before
baking all 49 cells.

Same palette lock and same dither as the real bake -- these are honest previews,
not concept art. Writes 48x48 PNGs; view them upscaled with nearest-neighbour.

    python scripts/blob_variants.py <outdir>
"""

import math
import sys
import numpy as np
from PIL import Image
from pathlib import Path

CELL = 48
CX, CY = 24.5, 25.5
FX, FY = 24, 23
LX, LY, LZ = -0.55, -0.68, 0.48
LLEN = math.sqrt(LX * LX + LY * LY + LZ * LZ)
SH_WRAP, SH_GAIN, SH_AMB, SH_SPEC = 0.80, 0.65, 0.16, 0.50

P = {'OUT': (0x2A, 0x00, 0x3D), 'LO': (0x8A, 0x00, 0x6C), 'MID': (0xFF, 0x00, 0xCC),
     'HI': (0xFF, 0x6E, 0xE2), 'SPEC': (0xFF, 0xC8, 0xF8), 'EYE': (0x0A, 0x00, 0x10),
     'GRN': (0x00, 0xFF, 0x9D), 'RED': (0xFF, 0x33, 0x66), 'CYN': (0x00, 0xE5, 0xFF),
     'WHT': (0xFF, 0xFF, 0xFF)}
RAMP = [P['OUT'], P['LO'], P['MID'], P['HI'], P['SPEC']]
BAYER = [v / 16 - 0.5 for v in [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]]


def jr(v):
    return math.floor(v + 0.5)


# Each variant is a knob-set. `harm` = (freq, amp, phase) sine harmonics on the
# silhouette radius -- this is the lumpiness, and it is the main open question
# in BLOB.md ("clean lit sphere-blob" vs "lumpier, more asymmetric egg").
BASE_HARM = [(3, 0.055, 0.0), (5, 0.038, 0.0), (2, 0.026, 0.0)]

V = [
    dict(k='asbuilt', n='As built', d='What is in the sheets now.',
         harm=BASE_HARM, R=13.0, sx=1.0, sy=1.0, out=1.15, dith=1.05, eye=1.0, visor=False),

    dict(k='clean', n='Clean sphere', d='Wobble nearly off. Mascot-logo, reads at any size.',
         harm=[(3, 0.012, 0.0), (5, 0.008, 0.0), (2, 0.006, 0.0)],
         R=13.2, sx=1.0, sy=1.0, out=1.15, dith=1.05, eye=1.0, visor=False),

    dict(k='lumpy', n='Lumpy egg', d='The reference art. Uglier, funnier, less logo.',
         harm=[(3, 0.105, 0.7), (5, 0.070, 2.1), (2, 0.060, 0.3)],
         R=12.6, sx=0.98, sy=1.04, out=1.15, dith=1.05, eye=1.0, visor=False),

    dict(k='drippy', n='Drippy blob', d='Lumpy + squat + heavier low harmonics. Most gooey.',
         harm=[(3, 0.090, 1.4), (5, 0.055, 0.6), (2, 0.105, 1.9), (7, 0.030, 0.9)],
         R=12.8, sx=1.10, sy=0.90, out=1.15, dith=1.05, eye=1.0, visor=False),

    dict(k='bigeyes', n='Big eyes', d='Same body, +40% eyes. Comedy budget where BLOB.md wants it.',
         harm=BASE_HARM, R=13.0, sx=1.0, sy=1.0, out=1.15, dith=1.05, eye=1.4, visor=False),

    dict(k='visor', n='Visor', d='Sells "he is piloting it" -- costs the eyes.',
         harm=BASE_HARM, R=13.0, sx=1.0, sy=1.0, out=1.15, dith=1.05, eye=1.0, visor=True),

    dict(k='dither', n='Heavy dither', d='Stipple cranked. Most period-correct, noisiest.',
         harm=BASE_HARM, R=13.0, sx=1.0, sy=1.0, out=1.15, dith=2.20, eye=1.0, visor=False),

    dict(k='chunky', n='Chunky outline', d='2px outline, bigger. Sticker / Kirby-ish.',
         harm=BASE_HARM, R=13.8, sx=1.0, sy=1.0, out=2.30, dith=1.05, eye=1.0, visor=False),
]


class C:
    def __init__(self):
        self.a = np.zeros((CELL, CELL, 4), np.uint8)

    def px(self, x, y, c):
        if 0 <= x < CELL and 0 <= y < CELL:
            self.a[y, x] = (*c, 255)

    def rect(self, x, y, w, h, c):
        for j in range(h):
            for i in range(w):
                self.px(x + i, y + j, c)

    def rows(self, sp, c):
        for y, a, b in sp:
            for x in range(a, b + 1):
                self.px(x, y, c)


def render(v):
    c = C()
    for y in range(CELL):
        for x in range(CELL):
            dx, dy = (x + 0.5 - CX) / v['sx'], (y + 0.5 - CY) / v['sy']
            d = math.hypot(dx, dy) or 1e-6
            th = math.atan2(dy, dx)
            wob = 1 + sum(a * math.sin(f * th + p) for f, a, p in v['harm'])
            r = 13.0 / 13.0 * v['R'] * wob
            if d > r:
                continue
            if d > r - v['out']:
                c.px(x, y, P['OUT'])
                continue
            nd = d / r
            nz = math.sqrt(max(0.0, 1 - nd * nd))
            lam = (dx / r) * LX + (dy / r) * LY + nz * LZ
            lw = lam * (1 - SH_WRAP) + SH_WRAP * (lam * 0.5 + 0.5)
            val = max(0.0, min(1.0, lw * SH_GAIN + SH_AMB))
            bay = BAYER[(y % 4) * 4 + (x % 4)]
            i = max(1, min(4, jr(val * 4 + bay * v['dith'])))
            if max(0.0, lam) ** 6 > SH_SPEC + bay * 0.30:
                i = 4
            c.px(x, y, RAMP[i])

    c.rows([(FY + 8, 22, 26)], P['EYE'])                       # neutral mouth

    if v['visor']:
        c.rect(FX - 9, FY - 2, 18, 5, P['OUT'])
        for i in range(-8, 9):
            c.rect(FX + i, FY - 1, 1, 3, P['WHT'] if abs(i - 3) < 2 else P['CYN'])
    else:
        # eye: round, two glints (WHT key upper-left, HI bounce lower-right)
        s = v['eye']
        w = max(1, round(2 * s))          # half-width of the flat rows
        h = max(1, round(2 * s))
        for dxo in (0, 10 + (2 * (w - 2))):
            x0 = 17 - (w - 2) + dxo
            x1 = 21 + (w - 2) + dxo
            top = FY - 1 - (h - 2)
            bot = FY + 3 + (h - 2)
            sp = [(top, x0 + 1, x1 - 1)] + [(y, x0, x1) for y in range(top + 1, bot)] \
                 + [(bot, x0 + 1, x1 - 1)]
            c.rows(sp, P['EYE'])
            c.px(x0 + 1, top + 1, P['WHT'])
            c.px(x1 - 1, bot - 1, P['HI'])
        # flat brows
        for i in range(5):
            c.rect(FX - 7 + i, FY - 4, 1, 1, P['EYE'])
            c.rect(48 - (FX - 7 + i), FY - 4, 1, 1, P['EYE'])
    return c.a


if __name__ == '__main__':
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for v in V:
        Image.fromarray(render(v), 'RGBA').save(out / f"{v['k']}.png")
        print(v['k'], v['n'])
