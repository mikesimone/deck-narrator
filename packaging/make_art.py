#!/usr/bin/env python3
"""Draws the app icon and the installer's banner and side images, in the brand palette
(pastel purple and pink on dark amethyst). The outputs are committed; re-run this only
to change them. Needs Pillow:  python packaging/make_art.py

  packaging/deck-narrator.ico       Windows icon (both programs, Start menu, Apps list)
  packaging/deck-narrator.png       256 px icon (GUI header and Linux window icon)
  packaging/installer/banner.bmp    493x58, top of the installer's inner pages
  packaging/installer/dialog.bmp    493x312, welcome and finish pages
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
GROUND, TILE, PURPLE, PINK, INK = "#1C1526", "#2A1E3A", "#C2A0E2", "#FF8FD0", "#F1E9FA"
LIGHT_BG, LIGHT_INK = "#F6F1FB", "#2E1A3D"
BARS = [0.35, 0.6, 0.9, 0.55, 1.0, 0.7, 0.45, 0.8, 0.5, 0.3]


def icon(size):
    """A slide on a stand, with a sound wave on it, on the brand's rounded tile."""
    s = 1024
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((24, 24, s - 24, s - 24), radius=190, fill=TILE)
    d.rounded_rectangle((150, 230, 874, 690), radius=48, fill=PURPLE)            # the slide
    d.rounded_rectangle((196, 276, 828, 644), radius=26, fill=GROUND)
    d.rectangle((487, 690, 537, 780), fill=PURPLE)                               # stand
    d.rounded_rectangle((360, 770, 664, 822), radius=26, fill=PURPLE)
    w, gap, cy = 40, 20, 460
    x = (s - (len(BARS) * w + (len(BARS) - 1) * gap)) // 2
    for b in BARS:
        h = int(140 * b)
        d.rounded_rectangle((x, cy - h, x + w, cy + h), radius=20, fill=PINK)
        x += w + gap
    return im.resize((size, size), Image.LANCZOS)


def font(px, bold=False):
    for name in (("segoeuib.ttf" if bold else "segoeui.ttf"),
                 ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    big = icon(256)
    big.save(HERE / "deck-narrator.png")
    icon(1024).save(HERE / "deck-narrator.ico", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])

    # WixUI writes the page title in black on the left of the banner, so it stays light.
    banner = Image.new("RGB", (493, 58), LIGHT_BG)
    banner.paste(icon(46), (493 - 54, 6), icon(46))
    banner.save(HERE / "installer" / "banner.bmp")

    # The welcome/finish text sits on the right 329 px, in black: keep that part light.
    dialog = Image.new("RGB", (493, 312), "#FFFCFF")
    d = ImageDraw.Draw(dialog)
    d.rectangle((0, 0, 163, 312), fill=GROUND)
    dialog.paste(icon(112), (26, 52), icon(112))
    d.text((82, 190), "Deck", font=font(22, True), fill=PURPLE, anchor="mm")
    d.text((82, 216), "Narrator", font=font(22, True), fill=PURPLE, anchor="mm")
    d.text((82, 250), "notes to narrated", font=font(11), fill=INK, anchor="mm")
    d.text((82, 265), "video", font=font(11), fill=INK, anchor="mm")
    d.rectangle((0, 304, 163, 312), fill=PINK)
    dialog.save(HERE / "installer" / "dialog.bmp")
    print("wrote icon, png, banner.bmp, dialog.bmp")


if __name__ == "__main__":
    main()
