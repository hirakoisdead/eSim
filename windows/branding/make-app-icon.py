#!/usr/bin/env python3
"""Build images/esim.ico -- the eSim identity icon -- from images/logo.png.

    python windows/branding/make-app-icon.py

The .ico is committed; this only needs re-running if logo.png changes.

It is the icon on eSim.exe (windows/launcher/esim_launcher.rc), on the setup
exe, on the Start-menu/desktop shortcuts and in Add/Remove Programs -- so the
app, its installer and its shortcuts all show the same mark the app's own
title bar and splash screen do. (The launcher used to embed workspace.ico,
which is a generic briefcase clipart, not eSim branding at all.)

Every size Windows asks for is stored, each resampled with LANCZOS from one
master: Explorer picks the nearest and never has to smear a 256 px bitmap
into a 16 px taskbar slot. The master is scaled up to 256 first because
Pillow silently drops any requested size larger than the image it is given,
and logo.png is only 200 px -- that is how the first cut of this icon ended
up with no 256 px entry (the size Explorer's large-icon views use).
"""
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGES = os.path.join(HERE, os.pardir, os.pardir, "images")

SIZES = [16, 20, 24, 32, 40, 48, 64, 72, 96, 128, 256]
MARGIN = 0.02          # breathing room so the coin's rim is not clipped


def main():
    logo = Image.open(os.path.join(IMAGES, "logo.png")).convert("RGBA")
    logo = logo.crop(logo.getbbox())        # drop the transparent border

    side = max(logo.size)
    pad = round(side * MARGIN)
    canvas = Image.new("RGBA", (side + 2 * pad, side + 2 * pad), (0, 0, 0, 0))
    canvas.alpha_composite(logo, ((canvas.width - logo.width) // 2,
                                  (canvas.height - logo.height) // 2))
    canvas = canvas.resize((max(SIZES),) * 2, Image.LANCZOS)

    out = os.path.join(IMAGES, "esim.ico")
    canvas.save(out, format="ICO", sizes=[(s, s) for s in SIZES])
    print("wrote", out, "sizes:", SIZES)


if __name__ == "__main__":
    main()
