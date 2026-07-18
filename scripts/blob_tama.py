"""
Tamagotchi-style Blob mockups. Standing still, neutral face.

Hand-authored 16x16 pixel maps -- NOT derived from a lit sphere. Tamagotchi
sprites are flat 1-bit LCD shapes: no light source, no shading, no dither, no
gradient. The character is a silhouette plus a few holes. 16x16 upscales exactly
3x into the 48px cell.

NO OUTLINES, and that is the whole translation problem. Tamagotchi is DARK ON
LIGHT: a black outline on a green-grey LCD, where the outline IS the character
and the interior is empty. The Blob is LIGHT ON DARK -- he composites over a
vaporwave sunset. An OUT (#2A003D) outline against that background is invisible,
so the first pass rendered six identical pink balls. Inverted, the FILL is the
character and the eyes are holes punched in it. Same form language, mirrored.

  .  transparent   #  MID body    X  EYE ink    w  WHT glint

    python scripts/blob_tama.py <outdir>
"""

import sys
import numpy as np
from PIL import Image
from pathlib import Path

P = {'#': (0xFF, 0x00, 0xCC), 'X': (0x0A, 0x00, 0x10), 'w': (0xFF, 0xFF, 0xFF)}

BALL = [
    '................',
    '.....######.....',
    '...##########...',
    '..############..',
    '.##############.',
    '.##############.',
    '.##############.',
    '.###XX####XX###.',
    '.###XX####XX###.',
    '.##############.',
    '.##############.',
    '.####XXXXXX####.',
    '.##############.',
    '..############..',
    '...##########...',
    '.....######.....',
]

EGG = [
    '......####......',
    '....########....',
    '...##########...',
    '..############..',
    '..############..',
    '..############..',
    '..############..',
    '..##XX####XX##..',
    '..##XX####XX##..',
    '..############..',
    '..############..',
    '..###XXXXXX###..',
    '..############..',
    '...##########...',
    '....########....',
    '.....######.....',
]

PEAR = [
    '................',
    '.......##.......',
    '......####......',
    '.....######.....',
    '....########....',
    '...##########...',
    '..############..',
    '..##XX####XX##..',
    '..##XX####XX##..',
    '.##############.',
    '.##############.',
    '.####XXXXXX####.',
    '.##############.',
    '.##############.',
    '..############..',
    '...##########...',
]

NUBS = [
    '................',
    '.....######.....',
    '...##########...',
    '..############..',
    '.##############.',
    '.##############.',
    '.##############.',
    '.###XX####XX###.',
    '.###XX####XX###.',
    '.##############.',
    '.####XXXXXX####.',
    '.##############.',
    '..############..',
    '...##########...',
    '..###......###..',
    '..###......###..',
]

BIGEYE = [
    '................',
    '.....######.....',
    '...##########...',
    '..############..',
    '.##############.',
    '.##############.',
    '.##XXXX##XXXX##.',
    '.##XXXX##XXXX##.',
    '.##XXXX##XXXX##.',
    '.##XXXX##XXXX##.',
    '.##############.',
    '.####XXXXXX####.',
    '.##############.',
    '..############..',
    '...##########...',
    '.....######.....',
]

SPROUT = [
    '.......##.......',
    '.......##.......',
    '......####......',
    '.....######.....',
    '...##########...',
    '..############..',
    '.##############.',
    '.##############.',
    '.###XX####XX###.',
    '.###XX####XX###.',
    '.##############.',
    '.####XXXXXX####.',
    '.##############.',
    '..############..',
    '...##########...',
    '.....######.....',
]

# The original hardware had no glints -- a 1-bit LCD cannot express one. This is
# the cheat, for comparison against BLOB.md's "eyes carry the comedy" rule.
GLINT = [
    '................',
    '.....######.....',
    '...##########...',
    '..############..',
    '.##############.',
    '.##############.',
    '.##############.',
    '.###wX####wX###.',
    '.###XX####XX###.',
    '.##############.',
    '.##############.',
    '.####XXXXXX####.',
    '.##############.',
    '..############..',
    '...##########...',
    '.....######.....',
]

SETS = [
    ('ball', 'Ball', 'The default. Round, dot eyes, flat.', BALL),
    ('egg', 'Egg', 'Taller, narrower. Reads younger.', EGG),
    ('pear', 'Pear', 'Narrow top, heavy bottom. Squattest.', PEAR),
    ('nubs', 'Nubs', 'Two feet. Standing, not floating.', NUBS),
    ('bigeye', 'Big eye', 'Eyes eat the face. Most expressive.', BIGEYE),
    ('sprout', 'Sprout', 'Antenna. Gives him a top.', SPROUT),
    ('glint', 'Ball + glint', 'One white pixel. Not period-correct.', GLINT),
]


def render(m, z=3):
    assert len(m) == 16, f'{len(m)} rows'
    for i, r in enumerate(m):
        assert len(r) == 16, f'row {i} is {len(r)} wide, not 16'
    a = np.zeros((16, 16, 4), np.uint8)
    for y, row in enumerate(m):
        for x, ch in enumerate(row):
            if ch != '.':
                a[y, x] = (*P[ch], 255)
    return a.repeat(z, 0).repeat(z, 1)


def check(m):
    """Tamagotchi sprites are symmetric. Verify, don't assume. Glints are
    exempt: the key light is global, so it translates rather than mirrors."""
    bad = []
    for y, row in enumerate(m):
        for x, ch in enumerate(row):
            mir = row[15 - x]
            if ch == 'w' or mir == 'w':
                continue
            if ch != mir:
                bad.append((x, y))
    return bad


if __name__ == '__main__':
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for k, n, d, m in SETS:
        b = check(m)
        Image.fromarray(render(m), 'RGBA').save(out / f'{k}.png')
        px = sum(r.count('#') + r.count('X') + r.count('w') for r in m)
        print(f'{k:8} {n:14} symmetric: {"yes" if not b else f"NO {b[:4]}"}   {px} px')
