"""
Contact sheet: composite the two sheets and look at him. Nearest-neighbour only.
Writes to the scratchpad, not the repo -- this is a look, not a deliverable.
"""
import sys
import numpy as np
from PIL import Image
from pathlib import Path

CELL, Z = 48, 5
ROWS = ['IDLE', 'HAPPY', 'SCARED', 'ALERT', 'SLEEP', 'SMUG', 'BRACE']
DIR = Path(__file__).resolve().parents[1] / 'dashboard'
OUT = Path(sys.argv[1])

body = Image.open(DIR / 'blob_body.png').convert('RGBA')
eyes = Image.open(DIR / 'blob_eyes.png').convert('RGBA')


def cell(sh, r, c):
    return sh.crop((c * CELL, r * CELL, (c + 1) * CELL, (r + 1) * CELL))


# columns: 4 breath frames (eyes open), then lid half / lid shut, then eyes alone
COLS = [('b', 0, 0), ('b', 1, 0), ('b', 2, 0), ('b', 3, 0),
        ('b', 0, 1), ('b', 0, 2), ('e', 0, 0)]

W, H = len(COLS) * CELL, len(ROWS) * CELL
sheet = Image.new('RGBA', (W, H), (0, 0, 0, 0))

for r in range(len(ROWS)):
    for i, (kind, bc, ec) in enumerate(COLS):
        if kind == 'e':
            im = cell(eyes, r, ec)
        else:
            im = cell(body, r, bc).copy()
            im.alpha_composite(cell(eyes, r, ec))
        sheet.paste(im, (i * CELL, r * CELL), im)

# Stand-in vaporwave sunset -- he composites over stream_bg.js, never over black.
bg = Image.new('RGBA', (W, H))
px = bg.load()
for y in range(H):
    t = y / H
    px_row = (int(28 + 60 * t), int(6 + 10 * t), int(48 + 40 * (1 - t)))
    for x in range(W):
        px[x, y] = (*px_row, 255)
bg.alpha_composite(sheet)

big = bg.resize((W * Z, H * Z), Image.NEAREST)
big.save(OUT)
print(f'{OUT}  {big.width}x{big.height}   cols: 4x breath | half-lid | shut | eyes-only')
