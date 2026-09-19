import io
import os

import httpx
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
BG = (10, 10, 11)
PANEL = (18, 18, 21)
LINE = (38, 38, 42)
TEXT = (210, 210, 215)
MUTED = (118, 118, 126)
BONE = (237, 237, 240)

FONT_DIR = "/usr/share/fonts/truetype/verdict"
LABELS = {"movie": "FILMS", "tv": "SHOWS", "game": "GAMES"}


def _font(name: str, size: int):
    path = os.path.join(FONT_DIR, name)
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default(size)


def _ramp(v: float) -> tuple:
    lo, hi = (143, 29, 44), (230, 176, 74)
    t = max(0.0, min(1.0, (v - 0.5) / 4.5))
    return tuple(round(lo[i] + (hi[i] - lo[i]) * t) for i in range(3))


def _fetch(url: str) -> Image.Image | None:
    if not url:
        return None
    try:
        with httpx.Client(timeout=6.0, follow_redirects=True) as c:
            r = c.get(url)
            r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        return img
    except Exception:
        return None


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / img.width, h / img.height)
    img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
    left = (img.width - w) // 2
    top = (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def _truncate(draw, text, font, max_w):
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


def build(kind: str, username: str, entries: list, avatar_path: str | None = None) -> bytes:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # crimson wash at the top
    glow = Image.new("RGB", (W, 620), BG)
    gd = ImageDraw.Draw(glow)
    for y in range(620):
        a = 1 - (y / 620)
        gd.line(
            [(0, y), (W, y)],
            fill=(
                int(BG[0] + (150 - BG[0]) * a * 0.22),
                int(BG[1] + (30 - BG[1]) * a * 0.22),
                int(BG[2] + (45 - BG[2]) * a * 0.22),
            ),
        )
    img.paste(glow, (0, 0))

    f_brand = _font("Cinzel.ttf", 46)
    f_head = _font("Cinzel.ttf", 72)
    f_user = _font("Inter-Regular.ttf", 38)
    f_title = _font("Inter-Regular.ttf", 40)
    f_meta = _font("Inter-Regular.ttf", 30)
    f_rank = _font("Cinzel.ttf", 64)
    f_score = _font("Cinzel.ttf", 46)
    f_foot = _font("Inter-Regular.ttf", 26)

    y = 92

    # avatar + username
    ax = 80
    if avatar_path and os.path.exists(avatar_path):
        try:
            av = Image.open(avatar_path).convert("RGB")
            av = _cover(av, 96, 96)
            mask = Image.new("L", (96, 96), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 95, 95), fill=255)
            img.paste(av, (ax, y), mask)
            ax += 124
        except Exception:
            pass
    d.text((ax, y + 28), username, font=f_user, fill=BONE)

    y += 150
    d.text((80, y), "MY TOP FIVE", font=f_head, fill=BONE)
    y += 92
    d.text((80, y), LABELS.get(kind, ""), font=f_head, fill=(196, 38, 56))
    y += 130

    row_h = 236
    for i in range(5):
        e = entries[i] if i < len(entries) else None
        top = y + i * row_h

        d.text((72, top + 62), str(i + 1), font=f_rank, fill=(60, 60, 66) if not e else MUTED)

        px, pw, ph = 170, 132, 198
        d.rectangle([px, top, px + pw, top + ph], fill=PANEL, outline=LINE)
        if e:
            poster = _fetch(e.get("image_url"))
            if poster is not None:
                img.paste(_cover(poster, pw, ph), (px, top))

        tx = px + pw + 40
        if e:
            title = _truncate(d, e["title"], f_title, W - tx - 200)
            d.text((tx, top + 56), title, font=f_title, fill=BONE)
            meta = str(e["year"]) if e.get("year") else ""
            if meta:
                d.text((tx, top + 112), meta, font=f_meta, fill=MUTED)
            if e.get("score") is not None:
                sc = float(e["score"])
                d.text((W - 170, top + 56), f"{sc:.1f}", font=f_score, fill=_ramp(sc))
        else:
            d.text((tx, top + 76), "—", font=f_title, fill=(50, 50, 56))

    d.line([(80, H - 150), (W - 80, H - 150)], fill=LINE, width=2)
    d.text((80, H - 118), "VER", font=f_brand, fill=BONE)
    bw = d.textlength("VER", font=f_brand)
    d.text((80 + bw, H - 118), "DICT", font=f_brand, fill=(224, 57, 77))
    d.text((80, H - 62), "verdictapp.app", font=f_foot, fill=MUTED)
    d.text((W - 400, H - 62), "Data from TMDB and IGDB", font=f_foot, fill=(70, 70, 76))

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()
