"""
Check the baked sheets against every acceptance criterion in the brief.
Exits non-zero on any failure.

    python scripts/verify_blob_sprites.py
"""

import sys
import numpy as np
from PIL import Image
from pathlib import Path

CELL = 48
ROWS = ['IDLE', 'HAPPY', 'SCARED', 'ALERT', 'SLEEP', 'SMUG', 'BRACE']
DIR = Path(__file__).resolve().parents[1] / 'dashboard'

PAL = {
    (0x2A, 0x00, 0x3D): 'OUT', (0x8A, 0x00, 0x6C): 'LO', (0xFF, 0x00, 0xCC): 'MID',
    (0xFF, 0x6E, 0xE2): 'HI',  (0xFF, 0xC8, 0xF8): 'SPEC', (0x0A, 0x00, 0x10): 'EYE',
    (0x00, 0xFF, 0x9D): 'GRN', (0xFF, 0x33, 0x66): 'RED', (0x00, 0xE5, 0xFF): 'CYN',
    (0xFF, 0xFF, 0xFF): 'WHT',
}

fails, notes = [], []


def check(cond, msg):
    (notes if cond else fails).append(('PASS' if cond else 'FAIL', msg))


def cell(sheet, r, c):
    return sheet[r * CELL:(r + 1) * CELL, c * CELL:(c + 1) * CELL]


body = np.array(Image.open(DIR / 'blob_body.png').convert('RGBA'))
eyes = np.array(Image.open(DIR / 'blob_eyes.png').convert('RGBA'))

# 1. Dimensions, no padding/gutters.
check(body.shape[:2] == (336, 192), f'blob_body.png is 192x336 (got {body.shape[1]}x{body.shape[0]})')
check(eyes.shape[:2] == (336, 144), f'blob_eyes.png is 144x336 (got {eyes.shape[1]}x{eyes.shape[0]})')

# 2. No anti-aliasing: alpha is 0 or 255, never between.
for nm, sh in (('body', body), ('eyes', eyes)):
    bad = np.unique(sh[..., 3][(sh[..., 3] != 0) & (sh[..., 3] != 255)])
    check(bad.size == 0, f'{nm}: no pixel has alpha 1..254 (offenders: {bad[:8]})')

# 3. Every opaque pixel is one of the 10 locked colours.
for nm, sh in (('body', body), ('eyes', eyes)):
    op = sh[sh[..., 3] == 255][:, :3]
    uniq = {tuple(int(v) for v in p) for p in np.unique(op, axis=0)}
    off = uniq - set(PAL)
    check(not off, f'{nm}: palette locked to the 10 ({len(uniq)} used, off-palette: '
                   f'{[f"#{r:02X}{g:02X}{b:02X}" for r, g, b in list(off)[:6]]})')

# 4. Registration: centre (24,25), span, margin, and no drift between frames.
#    NOTE: this deliberately does NOT test that the bbox is symmetric about 24.
#    The silhouette is asymmetric ON PURPOSE -- it is three sine harmonics
#    sampled against the grid, i.e. a lumpy egg, not a sphere. What must hold is
#    that the CENTRE is identical in every cell, which is a drift test.
for r, mood in enumerate(ROWS):
    coms, boxes = [], []
    for c in range(4):
        a = cell(body, r, c)
        ys, xs = np.where(a[..., 3] == 255)
        boxes.append((xs.min(), xs.max(), ys.min(), ys.max()))
        coms.append((xs.mean(), ys.mean()))
        check(xs.min() >= 3 and xs.max() <= 44 and ys.min() >= 3 and ys.max() <= 44,
              f'{mood} c{c}: >=3px margin (x{xs.min()}-{xs.max()} y{ys.min()}-{ys.max()})')
        check(7 <= xs.min() and xs.max() <= 41 and 8 <= ys.min() and ys.max() <= 42,
              f'{mood} c{c}: spans ~x8-40 / y9-41')
    # Centre of mass must sit on (24,25) and must not wander across the loop.
    cxs, cys = [p[0] for p in coms], [p[1] for p in coms]
    check(abs(np.mean(cxs) - 24) < 1.2 and abs(np.mean(cys) - 25) < 1.2,
          f'{mood}: centre of mass on (24,25) (got {np.mean(cxs):.2f},{np.mean(cys):.2f})')
    check(max(cxs) - min(cxs) < 0.30 and max(cys) - min(cys) < 0.30,
          f'{mood}: no drift across breath frames '
          f'(x travel {max(cxs)-min(cxs):.3f}, y travel {max(cys)-min(cys):.3f})')
    # A breath is a pure radial scale, so the two "neutral" frames are the same.
    check(np.array_equal(cell(body, r, 0), cell(body, r, 2)),
          f'{mood}: c0 and c2 are both neutral and identical')

# 5. Breath loop: c0 == c2 in silhouette scale, c1 expanded, c3 contracted.
for r, mood in enumerate(ROWS):
    area = [int((cell(body, r, c)[..., 3] == 255).sum()) for c in range(4)]
    check(area[1] > area[0] and area[3] < area[0],
          f'{mood}: breath c1 expands / c3 contracts (areas {area})')
    check(abs(area[1] - area[0]) < area[0] * 0.14,
          f'{mood}: breath is subtle, not a bounce (c1 is +{100*(area[1]-area[0])/area[0]:.1f}%)')

# 6. He is PINK in all 7 moods, and specifically MID-pink.
#    "pink beats accent" is NOT enough: the first bake passed that while MID sat
#    at 14.8%, behind SPEC at 23.8%, and he read as pale pastel rather than
#    #FF00CC. MID is his identity colour and "the bulk of him", so assert that.
for r, mood in enumerate(ROWS):
    a = cell(body, r, 0)
    op = a[a[..., 3] == 255][:, :3]
    cnt = {}
    for p in op:
        cnt[PAL[tuple(int(v) for v in p)]] = cnt.get(PAL[tuple(int(v) for v in p)], 0) + 1
    pink = sum(cnt.get(k, 0) for k in ('LO', 'MID', 'HI', 'SPEC'))
    accent = sum(cnt.get(k, 0) for k in ('GRN', 'RED', 'CYN'))
    check(pink > accent * 3, f'{mood}: body reads pink (pink {pink}px vs accent {accent}px)')
    ramp = {k: cnt.get(k, 0) for k in ('LO', 'MID', 'HI', 'SPEC')}
    if mood != 'SLEEP':      # SLEEP is dimmed on purpose -- it walks the ramp down
        check(ramp['MID'] == max(ramp.values()),
              f'{mood}: MID is the dominant body colour '
              f'(LO {ramp["LO"]} MID {ramp["MID"]} HI {ramp["HI"]} SPEC {ramp["SPEC"]})')

# 6b. Face ink must sit INSIDE the silhouette, never on the rim. SCARED's brow
#     was landing exactly on the outline: it squashes to sy=0.84, which brings
#     the head top down to meet a brow that blob.js only gets away with because
#     there the brow rides a live bob.
for r, mood in enumerate(ROWS):
    for c in range(4):
        a = cell(body, r, c)
        ink = np.all(a[..., :3] == (10, 0, 16), -1) & (a[..., 3] == 255)
        op = a[..., 3] == 255
        edge = np.zeros_like(ink)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                edge |= ~np.roll(np.roll(op, dy, 0), dx, 1)
        check(not (ink & edge).any(),
              f'{mood} c{c}: brows/mouth sit inside the silhouette, not on the rim')

# 7. Rim accent is thin, and lower-right only.
for r, mood in enumerate(ROWS):
    a = cell(body, r, 0)
    m = np.zeros(a.shape[:2], bool)
    for k in ((0, 255, 157), (255, 51, 102), (0, 229, 255)):
        m |= np.all(a[..., :3] == k, -1) & (a[..., 3] == 255)
    n = int(m.sum())
    if n:
        ys, xs = np.where(m)
        check(n < 130, f'{mood}: rim accent is thin ({n}px)')
        check(xs.mean() > 24 and ys.mean() > 25,
              f'{mood}: rim accent sits lower-right (mean x{xs.mean():.1f} y{ys.mean():.1f})')

# 8. Eyes sheet: eyes only, correct bands, two glints, SLEEP shut in all columns.
for r, mood in enumerate(ROWS):
    for c in range(3):
        a = cell(eyes, r, c)
        ys, xs = np.where(a[..., 3] == 255)
        check(21 <= ys.min() and ys.max() <= 27, f'{mood} eyes c{c}: inside y21-27 (y{ys.min()}-{ys.max()})')
        check(xs.min() + xs.max() == 48, f'{mood} eyes c{c}: eye pair centred on pixel 24')
        wht = int((np.all(a[..., :3] == (255, 255, 255), -1) & (a[..., 3] == 255)).sum())
        if mood not in ('HAPPY', 'SLEEP') and c != 2:
            check(wht == 2, f'{mood} eyes c{c}: exactly one WHT key per eye ({wht})')

    shut = [cell(eyes, 4, c) for c in range(3)]
    if r == 4:
        check(np.array_equal(shut[0], shut[1]) and np.array_equal(shut[1], shut[2]),
              'SLEEP: eyes closed in all 3 columns')

# 9. Glints must not be buried under a brow (the brow is on the OTHER sheet, and
#    the engine composites eyes on top -- but a glint inside a brow footprint
#    would still read as a hole punched in the brow).
for r, mood in enumerate(ROWS):
    e, b = cell(eyes, r, 0), cell(body, r, 0)
    gl = np.all(e[..., :3] == (255, 255, 255), -1) & (e[..., 3] == 255)
    br = np.all(b[..., :3] == (10, 0, 16), -1) & (b[..., 3] == 255)
    check(not (gl & br).any(), f'{mood}: WHT key glint is not under a brow')

# 10. Composite: eyes over body must land on the face, not on bare canvas.
for r, mood in enumerate(ROWS):
    e, b = cell(eyes, r, 0), cell(body, r, 0)
    em = e[..., 3] == 255
    check(bool((b[..., 3][em] == 255).all()),
          f'{mood}: every eye pixel lands on the body (no eye floating off-silhouette)')

for s, m in notes:
    print(f'  ok   {m}')
print()
for s, m in fails:
    print(f'  FAIL {m}')
print(f'\n{len(notes)} passed, {len(fails)} failed')
sys.exit(1 if fails else 0)
