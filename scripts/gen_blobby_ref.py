"""
Blobby REDESIGN to match the goofy-slime reference: googly eyes with big glints,
fanged grin, lolling tongue, lumpy glossy pink slime.

Keeps the sheet CONTRACT so it drops into blob.js unchanged:
  blob_body.png  192x336  4 breath cols x 7 mood rows   body+brows+mouth+fangs+tongue+arm
  blob_eyes.png  144x336  3 lid   cols x 7 mood rows     the big googly eyes + glints
  centre pixel (24,25); eyes overlay body with no offset; rows indexed by mood.

DELIBERATE DEVIATION FROM BLOB.md: shading is CEL + hand-placed gloss, not Bayer
dither. The reference is flat cartoon cells with glossy shine spots; dither would
fight that. Driven by the reference art direction, which supersedes the stipple
rule for this look. Still: 10-colour palette, alpha 0/255, no AA, always pink.

    python scripts/gen_blobby_ref.py            # writes the two sheets
    python scripts/gen_blobby_ref.py contact    # 7-mood contact PNG to scratch
"""

import math
import sys
import numpy as np
from PIL import Image
from pathlib import Path

CELL = 48
CX, CY = 24.5, 25.5
LX, LY, LZ = -0.55, -0.68, 0.48
ROWS = ['IDLE', 'HAPPY', 'SCARED', 'ALERT', 'SLEEP', 'SMUG', 'BRACE']
OUT_DIR = Path(__file__).resolve().parents[1] / 'dashboard'

P = {'OUT': (0x2A, 0x00, 0x3D), 'LO': (0x8A, 0x00, 0x6C), 'MID': (0xFF, 0x00, 0xCC),
     'HI': (0xFF, 0x6E, 0xE2), 'SPEC': (0xFF, 0xC8, 0xF8), 'EYE': (0x0A, 0x00, 0x10),
     'GRN': (0x00, 0xFF, 0x9D), 'RED': (0xFF, 0x33, 0x66), 'CYN': (0x00, 0xE5, 0xFF),
     'WHT': (0xFF, 0xFF, 0xFF)}


def jr(v):
    return math.floor(v + 0.5)


# Per-mood body deformation + phase (frozen across breath frames, no drift).
SHAPE = {
    'IDLE':   dict(sx=1.00, sy=1.00, dr=0.0, dim=0, ph=0.0),
    'HAPPY':  dict(sx=0.98, sy=1.06, dr=0.0, dim=0, ph=0.9),
    'SCARED': dict(sx=1.12, sy=0.90, dr=0.0, dim=0, ph=3.3),
    'ALERT':  dict(sx=1.00, sy=1.02, dr=0.4, dim=0, ph=2.7),
    'SLEEP':  dict(sx=1.10, sy=0.86, dr=-0.4, dim=1, ph=3.6),
    'SMUG':   dict(sx=1.05, sy=0.97, dr=0.0, dim=0, ph=4.5),
    'BRACE':  dict(sx=1.09, sy=0.90, dr=-0.4, dim=0, ph=5.4),
}
BASE_R = 12.4
BREATHE = 0.045


def body_cell(mood, frame):
    """Lumpy pear-slime silhouette, cel-shaded, wider at the bottom. Returns a
    48x48x4 uint8 buffer with body+outline only; face is stamped after."""
    s = SHAPE[mood]
    br = math.sin(frame * math.pi / 2) * BREATHE
    sx = s['sx'] + br * 0.5
    sy = s['sy'] + br
    R = BASE_R + s['dr']
    a = np.zeros((CELL, CELL, 4), np.uint8)
    for y in range(CELL):
        for x in range(CELL):
            dx = (x + 0.5 - CX)
            dy = (y + 0.5 - CY)
            ry = R * sy
            u = dy / ry
            if u < -1.02 or u > 1.16:
                continue
            th = math.atan2(dy, dx)
            uc = max(-1.0, min(1.0, u))
            base = math.sqrt(max(0.0, 1 - uc * uc))
            widen = 1 + 0.14 * uc                    # bottom heavier -> puddle
            lump = (1 + 0.060 * math.sin(3 * th + s['ph'] * 1.1)
                      + 0.040 * math.sin(5 * th - s['ph'] * 0.8)
                      + 0.028 * math.sin(2 * th + s['ph'] * 0.55))
            hw = R * sx * base * widen * lump
            # a couple of bottom drip lobes
            if u > 0.55:
                hw += 0.9 * max(0.0, math.sin(6 * th)) * (u - 0.55) * 3
            if abs(dx) > hw:
                continue
            # shading value from a fake sphere normal on the pear metric
            nxn = dx / (R * sx + 1e-6)
            nyn = dy / ry
            nd = min(1.0, math.hypot(nxn, nyn))
            nz = math.sqrt(max(0.0, 1 - nd * nd))
            lam = nxn * LX + nyn * LY + nz * LZ
            # outline: near the horizontal edge or the vertical extremes
            edge_x = hw - abs(dx)
            edge_y = (1.0 - abs(uc)) * ry
            if edge_x < 1.5 or edge_y < 1.4:
                a[y, x] = (*P['OUT'], 255)
                continue
            v = lam - s['dim'] * 0.5
            if v < -0.15:
                c = P['LO']
            elif v < 0.50:
                c = P['MID']
            elif v < 0.90:
                c = P['HI']
            else:
                c = P['SPEC']
            a[y, x] = (*c, 255)
    return a, sx, sy, R


class Stamp:
    def __init__(self, a):
        self.a = a

    def px(self, x, y, c):
        if 0 <= x < CELL and 0 <= y < CELL and self.a[y, x, 3] == 255:
            self.a[y, x] = (*c, 255)   # only draw ON the body (keeps him solid)

    def pxf(self, x, y, c):            # force (for arm/tongue that extend past body)
        if 0 <= x < CELL and 0 <= y < CELL:
            self.a[y, x] = (*c, 255)

    def rows(self, sp, c, force=False):
        f = self.pxf if force else self.px
        for y, x0, x1 in sp:
            for x in range(x0, x1 + 1):
                f(x, y, c)

    def disc(self, cx, cy, r, c, force=False):
        f = self.pxf if force else self.px
        for y in range(int(cy - r - 1), int(cy + r + 2)):
            for x in range(int(cx - r - 1), int(cx + r + 2)):
                if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r:
                    f(x, y, c)


# ── Gloss: the reference's shine spots. SPEC blobs, hand-placed. ──────────────
GLOSS = {
    'IDLE':   [(18, 33, 2.4), (31, 30, 1.6)],
    'HAPPY':  [(18, 32, 2.4), (31, 29, 1.6)],
    'SCARED': [(17, 33, 2.0), (32, 31, 1.4)],
    'ALERT':  [(18, 33, 2.2), (31, 30, 1.6)],
    'SLEEP':  [(19, 34, 1.8)],
    'SMUG':   [(18, 33, 2.2), (31, 30, 1.6)],
    'BRACE':  [(18, 34, 2.0), (31, 32, 1.4)],
}


def limb(st, path, r):
    """A connected limb: dark discs along the path first (outline), MID on top."""
    for (x, y) in path:
        st.disc(x, y, r + 1.0, P['OUT'], force=True)
    for (x, y) in path:
        st.disc(x, y, r, P['MID'], force=True)


def draw_arm(st, mood):
    """Raised 'pointing' arm for the confident moods, rooted IN the body so it
    reads as an arm and not a floating hook; a small resting nub otherwise."""
    up = mood in ('IDLE', 'HAPPY', 'ALERT', 'SMUG')
    if up:
        # shoulder (inside body) -> forearm -> fist, then a pointing finger
        limb(st, [(35, 22), (37, 19), (39, 16), (40, 13), (40, 11)], 2.2)
        st.disc(40, 10, 2.4, P['MID'], force=True)          # fist
        st.disc(40, 10, 2.4, P['MID'])
        st.pxf(40, 9, P['OUT']); st.pxf(41, 10, P['OUT'])
        st.rows([(8, 40, 40), (7, 40, 40)], P['MID'], force=True)  # finger up
        st.pxf(40, 6, P['OUT']); st.pxf(39, 7, P['OUT']); st.pxf(41, 7, P['OUT'])
        st.px(38, 13, P['HI'])                               # a little arm shine
    else:
        st.disc(40, 28, 2.6, P['OUT'], force=True)
        st.disc(40, 28, 2.0, P['MID'], force=True)


def draw_face(st, mood):
    """Brows, fanged grin, tongue. Eyes live on the other sheet."""
    E = P['EYE']
    # brows
    if mood == 'IDLE':
        st.rows([(12, 16, 19), (12, 29, 32)], E)
    elif mood == 'HAPPY':
        st.rows([(10, 15, 18), (10, 30, 33)], E)
    elif mood == 'SCARED':
        st.rows([(11, 16, 18), (10, 18, 19), (11, 30, 32), (10, 29, 30)], E)  # inner up
    elif mood == 'ALERT':
        st.rows([(10, 16, 20), (11, 16, 20), (10, 28, 32), (11, 28, 32)], E)  # thick straight
    elif mood == 'SMUG':
        st.rows([(13, 16, 19), (10, 29, 32)], E)                              # right lifts
    elif mood == 'BRACE':
        st.rows([(13, 16, 18), (12, 18, 20), (13, 30, 32), (12, 28, 30)], E)  # down+in

    # ── mouth ──
    if mood == 'SLEEP':
        st.rows([(33, 22, 26)], E)
        return
    if mood in ('SCARED', 'ALERT'):                     # small round 'o'
        st.disc(24, 33, 3.2, E)
        if mood == 'ALERT':
            st.disc(24, 34, 1.4, P['RED'])
        return
    if mood == 'BRACE':                                  # tight line
        st.rows([(33, 20, 28), (34, 21, 27)], E)
        return
    if mood == 'SMUG':                                   # one-sided smirk w/ fang + tongue
        st.rows([(31, 22, 30), (32, 23, 31), (33, 25, 31)], E)
        st.rows([(31, 24, 24), (31, 27, 27)], P['WHT'])  # two fangs
        st.disc(29, 34, 2.0, P['RED'], force=True)       # tongue tip out the side
        st.px(29, 33, P['SPEC'])
        return

    # IDLE / HAPPY — the signature fanged grin + lolling tongue
    big = mood == 'HAPPY'
    rx, ry = (10, 5) if big else (9, 4)
    st.disc(24, 32, 0, E)
    for yy in range(32 - ry, 32 + ry + 1):
        w = int(rx * math.sqrt(max(0.0, 1 - ((yy - 32) / ry) ** 2)))
        st.rows([(yy, 24 - w, 24 + w)], E)
    # fangs — white triangles from the top lip
    for fx in (17, 22, 27, 31):
        st.rows([(32 - ry + 1, fx, fx + 1), (32 - ry + 2, fx, fx + 1)], P['WHT'])
        st.px(fx, 32 - ry + 3, P['WHT'])
    # tongue — RED, lolling to the lower right and sticking out past the lip
    ty = 34 if big else 33
    st.disc(27, ty, 3.4 if big else 3.0, P['RED'], force=True)
    st.disc(28, ty + 3, 2.2 if big else 1.8, P['RED'], force=True)   # droop out the bottom
    st.px(26, ty - 1, P['SPEC'])
    st.rows([(ty, 27, 27)], P['LO'])                                  # centre crease


def draw_gloss(st, mood):
    for (gx, gy, gr) in GLOSS[mood]:
        st.disc(gx, gy, gr, P['SPEC'])


# ── Eyes sheet ────────────────────────────────────────────────────────────────
# Big googly eyes, close-set, black outline so they read on pink, SPEC eyeball,
# EYE pupil, WHT glint upper-left + small HI bounce lower-right. Lid: 0 open,
# 1 half, 2 shut; SLEEP shut in all three.
EYES = {
    'IDLE':   dict(r=5.0, lc=(19, 19), rc=(29, 19), pl=(20, 19), pr=(28, 19)),
    'HAPPY':  dict(r=5.2, lc=(19, 18), rc=(29, 18), pl=(20, 17), pr=(28, 17)),
    'SCARED': dict(r=5.6, lc=(19, 19), rc=(29, 19), pl=(19, 20), pr=(29, 20)),
    'ALERT':  dict(r=5.4, lc=(19, 18), rc=(29, 18), pl=(20, 17), pr=(28, 17)),
    'SMUG':   dict(r=5.0, lc=(19, 19), rc=(29, 19), pl=(21, 20), pr=(29, 20)),
    'BRACE':  dict(r=4.8, lc=(19, 20), rc=(29, 20), pl=(20, 20), pr=(28, 20)),
}


def eyes_cell(mood, lid):
    a = np.zeros((CELL, CELL, 4), np.uint8)
    st = Stamp(a)
    if mood == 'SLEEP' or lid == 2:
        # shut: a downward lash curve where each eye sits
        for (cx, cy) in ((19, 19), (29, 19)):
            st.rows([(cy, cx - 4, cx + 4), (cy + 1, cx - 3, cx - 2),
                     (cy + 1, cx + 2, cx + 3)], P['EYE'], force=True)
        return a
    e = EYES[mood]
    for side, (cx, cy), (px_, py_) in (('l', e['lc'], e['pl']), ('r', e['rc'], e['pr'])):
        r = e['r']
        yclip = cy + (r if lid == 0 else r * 0.1)       # half-lid hides the top
        st.disc(cx, cy, r + 1.2, P['OUT'], force=True)   # outline ring
        st.disc(cx, cy, r, P['WHT'], force=True)          # eyeball — pure white, like the ref
        st.disc(cx, cy + r * 0.55, r * 0.5, P['SPEC'], force=True)  # soft shade at the bottom
        # clip top for half-lid
        if lid == 1:
            for yy in range(0, int(cy)):
                hide = ((a[yy, :, :3] == P['WHT']).all(1) | (a[yy, :, :3] == P['SPEC']).all(1))
                a[yy, :] = np.where(hide[:, None], np.array([*P['OUT'], 255], np.uint8), a[yy, :])
        st.disc(px_, py_, 2.4, P['EYE'], force=True)      # pupil
        st.pxf(px_ - 1, py_ - 1, P['WHT'])                # key glint
        st.pxf(px_ + 1, py_ + 1, P['HI'])                 # bounce
        if lid == 1:                                       # lash line across
            st.rows([(int(cy), cx - 4, cx + 4)], P['EYE'], force=True)
    return a


def render_body(mood, frame):
    a, sx, sy, R = body_cell(mood, frame)
    st = Stamp(a)
    draw_gloss(st, mood)
    draw_arm(st, mood)
    draw_face(st, mood)
    return a


def build_sheets():
    body = np.zeros((CELL * 7, CELL * 4, 4), np.uint8)
    eyes = np.zeros((CELL * 7, CELL * 3, 4), np.uint8)
    for r, m in enumerate(ROWS):
        for c in range(4):
            body[r * CELL:(r + 1) * CELL, c * CELL:(c + 1) * CELL] = render_body(m, c)
        for c in range(3):
            eyes[r * CELL:(r + 1) * CELL, c * CELL:(c + 1) * CELL] = eyes_cell(m, c)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    Image.fromarray(body, 'RGBA').save(OUT_DIR / 'blob_body.png')
    Image.fromarray(eyes, 'RGBA').save(OUT_DIR / 'blob_eyes.png')
    print(f'blob_body.png {body.shape[1]}x{body.shape[0]}')
    print(f'blob_eyes.png {eyes.shape[1]}x{eyes.shape[0]}')


def contact(path):
    Z = 8
    out = np.zeros((CELL, CELL * 7, 4), np.uint8)
    for i, m in enumerate(ROWS):
        b = render_body(m, 0).copy()
        e = eyes_cell(m, 0)
        mask = e[..., 3] == 255
        b[mask] = e[mask]
        out[:, i * CELL:(i + 1) * CELL] = b
    im = Image.fromarray(out, 'RGBA')
    bg = Image.new('RGBA', im.size, (30, 8, 52, 255))
    bg.alpha_composite(im)
    bg.resize((im.width * Z, im.height * Z), Image.NEAREST).save(path)
    print(path)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'contact':
        contact(sys.argv[2])
    else:
        build_sheets()
