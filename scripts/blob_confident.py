"""
Confident-face design bench. Iterate on ONE expression with the operator, then
promote it as the reference for the rest of the moods.

Reuses gen_blobby_ref's body + shading; only the face (eyes/brows/mouth/arm)
changes per take. Renders big on the vaporwave backdrop.

    python scripts/blob_confident.py <outdir>
"""

import sys
import numpy as np
from PIL import Image
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_blobby_ref as G

P = G.P


def half_eye(st, cx, cy, r, lidFrac, pupDx, pupDy):
    """A half-lidded white eye: flat lid on top, round below, dark lash line,
    forward pupil + upper-left glint. This is the 'cool/confident' eye."""
    top = cy - r + int(2 * r * lidFrac)           # where the lid cuts the disc
    # dark backing = outline
    for yy in range(top - 1, int(cy + r + 1)):
        dh = r * r - (yy - cy) ** 2
        if dh < 0:
            continue
        half = int(dh ** 0.5)
        st.rows([(yy, cx - half - 1, cx + half + 1)], P['OUT'], force=True)
    # white eyeball below the lid
    for yy in range(top, int(cy + r + 1)):
        dh = r * r - (yy - cy) ** 2
        if dh < 0:
            continue
        half = int(dh ** 0.5)
        st.rows([(yy, cx - half, cx + half)], P['WHT'], force=True)
    st.rows([(top - 1, cx - r, cx + r)], P['EYE'], force=True)     # lash line
    st.disc(cx + pupDx, cy + pupDy, 2.2, P['EYE'], force=True)     # pupil
    st.pxf(cx + pupDx - 1, cy + pupDy - 1, P['WHT'])               # glint


def full_eye(st, cx, cy, r, pupDx, pupDy):
    st.disc(cx, cy, r + 1.1, P['OUT'], force=True)
    st.disc(cx, cy, r, P['WHT'], force=True)
    st.disc(cx + pupDx, cy + pupDy, 2.4, P['EYE'], force=True)
    st.pxf(cx + pupDx - 1, cy + pupDy - 1, P['WHT'])
    st.pxf(cx + pupDx + 1, cy + pupDy + 1, P['HI'])


def arm_point(st):
    G.limb(st, [(35, 22), (37, 19), (39, 16), (40, 13), (40, 11)], 2.2)
    st.disc(40, 10, 2.4, P['MID'], force=True)
    st.rows([(8, 40, 40), (7, 40, 40)], P['MID'], force=True)
    st.pxf(40, 6, P['OUT']); st.pxf(40, 9, P['OUT'])


# ── Take A — COOL: half-lidded, easy closed smile, level brows, pointing. ────
def take_cool(st):
    st.rows([(11, 15, 20), (11, 28, 33)], P['EYE'])               # level brows
    half_eye(st, 19, 20, 5, 0.42, 0, 2)
    half_eye(st, 29, 20, 5, 0.42, 0, 2)
    # easy confident smile — a shallow upward arc, no tongue
    st.rows([(32, 20, 20), (32, 28, 28), (33, 21, 27), (34, 23, 25)], P['EYE'])
    arm_point(st)


# ── Take B — COCKY: open fanged grin, brows up, pointing. Showman. ───────────
def take_cocky(st):
    st.rows([(10, 15, 19), (10, 29, 33)], P['EYE'])               # raised brows
    full_eye(st, 19, 19, 5, 1, 0)
    full_eye(st, 29, 19, 5, -1, 0)
    # wide grin with fangs, corners up
    for yy, x0, x1 in [(30, 19, 29), (31, 18, 30), (32, 19, 29), (33, 21, 27)]:
        st.rows([(yy, x0, x1)], P['EYE'])
    for fx in (20, 24, 28):
        st.rows([(30, fx, fx + 1), (31, fx, fx)], P['WHT'])
    arm_point(st)


# ── Take C — FOCUSED: narrowed steady eyes, firm small grin, low level brows. ─
def take_focused(st):
    st.rows([(12, 15, 20), (12, 28, 33), (13, 19, 20), (13, 28, 29)], P['EYE'])  # low, slight inward
    half_eye(st, 19, 20, 5, 0.55, 0, 1)
    half_eye(st, 29, 20, 5, 0.55, 0, 1)
    st.rows([(33, 20, 28), (32, 20, 20), (32, 28, 28)], P['EYE'])  # firm flat-ish grin
    G.limb(st, [(36, 24), (39, 24), (41, 23)], 2.0)               # arm on hip-ish nub


TAKES = [('cool', 'A · Cool', take_cool),
         ('cocky', 'B · Cocky', take_cocky),
         ('focused', 'C · Focused', take_focused)]


def render(fn):
    a, sx, sy, R = G.body_cell('IDLE', 0)
    st = G.Stamp(a)
    G.draw_gloss(st, 'IDLE')
    fn(st)
    return a


if __name__ == '__main__':
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    Z = 10
    strip = Image.new('RGBA', (48 * len(TAKES), 48), (0, 0, 0, 0))
    for i, (k, n, fn) in enumerate(TAKES):
        im = Image.fromarray(render(fn), 'RGBA')
        im.save(out / (k + '.png'))
        strip.paste(im, (i * 48, 0), im)
    bg = Image.new('RGBA', strip.size, (30, 8, 52, 255))
    bg.alpha_composite(strip)
    bg.resize((strip.width * Z, strip.height * Z), Image.NEAREST).save(out / 'confident_strip.png')
    print(' | '.join(t[1] for t in TAKES))
