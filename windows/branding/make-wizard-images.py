#!/usr/bin/env python3
"""Generate the Inno Setup wizard artwork from the repo's own logo assets.

Run once when the branding sources change; the BMPs it writes next to it are
committed, so a build machine needs no Pillow:

    python windows/branding/make-wizard-images.py

Inno picks the file whose size best matches the display's DPI scaling, so
each image is emitted at the four sizes Inno documents (100/125/150/200%).
BMP because that is the only format Inno's WizardImageFile loads -- a PNG
compiles fine but the setup EXE dies at launch with "Bitmap image is not
valid":

    wizard-164x314.bmp ...      left panel, Welcome + Finished pages
    wizard-small-55x58.bmp ...  top-right corner, every inner page

Sources (images/): logo.png (the transistor coin), esim_text.png (the gold
'eSim' wordmark), fosseeLogo.png. The setup EXE's own icon is images/esim.ico
-- the same icon eSim.exe and the shortcuts carry; see make-app-icon.py.
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGES = os.path.join(HERE, os.pardir, os.pardir, "images")

# Wizard-panel palette: the warm browns of the eSim splash screen, so the
# installer and the app that opens after it read as one product.
TOP = (74, 47, 28)
BOTTOM = (150, 106, 68)
GLOW = (214, 176, 134)

BIG_SIZES = [(164, 314), (205, 393), (246, 471), (328, 628)]
SMALL_SIZES = [(55, 58), (69, 73), (83, 87), (110, 116)]


def asset(name):
    return Image.open(os.path.join(IMAGES, name)).convert("RGBA")


def font(size, bold=False):
    for path, kw in (
        (os.path.join(IMAGES, "fonts",
                      "Ubuntu-Bold.ttf" if bold else "Ubuntu-Regular.ttf"),
         {}),
        (r"C:\Windows\Fonts\seguisb.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
         {}),
    ):
        try:
            f = ImageFont.truetype(path, size)
            if kw.get("variation"):
                try:
                    f.set_variation_by_name(kw["variation"])
                except Exception:
                    pass
            return f
        except OSError:
            continue
    return ImageFont.load_default()


def fit(img, width):
    """Scale img to `width`, keeping aspect."""
    h = max(1, round(img.height * width / img.width))
    return img.resize((width, h), Image.LANCZOS)


def centered(canvas, img, y):
    canvas.alpha_composite(img, ((canvas.width - img.width) // 2, y))


def big_panel():
    """The 4x master: everything below is a LANCZOS downscale of this."""
    W, H = 656, 1256
    panel = Image.new("RGBA", (W, H))
    px = panel.load()
    for y in range(H):                       # vertical gradient
        t = y / (H - 1)
        row = tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM))
        for x in range(W):
            px[x, y] = row + (255,)

    # Soft radial glow behind the logo, so the coin does not sit on flat paint.
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    cx, cy = W // 2, 380
    for i, r in enumerate(range(520, 0, -8)):
        a = round(46 * (1 - r / 520) ** 2)
        g.ellipse((cx - r, cy - r * 0.82, cx + r, cy + r * 0.82), fill=GLOW + (a,))
    panel.alpha_composite(glow)

    centered(panel, fit(asset("logo.png"), 300), 230)
    centered(panel, fit(asset("esim_text.png"), 400), 580)

    d = ImageDraw.Draw(panel)
    tag = "Open Source EDA Tool"
    f = font(38)
    d.text((W // 2, 800), tag, font=f, fill=(238, 224, 206, 255), anchor="mm")

    # Hairline rule, then the FOSSEE mark on the white plate its orange needs.
    d.line((110, 900, W - 110, 900), fill=(214, 176, 134, 90), width=2)
    fossee = fit(asset("fosseeLogo.png"), 380)
    plate_pad = 26
    plate = Image.new(
        "RGBA",
        (fossee.width + 2 * plate_pad, fossee.height + 2 * plate_pad),
        (0, 0, 0, 0),
    )
    ImageDraw.Draw(plate).rounded_rectangle(
        (0, 0, plate.width - 1, plate.height - 1), radius=20, fill=(255, 255, 255, 245)
    )
    plate.alpha_composite(fossee, (plate_pad, plate_pad))
    centered(panel, plate, 940)

    d.text((W // 2, 1190), "FOSSEE, IIT Bombay", font=font(34, bold=True),
           fill=(255, 255, 255, 235), anchor="mm")
    return panel


def small_master():
    """Inner pages are white; the mark sits on white so it blends in."""
    S = 440
    img = Image.new("RGBA", (S, S + 24), (255, 255, 255, 255))
    centered(img, fit(asset("logo.png"), 360), 32)
    return img


def main():
    big = big_panel()
    for w, h in BIG_SIZES:
        out = big.resize((w, h), Image.LANCZOS).convert("RGB")
        out.save(os.path.join(HERE, f"wizard-{w}x{h}.bmp"))

    small = small_master()
    for w, h in SMALL_SIZES:
        out = small.resize((w, h), Image.LANCZOS).convert("RGB")
        out.save(os.path.join(HERE, f"wizard-small-{w}x{h}.bmp"))

    print("wrote", len(BIG_SIZES) + len(SMALL_SIZES), "images to", HERE)


if __name__ == "__main__":
    main()
