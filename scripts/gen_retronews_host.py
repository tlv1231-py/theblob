#!/usr/bin/env python3
"""RetroNews host — "ROOKIE" rebuilt at spec, with his full expression sheet.

Rebuilt from the approved concept art: spiky dark-navy hair, warm skin, very
large eyes, GOLD headset with a boom mic, cream collared shirt, cyan tie.

THE SPEC (CLAUDE.md "RetroNews — the era rule" + retronews.py):
    cell            72 x 90 px
    sheet           3 lid columns x 6 expression rows = 216 x 540
    displayed at    4x -> 288 x 360 stage -> 216 x 270 device
                    (stage x 0.75 = device, so 72*4*0.75 = 216 = 72*3 exactly;
                     any non-multiple-of-4 resamples him and the era read dies)
    palette         <= 32 colours, ZERO semi-alpha, transparent background

WHY IT IS BUILT THIS WAY — REGISTRATION.
The base (hair, head, headset, shirt) is drawn ONCE and every cell composites
the same base, changing only BROWS, EYES and MOUTH. That is not a shortcut, it
is the whole reason the sheet is usable: if the skull drifts even 1px between
expressions he twitches every time his mood changes, and at 3x device scale 1px
is a visible 3px jump. Deriving instead of redrawing makes drift impossible.

    python scripts/gen_retronews_host.py
"""
from __future__ import annotations

import os
import sys
from PIL import Image, ImageDraw

W, H = 72, 90
CX = 36
OUT = os.environ.get("OUT_DIR", "host")

MOODS = ["NEUTRAL", "HAPPY", "SURPRISED", "SMUG", "WORRIED", "SLEEPY"]
LIDS = ["open", "half", "shut"]

C = {
    "clear":  (0, 0, 0, 0),
    "line":   (26, 24, 54, 255),      # the 1px keyline — navy, not black
    "hair":   (54, 52, 96, 255),
    "hair_d": (38, 36, 72, 255),
    "hair_h": (86, 84, 140, 255),
    "skin":   (246, 176, 110, 255),
    "skin_d": (214, 138, 80, 255),
    "skin_h": (255, 206, 156, 255),
    "blush":  (240, 146, 118, 255),
    "eye_w":  (252, 252, 255, 255),
    "iris":   (40, 44, 104, 255),
    "gold":   (240, 190, 60, 255),
    "gold_d": (176, 132, 30, 255),
    "grey":   (92, 100, 122, 255),
    "grey_d": (60, 66, 86, 255),
    "shirt":  (244, 240, 214, 255),
    "shirt_d": (206, 200, 168, 255),
    "tie":    (74, 196, 230, 255),
    "tie_d":  (44, 150, 190, 255),
    "mouth":  (150, 80, 70, 255),
}


def px(d, x, y, c, w=1, h=1):
    d.rectangle([x, y, x + w - 1, y + h - 1], fill=c)


# Hair silhouette: the top edge, one entry per column across the head.
# Hand-authored because spikes are the character's signature and a formula
# makes them regular, which reads as a helmet rather than as hair.
HAIR_TOP = [
    28, 26, 23, 20, 17, 15, 12, 10,  8, 11, 14, 10,  6,  4,  7, 10,
     6,  3,  2,  4,  8,  5,  2,  1,  3,  6,  4,  2,  3,  6,  9,  7,
     5,  8, 11, 14, 12, 15, 18, 21, 24, 27,
]
HAIR_X0 = 15                     # first column the hair occupies


def draw_base(d):
    """Everything that must be IDENTICAL in all 18 cells."""
    # ── shoulders / shirt ────────────────────────────────────────────────
    # Sloped, not a box. A flat-topped rectangle reads as a crate he is standing
    # behind; the slope is what makes it a body.
    for i in range(22):
        inset = max(0, 8 - i * 2)
        px(d, 6 + inset, 68 + i, C["line"], 60 - inset * 2, 1)
        px(d, 7 + inset, 68 + i, C["shirt"], 58 - inset * 2, 1)
        px(d, 7 + inset, 68 + i, C["shirt_d"], 5, 1)
        px(d, 60 - inset, 68 + i, C["shirt_d"], 5, 1)

    # collar — two flaps meeting in a V
    for i in range(10):
        px(d, 24 + i, 66 + i, C["shirt"], 6, 1)
        px(d, 48 - i - 5, 66 + i, C["shirt"], 6, 1)
        px(d, 23 + i, 66 + i, C["line"], 1, 1)
        px(d, 48 - i + 1, 66 + i, C["line"], 1, 1)

    # tie
    px(d, CX - 3, 70, C["tie"], 7, 4)
    px(d, CX - 4, 74, C["tie"], 9, 16)
    px(d, CX - 4, 74, C["tie_d"], 2, 16)
    px(d, CX - 4, 70, C["line"], 1, 20)
    px(d, CX + 4, 70, C["line"], 1, 20)

    # ── neck ─────────────────────────────────────────────────────────────
    px(d, CX - 7, 58, C["line"], 15, 10)
    px(d, CX - 6, 58, C["skin_d"], 13, 9)
    px(d, CX - 6, 58, C["skin"], 8, 5)
    px(d, CX - 7, 66, C["line"], 15, 1)          # collar shadow

    # ── head ─────────────────────────────────────────────────────────────
    # stepped oval, hand-tapered: wide cheeks, narrow chin
    head = []
    for y in range(44):
        t = y / 43.0
        if t < 0.60:
            w = 17 - int(round(2 * (0.60 - t) * (0.60 - t) * 18))
        else:
            k = (t - 0.60) / 0.40
            w = int(round(17 - 10 * k * k))
        head.append(max(3, w))
    for y, w in enumerate(head):
        px(d, CX - w, 16 + y, C["skin"], w * 2 + 1, 1)
        px(d, CX + w - 4, 16 + y, C["skin_d"], 4, 1)          # right-side shade
        px(d, CX - w - 1, 16 + y, C["line"], 1, 1)
        px(d, CX + w + 1, 16 + y, C["line"], 1, 1)
    px(d, CX - head[-1], 60, C["line"], head[-1] * 2 + 1, 1)

    # ear (left, viewer's left)
    px(d, CX - 19, 34, C["line"], 4, 9)
    px(d, CX - 18, 35, C["skin_d"], 3, 7)

    # ── hair ─────────────────────────────────────────────────────────────
    for i, top in enumerate(HAIR_TOP):
        x = HAIR_X0 + i
        if x < 0 or x >= W:
            continue
        bottom = 30 if x < CX - 6 else (26 if x < CX + 8 else 32)
        px(d, x, top, C["line"], 1, 1)
        px(d, x, top + 1, C["hair"], 1, bottom - top)
        if i % 5 == 0:
            px(d, x, top + 1, C["hair_h"], 1, max(2, (bottom - top) // 3))
    # sideburn masses so the hair frames the face
    px(d, CX - 20, 28, C["hair"], 4, 12)
    px(d, CX - 21, 28, C["line"], 1, 12)
    px(d, CX + 16, 28, C["hair"], 5, 14)
    px(d, CX + 21, 28, C["line"], 1, 14)
    px(d, CX + 16, 28, C["hair_d"], 2, 14)

    # ── headset ───────────────────────────────────────────────────────────
    # OUTLINED, and seated LOWER than the crown. The first version ran the bare
    # gold band across the top of the spikes with no keyline, so at 72px it
    # merged into the hair and read as blonde highlights rather than as
    # hardware. A 1px dark line on both sides is what separates an object from
    # the thing behind it at this size — the same reason every shape here has one.
    band = [(CX + 4, 14), (CX + 8, 12), (CX + 12, 12), (CX + 15, 14),
            (CX + 17, 17), (CX + 19, 21), (CX + 20, 25)]
    for bx, by in band:
        px(d, bx, by - 1, C["line"], 3, 1)        # top keyline
        px(d, bx, by, C["gold"], 3, 3)
        px(d, bx, by + 3, C["gold_d"], 3, 1)
        px(d, bx, by + 4, C["line"], 3, 1)        # bottom keyline
    # earpiece — clearly attached to the band, over the ear line
    px(d, CX + 16, 28, C["line"], 9, 14)
    px(d, CX + 17, 29, C["grey"], 7, 12)
    px(d, CX + 17, 29, C["grey_d"], 3, 12)
    px(d, CX + 19, 32, C["gold"], 3, 6)           # gold detail so it ties to the band
    # boom mic — thicker arm, bigger capsule, both outlined
    for i in range(8):
        px(d, CX + 16 - i, 41 + i, C["line"], 3, 1)
        px(d, CX + 16 - i, 41 + i, C["gold"], 2, 1)
    px(d, CX + 6, 49, C["line"], 9, 6)
    px(d, CX + 7, 50, C["grey"], 7, 4)
    px(d, CX + 7, 50, C["grey_d"], 3, 4)


def draw_brows(d, mood):
    L, R = CX - 13, CX + 5
    if mood == "SURPRISED":
        px(d, L, 25, C["line"], 9, 2); px(d, R, 25, C["line"], 9, 2)
    elif mood == "WORRIED":
        for i in range(9):
            px(d, L + i, 29 - i // 3, C["line"], 1, 2)
            px(d, R + i, 27 + i // 3, C["line"], 1, 2)
    elif mood == "SMUG":
        px(d, L, 29, C["line"], 9, 2)
        for i in range(9):
            px(d, R + i, 27 - i // 4, C["line"], 1, 2)
    elif mood == "SLEEPY":
        px(d, L, 29, C["line"], 9, 1); px(d, R, 29, C["line"], 9, 1)
    else:                                          # NEUTRAL / HAPPY
        for i in range(9):
            px(d, L + i, 28 - i // 4, C["line"], 1, 2)
            px(d, R + i, 26 + i // 4, C["line"], 1, 2)


def draw_eyes(d, mood, lid):
    """Big eyes carry the whole performance at this size."""
    for s, ex in ((-1, CX - 13), (1, CX + 5)):
        if lid == "shut" or mood == "SLEEPY" and lid != "open":
            px(d, ex, 37, C["line"], 9, 2)
            px(d, ex + 1, 39, C["line"], 7, 1)
            continue
        h = 12 if lid == "open" else 6
        top = 33 if lid == "open" else 37
        if mood == "HAPPY":                        # ^^ happy arcs
            for i in range(9):
                yy = 40 - abs(i - 4)
                px(d, ex + i, yy, C["line"], 1, 2)
            continue
        # sclera + keyline
        px(d, ex, top, C["line"], 9, 1)
        px(d, ex - 1, top + 1, C["line"], 1, h - 2)
        px(d, ex + 9, top + 1, C["line"], 1, h - 2)
        px(d, ex, top + h - 1, C["line"], 9, 1)
        px(d, ex, top + 1, C["eye_w"], 9, h - 2)
        # iris — bigger and higher for SURPRISED, low-lidded for SMUG
        ih = max(3, h - 4) if mood != "SURPRISED" else max(4, h - 3)
        iy = top + 2 if mood != "SMUG" else top + 3
        px(d, ex + 2, iy, C["iris"], 5, min(ih, top + h - 1 - iy))
        px(d, ex + 3, iy + 1, C["eye_w"], 2, 2)    # specular glint
        if mood == "SMUG":                          # heavy upper lid
            px(d, ex, top + 1, C["line"], 9, 2)


def draw_mouth(d, mood):
    if mood == "HAPPY":
        px(d, CX - 4, 51, C["line"], 9, 1)
        px(d, CX - 3, 52, C["mouth"], 7, 2)
        px(d, CX - 2, 54, C["line"], 5, 1)
    elif mood == "SURPRISED":
        px(d, CX - 2, 50, C["line"], 5, 1)
        px(d, CX - 3, 51, C["line"], 1, 4); px(d, CX + 2, 51, C["line"], 1, 4)
        px(d, CX - 2, 51, C["mouth"], 5, 4)
        px(d, CX - 2, 55, C["line"], 5, 1)
    elif mood == "SMUG":
        px(d, CX - 1, 52, C["line"], 7, 1)
        px(d, CX + 5, 51, C["line"], 1, 1)
    elif mood == "WORRIED":
        for i in range(7):
            px(d, CX - 3 + i, 53 - (1 if 1 < i < 5 else 0), C["line"], 1, 1)
    elif mood == "SLEEPY":
        px(d, CX - 1, 52, C["line"], 4, 2)
    else:                                           # NEUTRAL
        px(d, CX - 3, 52, C["line"], 7, 1)


def draw_extras(d, mood):
    px(d, CX - 15, 46, C["blush"], 5, 2)            # blush, always
    px(d, CX + 9, 46, C["blush"], 5, 2)
    if mood == "WORRIED":                           # sweat bead
        px(d, CX + 13, 24, C["eye_w"], 2, 3)
    if mood == "SLEEPY":
        px(d, CX + 14, 20, C["eye_w"], 3, 3)        # little z


def cell(mood, lid):
    img = Image.new("RGBA", (W, H), C["clear"])
    d = ImageDraw.Draw(img)
    draw_base(d)
    draw_brows(d, mood)
    draw_eyes(d, mood, lid)
    draw_mouth(d, mood)
    draw_extras(d, mood)
    return img


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    sheet = Image.new("RGBA", (W * 3, H * len(MOODS)), C["clear"])
    for r, mood in enumerate(MOODS):
        for c, lid in enumerate(LIDS):
            img = cell(mood, lid)
            sheet.alpha_composite(img, (c * W, r * H))
    path = os.path.join(OUT, "retronews_host.png")
    sheet.save(path)

    data = list(sheet.getdata())
    cols = {p for p in data if p[3] > 0}
    semi = sum(1 for p in data if 0 < p[3] < 255)
    print(f"sheet   {sheet.size[0]}x{sheet.size[1]}  (3 lids x {len(MOODS)} moods of {W}x{H})")
    print(f"colours {len(cols)}   {'OK <=32' if len(cols) <= 32 else 'OVER BUDGET'}")
    print(f"semi-alpha pixels {semi}  {'OK — no anti-aliasing' if semi == 0 else 'FAIL'}")
    print(f"-> {path}")

    # 4x previews: the full sheet, and a row of the open-eyed moods at stage size.
    sheet.resize((sheet.size[0] * 3, sheet.size[1] * 3), Image.NEAREST).save(
        os.path.join(OUT, "_sheet_3x.png"))
    strip = Image.new("RGBA", (len(MOODS) * (W * 4 + 12) + 12, H * 4 + 24), (20, 28, 72, 255))
    for i, mood in enumerate(MOODS):
        strip.alpha_composite(cell(mood, "open").resize((W * 4, H * 4), Image.NEAREST),
                              (12 + i * (W * 4 + 12), 12))
    strip.save(os.path.join(OUT, "_moods_4x.png"))
    print(f"-> {os.path.join(OUT, '_moods_4x.png')} (4x = exact stage size)")


if __name__ == "__main__":
    sys.exit(main())
