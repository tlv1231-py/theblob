"""
ART STYLE mockups. Same tech spec in every cell -- 48x48, alpha 0 or 255, the
10 locked colours and nothing else, transparent bg, upper-left key, always pink.
Only the RENDERING changes.

This is the range question: BLOB.md fixes Bayer stipple as the look, but ordered
dither is just one way to get from a lit sphere to indexed colour. Cel, hatch,
halftone, scanline and 1-bit all satisfy the same constraints and read nothing
alike.

    python scripts/blob_styles.py <outdir>
"""

import math
import sys
import numpy as np
from PIL import Image
from pathlib import Path

CELL = 48
CX, CY, R = 24.5, 25.5, 13.0
FX, FY = 24, 23
LX, LY, LZ = -0.55, -0.68, 0.48

P = {'OUT': (0x2A, 0x00, 0x3D), 'LO': (0x8A, 0x00, 0x6C), 'MID': (0xFF, 0x00, 0xCC),
     'HI': (0xFF, 0x6E, 0xE2), 'SPEC': (0xFF, 0xC8, 0xF8), 'EYE': (0x0A, 0x00, 0x10),
     'GRN': (0x00, 0xFF, 0x9D), 'RED': (0xFF, 0x33, 0x66), 'CYN': (0x00, 0xE5, 0xFF),
     'WHT': (0xFF, 0xFF, 0xFF)}
RAMP = [P['OUT'], P['LO'], P['MID'], P['HI'], P['SPEC']]
BAYER = [v / 16 - 0.5 for v in [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]]
HARM = [(3, 0.055, 0.0), (5, 0.038, 0.0), (2, 0.026, 0.0)]


def jr(v):
    return math.floor(v + 0.5)


def geom(x, y):
    """-> (inside, on_outline, lam, nd) for the shared silhouette."""
    dx, dy = x + 0.5 - CX, y + 0.5 - CY
    d = math.hypot(dx, dy) or 1e-6
    th = math.atan2(dy, dx)
    r = R * (1 + sum(a * math.sin(f * th + p) for f, a, p in HARM))
    if d > r:
        return False, False, 0, 0
    nd = d / r
    nz = math.sqrt(max(0.0, 1 - nd * nd))
    lam = (dx / r) * LX + (dy / r) * LY + nz * LZ
    return True, d > r - 1.15, lam, nd


def val(lam):
    lw = lam * 0.20 + 0.80 * (lam * 0.5 + 0.5)
    return max(0.0, min(1.0, lw * 0.65 + 0.16))


# ── One shading rule per style. Returns a palette colour. ─────────────────────

def s_bayer(x, y, lam, nd):
    v, b = val(lam), BAYER[(y % 4) * 4 + (x % 4)]
    i = max(1, min(4, jr(v * 4 + b * 1.05)))
    if max(0.0, lam) ** 6 > 0.50 + b * 0.30:
        i = 4
    return RAMP[i]


def s_cel(x, y, lam, nd):
    v = val(lam)
    i = 1 if v < 0.38 else (2 if v < 0.60 else (3 if v < 0.80 else 4))
    return RAMP[i]


def s_hatch(x, y, lam, nd):
    v, i = val(lam), 2
    if v < 0.58 and (x + y) % 4 == 0:
        i = 1
    if v < 0.40 and (x + y) % 2 == 0:
        i = 1
    if v < 0.24:
        i = 1
    if v > 0.66 and (x - y) % 4 == 0:
        i = 3
    if v > 0.80 and (x - y) % 2 == 0:
        i = 3
    if v > 0.92:
        i = 4
    return RAMP[i]


def s_halftone(x, y, lam, nd):
    # Dot grid: cell darkness -> dot radius. Comic print, not stipple.
    cx4, cy4 = (x // 4) * 4 + 1.5, (y // 4) * 4 + 1.5
    ok, _, clam, _ = geom(int(cx4), int(cy4))
    v = val(clam if ok else lam)
    dist = math.hypot(x + 0.5 - (cx4 + 0.5), y + 0.5 - (cy4 + 0.5))
    if v < 0.56 and dist < (0.56 - v) * 9.5:
        return RAMP[1]
    if v > 0.60 and dist < (v - 0.60) * 9.5:
        return RAMP[4]
    return RAMP[2]


def s_scan(x, y, lam, nd):
    v = val(lam)
    i = max(1, min(4, jr(v * 4)))
    if y % 2:
        i = max(1, i - 1)          # CRT interlace
    return RAMP[i]


def s_1bit(x, y, lam, nd):
    v, b = val(lam), BAYER[(y % 4) * 4 + (x % 4)]
    return P['MID'] if v + b * 0.95 > 0.46 else P['OUT']


def s_sticker(x, y, lam, nd):
    if lam > 0.74:
        return P['SPEC']
    if lam < 0.16:
        return P['LO']
    return P['MID']


def s_rim(x, y, lam, nd):
    # Noir: body sits in shadow, light only wraps the edge.
    b = BAYER[(y % 4) * 4 + (x % 4)]
    edge = nd ** 3.0
    if lam > 0.30 and edge > 0.42 + b * 0.30:
        return P['SPEC'] if lam > 0.72 else P['HI']
    if lam < -0.05 and edge > 0.55 + b * 0.30:
        return P['CYN']
    return P['LO'] if val(lam) > 0.34 + b * 0.5 else P['OUT']


def s_noise(x, y, lam, nd):
    # Random stipple instead of ordered -- organic grain, no lattice.
    v = val(lam)
    h = math.sin(x * 12.9898 + y * 78.233) * 43758.5453
    n = (h - math.floor(h)) - 0.5
    return RAMP[max(1, min(4, jr(v * 4 + n * 1.5)))]


STYLES = [
    ('bayer',    'Bayer stipple',  'What BLOB.md specifies. Ordered 4x4 lattice.', s_bayer,   False),
    ('cel',      'Hard cel',       'No dither. Flat bands, crisp terminator.',     s_cel,     False),
    ('hatch',    'Cross-hatch',    'Etched diagonals instead of a dot lattice.',   s_hatch,   False),
    ('halftone', 'Halftone',       'Comic print. Dot size carries the value.',     s_halftone, False),
    ('scan',     'CRT scanline',   'Interlaced rows. Arcade monitor.',             s_scan,    False),
    ('onebit',   '1-bit',          'Two colours total. Pure pattern dither.',      s_1bit,    False),
    ('sticker',  'Sticker',        'Flat fill, hard highlight. Vector-ish.',       s_sticker, False),
    ('rim',      'Rim-lit noir',   'Body in shadow, light only on the edge.',      s_rim,     False),
    ('noise',    'Noise stipple',  'Random grain. No lattice, more organic.',      s_noise,   False),
    ('chunky',   'Half-res chunk', '24x24 logical, doubled. Fewer, bigger pixels.', s_bayer,  True),
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


def face(c, style):
    # 1-bit has only MID and OUT, so the face ink must be OUT -- drawn in MID it
    # is the same colour as the body and the eyes simply disappear. Solid OUT
    # against a scattered OUT dither still reads, which is the whole 1-bit trick.
    ink = P['OUT'] if style == 'onebit' else P['EYE']
    c.rows([(FY + 8, 22, 26)], ink)                            # neutral mouth
    for dx in (0, 10):
        c.rows([(FY - 1, 18 + dx, 20 + dx)]
               + [(y, 17 + dx, 21 + dx) for y in (FY, FY + 1, FY + 2)]
               + [(FY + 3, 18 + dx, 20 + dx)], ink)
        if style != 'onebit':
            c.px(18 + dx, FY, P['WHT'])
            c.px(20 + dx, FY + 2, P['HI'])
    for i in range(5):                                         # flat brows
        c.rect(FX - 7 + i, FY - 4, 1, 1, ink)
        c.rect(48 - (FX - 7 + i), FY - 4, 1, 1, ink)


def render(key, fn, chunk):
    c = C()
    ol = P['MID'] if key == 'onebit' else P['OUT']
    for y in range(CELL):
        for x in range(CELL):
            inside, edge, lam, nd = geom(x, y)
            if not inside:
                continue
            if edge and key not in ('rim', 'onebit'):
                c.px(x, y, P['OUT'] if key != 'sticker' else P['OUT'])
                continue
            if edge and key == 'onebit':
                c.px(x, y, P['OUT'])
                continue
            c.px(x, y, fn(x, y, lam, nd))
    if key == 'sticker':                                       # 2px outline
        for y in range(CELL):
            for x in range(CELL):
                inside, _, _, _ = geom(x, y)
                if inside:
                    ins2, _, _, _ = geom(x, y)
                    dx, dy = x + 0.5 - CX, y + 0.5 - CY
                    d = math.hypot(dx, dy) or 1e-6
                    th = math.atan2(dy, dx)
                    r = R * (1 + sum(a * math.sin(f * th + p) for f, a, p in HARM))
                    if d > r - 2.3:
                        c.px(x, y, P['OUT'])
    face(c, key)
    a = c.a
    if chunk:
        a = a[::2, ::2].repeat(2, 0).repeat(2, 1)              # nearest, palette-safe
    return a


if __name__ == '__main__':
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for k, n, d, fn, ch in STYLES:
        Image.fromarray(render(k, fn, ch), 'RGBA').save(out / f'{k}.png')
        print(f'{k:9} {n}')
