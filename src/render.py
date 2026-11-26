"""Grafiche dei post: da una bozza (JSON) e dalle foto crea le immagini 1080x1350 per Instagram."""
import io

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import config

W, H = 1080, 1350
GREEN = (86, 207, 149)
DARK = (0, 112, 64)
INK = (30, 30, 30)
GREY = (90, 90, 90)
LIGHT = (140, 140, 140)
FONT_B = str(config.ROOT / "assets" / "fonts" / "Poppins-Bold.ttf")
FONT_M = str(config.ROOT / "assets" / "fonts" / "Poppins-Medium.ttf")
LOGO = str(config.ROOT / "assets" / "logo_slide.png")
MARGIN = 64


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def fit_font(draw, text, path, size, max_w, min_size=26):
    while size > min_size and draw.textlength(text, font=font(path, size)) > max_w:
        size -= 2
    return font(path, size)


def wrap(draw, text, fnt, max_w):
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = (line + " " + w).strip()
        if draw.textlength(trial, font=fnt) <= max_w or not line:
            line = trial
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def center(draw, y, text, fnt, fill, width=W):
    w = draw.textlength(text, font=fnt)
    draw.text(((width - w) / 2, y), text, font=fnt, fill=fill)


def load_photo(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    return ImageOps.exif_transpose(im).convert("RGB")


def fill_frame(im: Image.Image) -> Image.Image:
    return ImageOps.fit(im, (W, H), Image.LANCZOS, centering=(0.5, 0.45))


def gradient(im: Image.Image, frac=0.34, strength=210) -> Image.Image:
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    top = int(H * (1 - frac))
    for y in range(top, H):
        d.line((0, y, W, y), fill=(0, 0, 0, int(strength * ((y - top) / (H - top)) ** 1.4)))
    return Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")


def logo_image(width: int) -> Image.Image:
    logo = Image.open(LOGO).convert("RGBA")
    bg = Image.new("RGBA", logo.size, "white")
    bg.alpha_composite(logo)
    logo = bg.convert("RGB").crop((60, 60, 640, 520))
    ratio = width / logo.width
    return logo.resize((width, int(logo.height * ratio)), Image.LANCZOS)


def slide_cover(photo, righe, sottotitolo=""):
    im = gradient(fill_frame(photo), frac=0.45, strength=225)
    d = ImageDraw.Draw(im)
    righe = righe[:3]
    sub_h = 60 if sottotitolo else 0
    line_h = 100
    y = H - MARGIN - sub_h - line_h * len(righe) - 30
    d.rectangle((MARGIN, y - 28, MARGIN + 110, y - 20), fill=GREEN)
    for i, t in enumerate(righe):
        fnt = fit_font(d, t, FONT_B, 78, W - 2 * MARGIN)
        d.text((MARGIN, y + i * line_h), t, font=fnt, fill=GREEN if i == len(righe) - 1 and len(righe) > 1 else "white")
    if sottotitolo:
        fnt = fit_font(d, sottotitolo, FONT_M, 32, W - 2 * MARGIN, 22)
        d.text((MARGIN, H - MARGIN - 34), sottotitolo, font=fnt, fill="white")
    return im


def slide_photo(photo, etichetta, testo):
    im = gradient(fill_frame(photo))
    d = ImageDraw.Draw(im)
    d.rectangle((MARGIN, 1150, MARGIN + 90, 1156), fill=GREEN)
    d.text((MARGIN, 1174), (etichetta or "").upper(), font=font(FONT_B, 28), fill=GREEN)
    fnt = fit_font(d, testo or "", FONT_B, 44, W - 2 * MARGIN, 28)
    d.text((MARGIN, 1222), testo or "", font=fnt, fill="white")
    return im


def slide_text(titolo, punti):
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    logo = logo_image(250)
    im.paste(logo, ((W - logo.width) // 2, 50))
    ft = font(FONT_B, 60)
    lines = wrap(d, titolo, ft, W - 2 * 100)[:3]
    y = 360
    for ln in lines:
        center(d, y, ln, ft, DARK)
        y += 76
    d.rectangle((W / 2 - 60, y + 14, W / 2 + 60, y + 20), fill=GREEN)
    y += 90
    size = 46
    while True:
        fb = font(FONT_M, size)
        blocks = [wrap(d, p, fb, W - 2 * 110 - 40) for p in punti[:5]]
        total = sum(len(b) * (size + 12) + 26 for b in blocks)
        if y + total <= H - 140 or size <= 28:
            break
        size -= 2
    for b in blocks:
        d.ellipse((110, y + size * 0.45, 110 + 16, y + size * 0.45 + 16), fill=GREEN)
        for ln in b:
            d.text((110 + 40, y), ln, font=fb, fill=INK)
            y += size + 12
        y += 26
    center(d, H - 90, config.ADDRESS, font(FONT_M, 26), LIGHT)
    return im


def slide_final(titolo, righe, prezzo):
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    logo = logo_image(400)
    im.paste(logo, ((W - logo.width) // 2, 50))
    ft = font(FONT_B, 76)
    y = 420
    for ln in wrap(d, titolo, ft, W - 2 * 90)[:2]:
        center(d, y, ln, ft, DARK)
        y += 96
    d.rectangle((W / 2 - 60, y + 26, W / 2 + 60, y + 32), fill=GREEN)
    y += 64
    for i, t in enumerate(righe[:4]):
        fnt = fit_font(d, t, FONT_B if i == 0 else FONT_M, 38 if i == 0 else 33, W - 2 * 70, 24)
        center(d, y, t, fnt, INK if i == 0 else GREY)
        y += 56
    by = max(y + 30, 960)
    d.rounded_rectangle((190, by, 890, by + 80), radius=40, fill=GREEN)
    center(d, by + 14, "Prendi un appuntamento", font(FONT_B, 36), "white")
    center(d, by + 135, config.ADDRESS, fit_font(d, config.ADDRESS, FONT_B, 32, W - 140), INK)
    center(d, by + 183, "Ognuno lavora in autonomia", font(FONT_M, 28), (110, 110, 110))
    if prezzo:
        center(d, H - 70, config.PRICE_LINE, font(FONT_M, 24), LIGHT)
    return im


def render_slides(draft: dict, photos: dict) -> list:
    """photos: id foto -> immagine (bytes). Restituisce la lista di immagini PIL."""
    out = []
    for s in draft["slides"]:
        t = s["tipo"]
        if t == "copertina":
            out.append(slide_cover(load_photo(photos[s["foto"]]), s["righe"], s.get("sottotitolo", "")))
        elif t == "foto":
            out.append(slide_photo(load_photo(photos[s["foto"]]), s.get("etichetta", ""), s.get("testo", "")))
        elif t == "testo":
            out.append(slide_text(s["titolo"], s["punti"]))
        elif t == "finale":
            out.append(slide_final(s["titolo"], s.get("righe", []), bool(s.get("prezzo"))))
    return out


def to_jpeg(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92, subsampling=0)
    return buf.getvalue()
