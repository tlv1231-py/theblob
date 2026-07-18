"""
Blobby — EYES-ONLY redesign, all 7 moods. Small pink circle + cartoonishly
large, over-the-top expressive eyes, one tasteful line mouth. No arm, no fangs,
no tongue, no brows, no particles. The eyes do ALL the expressing.

IDLE is the CONFIDENT DUMB GUY (take A the operator picked): half-lidded, pupils
slightly wall-eyed, a little curled smile. That is the default face.

Sheets keep the contract so blob.js consumes them unchanged:
  blob_body.png 192x336  4 breath cols x 7 mood rows   circle + mouth
  blob_eyes.png 144x336  3 lid   cols x 7 mood rows     eyes + glints

    python scripts/gen_blobby_eyes.py          # write the two sheets
    python scripts/gen_blobby_eyes.py contact  # 7-mood contact to scratch arg2
"""

import math
import sys
import numpy as np
from PIL import Image
from pathlib import Path

CELL = 48
LX, LY, LZ = -0.55, -0.68, 0.48
ROWS = ['IDLE', 'HAPPY', 'SCARED', 'ALERT', 'SLEEP', 'SMUG', 'BRACE', 'EXASPERATED', 'HOPEFUL']
OUT_DIR = Path(__file__).resolve().parents[1] / 'dashboard'

P = {'OUT': (0x2A, 0x00, 0x3D), 'LO': (0x8A, 0x00, 0x6C), 'MID': (0xFF, 0x00, 0xCC),
     'HI': (0xFF, 0x6E, 0xE2), 'SPEC': (0xFF, 0xC8, 0xF8), 'EYE': (0x0A, 0x00, 0x10),
     'WHT': (0xFF, 0xFF, 0xFF)}
RAMP = [P['OUT'], P['LO'], P['MID'], P['HI'], P['SPEC']]

CIRC = (24, 29, 14)                 # cx, cy, R  (take A's small circle)
EYE_L, EYE_R, EYE_Y = 17, 31, 23    # eye centres


class Buf:
    def __init__(self):
        self.a = np.zeros((CELL, CELL, 4), np.uint8)

    def set(self, x, y, c):
        x = int(x); y = int(y)
        if 0 <= x < CELL and 0 <= y < CELL:
            self.a[y, x] = (*c, 255)

    def get(self, x, y):
        x = int(x); y = int(y)
        if 0 <= x < CELL and 0 <= y < CELL and self.a[y, x, 3] == 255:
            return tuple(int(v) for v in self.a[y, x][:3])
        return None

    def disc(self, cx, cy, r, c):
        for y in range(int(cy - r - 1), int(cy + r + 2)):
            for x in range(int(cx - r - 1), int(cx + r + 2)):
                if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r:
                    self.set(x, y, c)

    def ellipse(self, cx, cy, rx, ry, c, only=None):
        for y in range(int(cy - ry - 1), int(cy + ry + 2)):
            for x in range(int(cx - rx - 1), int(cx + rx + 2)):
                if ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2 <= 1:
                    if only is not None and self.get(x, y) != only:
                        continue
                    self.set(x, y, c)


def body(st, dR, dim=0):
    cx, cy, R = CIRC[0], CIRC[1], CIRC[2] + dR
    for y in range(CELL):
        for x in range(CELL):
            dx, dy = x + 0.5 - cx, y + 0.5 - cy
            d = math.hypot(dx, dy)
            if d > R:
                continue
            if d > R - 1.4:
                st.set(x, y, P['OUT'])
                continue
            nd = d / r if (r := R) else 1
            nz = math.sqrt(max(0.0, 1 - nd * nd))
            lam = (dx / R) * LX + (dy / R) * LY + nz * LZ
            lw = lam * 0.20 + 0.80 * (lam * 0.5 + 0.5)
            v = max(0.0, min(1.0, lw * 0.65 + 0.16))
            i = 1 if v < 0.30 else (2 if v < 0.62 else (3 if v < 0.90 else 4))
            if dim:
                i = max(1, i - dim)
            st.set(x, y, RAMP[i])
    if not dim:
        st.disc(18, cy + 6, 2.0, P['SPEC'])   # gloss


def draw_mullet(st):
    """A big 80s mullet — dark, voluminous hair BEHIND the circle: a poof up top,
    long locks flaring down the back, feathered pink highlight streaks for the
    rich sheen. Drawn before the body so the pink face sits in front of it."""
    cx, cy, R = CIRC
    HAIR = P['EYE']

    def hw(y):                          # hair half-width per row (from centre)
        if y < 16:                      # a rounded 80s DOME — big volume up top
            return 5 + 15 * math.sin(y / 16.0 * math.pi * 0.9)
        if y < 32:                      # SHORT business sides — hug the head
            return math.sqrt(max(0.0, R * R - (y - cy) ** 2)) + 2.0
        return 15 + (y - 32) * 0.95     # the TAIL — full length flaring out the back

    FEATHER = [0, 1, 1, 0, -1, 1]       # gentle jagged edge so it reads as hair
    for y in range(0, 48):
        w = hw(y) + FEATHER[y % 6]
        for x in range(int(round(cx - w)), int(round(cx + w)) + 1):
            st.set(x, y, HAIR)

    # Sheen: BROAD feathered locks (2px) through the poof and the tail — volume,
    # not stringy drips, and no straight crown line (that read as a hat brim).
    locks = [(cx - 11, 4, 15), (cx + 10, 4, 15),
             (cx - 15, 33, 47), (cx - 9, 35, 47), (cx + 9, 35, 47), (cx + 15, 33, 47)]
    for base, y0, y1 in locks:
        for y in range(y0, y1):
            x = int(round(base + math.sin(y * 0.5) * 1.4))
            if st.get(x, y) == HAIR:
                st.set(x, y, P['HI'])
            if st.get(x + 1, y) == HAIR:
                st.set(x + 1, y, P['HI'])
    for (x, y) in [(cx - 3, 2), (cx + 3, 2), (cx - 16, 44), (cx + 16, 44)]:
        if st.get(x, y) is not None:
            st.set(x, y, P['SPEC'])


# ── Eye specs per mood. Everything dialled up. ───────────────────────────────
# lidT/lidB: fraction of the eye covered from top / bottom (a curved lid).
# div: pupils pushed outward (wall-eye). gaze: both pupils shift together.
# glint: 'key' | 'sparkle' | 'none'.  shape: 'round' | 'closed'.
E = {
    'IDLE':   dict(rx=7, ry=8, lidT=0.34, curve=0.10, pupR=3.0, div=1.6, pupDy=2, glint='key'),
    # HAPPY — huge, wide, sparkling, pupils blown, looking up. Pure joy.
    'HAPPY':  dict(rx=8, ry=9, lidT=0.0,  curve=0.0,  pupR=3.8, div=0.0, pupDy=-1, glint='sparkle'),
    # SCARED — bulging eyes, pinprick pupils adrift in white. Terror.
    'SCARED': dict(rx=9, ry=9, lidT=0.0,  curve=0.0,  pupR=1.1, div=1.4, pupDy=-1, glint='none'),
    # ALERT — wide and locked on, big sharp pupils dead centre.
    'ALERT':  dict(rx=8, ry=9, lidT=0.04, curve=0.0,  pupR=2.6, div=0.0, pupDy=0, glint='key'),
    'SLEEP':  dict(shape='closed'),
    # SMUG — heavy lids, side-eye hard to one side. Insufferable.
    'SMUG':   dict(rx=7, ry=7, lidT=0.52, curve=-0.06, pupR=2.8, div=0.0, gaze=2.6, pupDy=1, glint='key'),
    # BRACE — clamped squint, intense pupils. Focus, not fear.
    'BRACE':  dict(rx=8, ry=6, lidT=0.30, lidB=0.30, curve=0.0, pupR=2.6, div=0.0, pupDy=0, glint='key'),
    # EXASPERATED — a loss just landed. Heavy lids, pupils rolled UP against the
    # lid with a crescent of white below: the classic "ugh, again" eye-roll.
    'EXASPERATED': dict(rx=7, ry=8, lidT=0.40, curve=0.0, pupR=2.3, div=2.4, pupDy=-2, glint='none'),
    # HOPEFUL — a fresh pickup. He is looking UP at the tile he just bought,
    # wide-eyed and eager, sure it's a winner. Sparkle of optimism.
    'HOPEFUL': dict(rx=8, ry=9, lidT=0.0, curve=0.0, pupR=2.8, div=0.0, pupDy=-3, glint='sparkle'),
}


def draw_eye(st, cx, cy, s, side, lidAdd):
    rx, ry = s['rx'], s['ry']
    lidT = min(0.96, s.get('lidT', 0) + lidAdd)
    lidB = s.get('lidB', 0)
    curve = s.get('curve', 0)
    st.ellipse(cx, cy, rx + 1, ry + 1, P['OUT'])
    st.ellipse(cx, cy, rx, ry, P['WHT'])

    shut = lidT >= 0.9
    # Pupil + glints go down FIRST, so a lowered lid OCCLUDES a rolled-up pupil
    # rather than the pupil painting over the eyelid — that was the "his pupils
    # go through his eyelids" bug on EXASPERATED and any looking-up eye.
    if not shut:
        px = cx + side * s.get('div', 0) + s.get('gaze', 0)
        py = cy + s.get('pupDy', 0)
        st.disc(px, py, s['pupR'], P['EYE'])
        g = s.get('glint', 'key')
        if g != 'none':
            st.disc(px - s['pupR'] * 0.45, py - s['pupR'] * 0.5, max(1.3, s['pupR'] * 0.42), P['WHT'])
            st.set(px + s['pupR'] * 0.5, py + s['pupR'] * 0.5, P['HI'])
        if g == 'sparkle':
            st.disc(px + s['pupR'] * 0.55, py - s['pupR'] * 0.2, 1.4, P['WHT'])   # second sparkle

    EYEINT = (P['WHT'], P['EYE'], P['HI'])   # eye-interior colours the lid covers
    # top lid — repaints the interior (white, pupil, glint) above the lash line
    if lidT > 0:
        base = cy - ry + 2 * ry * lidT
        for x in range(int(cx - rx - 1), int(cx + rx + 2)):
            u = (x - cx) / rx
            lb = base + curve * (u * u) * ry
            for y in range(int(cy - ry - 1), int(lb) + 1):
                if st.get(x, y) in EYEINT:
                    st.set(x, y, P['MID'])
            if st.get(x, int(round(lb))) in (P['MID'],) + EYEINT:
                st.set(x, int(round(lb)), P['EYE'])
    # bottom lid (squint)
    if lidB > 0:
        base = cy + ry - 2 * ry * lidB
        for x in range(int(cx - rx - 1), int(cx + rx + 2)):
            for y in range(int(base), int(cy + ry + 2)):
                if st.get(x, y) in EYEINT:
                    st.set(x, y, P['MID'])
            if st.get(x, int(round(base))) in (P['MID'],) + EYEINT:
                st.set(x, int(round(base)), P['EYE'])


def closed_eye(st, cx, cy, droop=False):
    """Fully-blinked eye (a calm lash arc). droop=True for SLEEP: a heavier,
    lower, sadder-sweeter downward curve that clearly reads as asleep."""
    rx = 6
    amp = 3 if droop else 2
    for x in range(cx - rx, cx + rx + 1):
        u = (x - cx) / rx
        y = cy + int(round((1 - u * u) * amp)) - (1 if droop else 0)
        st.set(x, y, P['EYE'])
        st.set(x, y + 1, P['EYE'])
        if droop:
            st.set(x, y + 2, P['EYE'])


def draw_mouth(st, mood):
    E_ = P['EYE']
    cx = 24
    if mood == 'HAPPY':                       # wider curled smile
        for x in range(cx - 4, cx + 5):
            st.set(x, 36, E_)
        st.set(cx - 5, 35, E_); st.set(cx + 5, 35, E_)
        st.set(cx - 6, 34, E_); st.set(cx + 6, 34, E_)
    elif mood in ('IDLE',):                   # little confident-dumb smile
        for x in range(cx - 3, cx + 4):
            st.set(x, 36, E_)
        st.set(cx - 4, 35, E_); st.set(cx + 4, 35, E_)
    elif mood == 'SMUG':                       # smirk — one end up
        for x in range(cx - 3, cx + 3):
            st.set(x, 36, E_)
        st.set(cx + 3, 35, E_); st.set(cx + 4, 34, E_)
    elif mood == 'SCARED':                     # small worried gap
        for x in range(cx - 2, cx + 3):
            st.set(x, 37, E_)
    elif mood == 'EXASPERATED':                # flat, corners dipped — unimpressed
        for x in range(cx - 3, cx + 4):
            st.set(x, 36, E_)
        st.set(cx - 4, 37, E_); st.set(cx + 4, 37, E_)
    elif mood == 'SLEEP':                      # tiny
        for x in range(cx - 1, cx + 2):
            st.set(x, 36, E_)
    elif mood == 'HOPEFUL':                    # small eager open smile
        for x in range(cx - 2, cx + 3):
            st.set(x, 36, E_)
        st.set(cx - 3, 35, E_); st.set(cx + 3, 35, E_)
    else:                                      # ALERT / BRACE — flat tight line
        for x in range(cx - 3, cx + 4):
            st.set(x, 36, E_)


BREATH_dR = [0, 0.5, 0, -0.5]


def body_cell(mood, col):
    st = Buf()
    draw_mullet(st)                                          # 80s hair, behind him
    body(st, BREATH_dR[col], dim=1 if mood == 'SLEEP' else 0)
    draw_mouth(st, mood)
    return st.a


def eyes_cell(mood, lid):
    st = Buf()
    if mood == 'SLEEP' or lid == 2:
        droop = mood == 'SLEEP'
        closed_eye(st, EYE_L, EYE_Y + (1 if droop else 0), droop)
        closed_eye(st, EYE_R, EYE_Y + (1 if droop else 0), droop)
        return st.a
    s = E[mood]
    lidAdd = 0.0 if lid == 0 else 0.34
    draw_eye(st, EYE_L, EYE_Y, s, -1, lidAdd)
    draw_eye(st, EYE_R, EYE_Y, s, +1, lidAdd)
    return st.a


def build():
    body_sh = np.zeros((CELL * len(ROWS), CELL * 4, 4), np.uint8)
    eyes_sh = np.zeros((CELL * len(ROWS), CELL * 3, 4), np.uint8)
    for r, m in enumerate(ROWS):
        for c in range(4):
            body_sh[r * CELL:(r + 1) * CELL, c * CELL:(c + 1) * CELL] = body_cell(m, c)
        for c in range(3):
            eyes_sh[r * CELL:(r + 1) * CELL, c * CELL:(c + 1) * CELL] = eyes_cell(m, c)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    Image.fromarray(body_sh, 'RGBA').save(OUT_DIR / 'blob_body.png')
    Image.fromarray(eyes_sh, 'RGBA').save(OUT_DIR / 'blob_eyes.png')
    print(f'blob_body.png {body_sh.shape[1]}x{body_sh.shape[0]}')
    print(f'blob_eyes.png {eyes_sh.shape[1]}x{eyes_sh.shape[0]}')


def contact(path):
    Z = 8
    out = np.zeros((CELL, CELL * len(ROWS), 4), np.uint8)
    for i, m in enumerate(ROWS):
        b = body_cell(m, 0).copy()
        e = eyes_cell(m, 0)
        mask = e[..., 3] == 255
        b[mask] = e[mask]
        out[:, i * CELL:(i + 1) * CELL] = b
    im = Image.fromarray(out, 'RGBA')
    bg = Image.new('RGBA', im.size, (30, 8, 52, 255)); bg.alpha_composite(im)
    bg.resize((im.width * Z, im.height * Z), Image.NEAREST).save(path)
    print(path)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'contact':
        contact(sys.argv[2])
    else:
        build()
