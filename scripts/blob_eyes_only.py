"""
Eyes-only Blobby. A clean pink circle + cartoonishly large expressive eyes.
No mouth (or one tasteful line), no arm, no fangs, no tongue. The eyes do all
the expressing — this is BLOB.md's actual thesis.

We're nailing the CONFIDENT face first, then it becomes the reference.

    python scripts/blob_eyes_only.py <outdir>
"""

import math
import sys
import numpy as np
from PIL import Image
from pathlib import Path

CELL = 48
LX, LY, LZ = -0.55, -0.68, 0.48
P = {'OUT': (0x2A, 0x00, 0x3D), 'LO': (0x8A, 0x00, 0x6C), 'MID': (0xFF, 0x00, 0xCC),
     'HI': (0xFF, 0x6E, 0xE2), 'SPEC': (0xFF, 0xC8, 0xF8), 'EYE': (0x0A, 0x00, 0x10),
     'WHT': (0xFF, 0xFF, 0xFF)}
RAMP = [P['OUT'], P['LO'], P['MID'], P['HI'], P['SPEC']]


class A:
    def __init__(self):
        self.a = np.zeros((CELL, CELL, 4), np.uint8)

    def set(self, x, y, c):
        if 0 <= x < CELL and 0 <= y < CELL:
            self.a[y, x] = (*c, 255)

    def get(self, x, y):
        return tuple(int(v) for v in self.a[y, x][:3]) if self.a[y, x, 3] == 255 else None

    def disc(self, cx, cy, r, c):
        for y in range(int(cy - r - 1), int(cy + r + 2)):
            for x in range(int(cx - r - 1), int(cx + r + 2)):
                if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r:
                    self.set(x, y, c)

    def ellipse(self, cx, cy, rx, ry, c, only_white=False):
        for y in range(int(cy - ry - 1), int(cy + ry + 2)):
            for x in range(int(cx - rx - 1), int(cx + rx + 2)):
                if ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2 <= 1:
                    if only_white and self.get(x, y) != P['WHT']:
                        continue
                    self.set(x, y, c)


def body(st, cx, cy, R, gloss):
    """Clean cel-shaded pink circle, light upper-left, OUT outline."""
    for y in range(CELL):
        for x in range(CELL):
            dx, dy = x + 0.5 - cx, y + 0.5 - cy
            d = math.hypot(dx, dy)
            if d > R:
                continue
            if d > R - 1.4:
                st.set(x, y, P['OUT'])
                continue
            nd = d / R
            nz = math.sqrt(max(0.0, 1 - nd * nd))
            lam = (dx / R) * LX + (dy / R) * LY + nz * LZ
            lw = lam * 0.20 + 0.80 * (lam * 0.5 + 0.5)
            v = max(0.0, min(1.0, lw * 0.65 + 0.16))
            i = 1 if v < 0.30 else (2 if v < 0.62 else (3 if v < 0.90 else 4))
            st.set(x, y, RAMP[i])
    for (gx, gy, gr) in gloss:
        st.disc(gx, gy, gr, P['SPEC'])


def big_eye(st, cx, cy, rx, ry, lidFrac, curve, pupR, pupDx, pupDy):
    """A large cartoon eye with a clean curved lid. lidFrac 0=wide open, 1=shut.
    curve>0 lowers the lid's outer ends (sleepy/soft), <0 lowers its centre."""
    st.ellipse(cx, cy, rx + 1, ry + 1, P['OUT'])          # outline
    st.ellipse(cx, cy, rx, ry, P['WHT'])                  # eyeball
    # eyelid: repaint the top down to a curved lash line with body pink, then
    # draw the lash line itself.
    lidBase = cy - ry + 2 * ry * lidFrac
    for x in range(int(cx - rx - 1), int(cx + rx + 2)):
        u = (x - cx) / rx
        lb = lidBase + curve * (u * u) * ry
        for y in range(int(cy - ry - 1), int(lb) + 1):
            if st.get(x, y) == P['WHT']:
                st.set(x, y, P['MID'])
        yl = int(round(lb))
        if st.get(x, yl) == P['WHT'] or st.get(x, yl) == P['MID']:
            st.set(x, yl, P['EYE'])
    # pupil, sitting in the visible lower part
    st.disc(cx + pupDx, cy + pupDy, pupR, P['EYE'])
    # two glints: big WHT key upper-left, small HI bounce lower-right
    st.disc(cx + pupDx - pupR * 0.45, cy + pupDy - pupR * 0.5, max(1.3, pupR * 0.42), P['WHT'])
    st.set(int(cx + pupDx + pupR * 0.5), int(cy + pupDy + pupR * 0.45), P['HI'])


def line_mouth(st, cx, y, w):
    for x in range(cx - w, cx + w + 1):
        st.set(x, y, P['EYE'])


def dumb_smile(st, cx, y, w):
    """One tasteful line, curled up at the ends — a confident-dumb-guy smile."""
    for x in range(cx - w, cx + w + 1):
        st.set(x, y, P['EYE'])
    st.set(cx - w - 1, y - 1, P['EYE'])
    st.set(cx + w + 1, y - 1, P['EYE'])


# ── CONFIDENT DUMB GUY — small circle, line-smile, wall-eyed pupils ──────────
# `div` = how far apart the pupils point (the derp). `lid` = confident half-lid.
# `pupY` = vertical pupil offset within the visible eye.
def make(kind, div=2.0, lid=0.34, pupY=2, smileY=35, smileW=3):
    st = A()
    cx, cy, R = 24, 29, 14
    body(st, cx, cy, R, [(18, 35, 2.0)])
    # left pupil looks LEFT, right pupil looks RIGHT — the confident-dumb wall-eye
    big_eye(st, 17, 23, 7, 8, lid, 0.10, 3.0, -div, pupY)
    big_eye(st, 31, 23, 7, 8, lid, 0.10, 3.0,  div, pupY)
    dumb_smile(st, cx, smileY, smileW)
    return st.a


VARIANTS = [
    ('derp_a', 'A · mild derp',   dict(div=1.5, lid=0.34, pupY=2)),
    ('derp_b', 'B · full derp',   dict(div=2.6, lid=0.34, pupY=2)),
    ('derp_c', 'C · derp, look-up', dict(div=2.2, lid=0.28, pupY=1)),
]


if __name__ == '__main__':
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    Z = 12
    strip = Image.new('RGBA', (48 * len(VARIANTS), 48), (0, 0, 0, 0))
    for i, (k, n, kw) in enumerate(VARIANTS):
        im = Image.fromarray(make(k, **kw), 'RGBA')
        im.save(out / (k + '.png'))
        strip.paste(im, (i * 48, 0), im)
    bg = Image.new('RGBA', strip.size, (30, 8, 52, 255))
    bg.alpha_composite(strip)
    bg.resize((strip.width * Z, strip.height * Z), Image.NEAREST).save(out / 'eyes_strip.png')
    print(' | '.join(v[1] for v in VARIANTS))
