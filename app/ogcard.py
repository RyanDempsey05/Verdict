import io
import os

from PIL import Image, ImageDraw, ImageFilter

from app import card as sharecard

W, H = 1200, 630
BG = (10, 10, 11)
BONE = (237, 237, 240)
MUTED = (150, 150, 158)
CRIMSON = (224, 57, 77)

OUT_PATH = "/media/og-default.png"


def _collage(posters: list) -> Image.Image | None:
    """Row of posters across the top, darkened to sit behind the text."""
    imgs = []
    for url in posters:
        got = sharecard._fetch(url)
        if got is not None:
            imgs.append(got)
        if len(imgs) >= 7:
            break
    if not imgs:
        return None

    strip = Image.new("RGB", (W, H), BG)
    pw = W // 6
    ph = int(pw * 1.5)
    x = -20
    i = 0
    while x < W:
        src = imgs[i % len(imgs)]
        strip.paste(sharecard._cover(src, pw, ph), (x, -40))
        x += pw + 6
        i += 1

    strip = strip.filter(ImageFilter.GaussianBlur(3))
    dark = Image.new("RGB", (W, H), BG)
    return Image.blend(strip, dark, 0.72)


def build(posters: list | None = None) -> bytes:
    base = _collage(posters or [])
    img = base if base is not None else Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # crimson wash from the bottom left
    glow = Image.new("RGB", (W, H), BG)
    gd = ImageDraw.Draw(glow)
    for y in range(H):
        a = (y / H) ** 1.6
        gd.line(
            [(0, y), (W, y)],
            fill=(
                int(BG[0] + (140 - BG[0]) * a * 0.30),
                int(BG[1] + (28 - BG[1]) * a * 0.30),
                int(BG[2] + (42 - BG[2]) * a * 0.30),
            ),
        )
    img = Image.blend(img, glow, 0.45)
    d = ImageDraw.Draw(img)

    f_brand = sharecard._font("Cinzel.ttf", 82)
    f_tag = sharecard._font("Inter-Regular.ttf", 38)
    f_foot = sharecard._font("Inter-Regular.ttf", 28)

    x, y = 78, 250
    d.text((x, y), "VER", font=f_brand, fill=BONE)
    bw = d.textlength("VER", font=f_brand)
    d.text((x + bw, y), "DICT", font=f_brand, fill=CRIMSON)

    d.text((x, y + 122), "Rate films, shows, and games.", font=f_tag, fill=BONE)
    d.text((x, y + 176), "Build your library of favorites.", font=f_tag, fill=MUTED)

    d.line([(x, H - 96), (W - 78, H - 96)], fill=(48, 48, 54), width=2)
    d.text((x, H - 72), "verdictapp.app", font=f_foot, fill=MUTED)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def ensure(posters: list | None = None) -> bool:
    """Write the card to the media volume once; it's served as a static file."""
    if os.path.exists(OUT_PATH):
        return True
    try:
        with open(OUT_PATH, "wb") as fh:
            fh.write(build(posters))
        return True
    except Exception:
        return False
