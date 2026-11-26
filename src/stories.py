"""Storie Instagram 1080x1920: festivita', ganci dei post e domande della settimana.

Le storie con sondaggi, domande o quiz richiedono lo sticker: l'API di Instagram non li accetta,
quindi l'immagine viene preparata qui e lo sticker si aggiunge a mano (1 minuto).
Le storie senza sticker si possono pubblicare in automatico.
"""
import json
import random

from PIL import Image, ImageDraw, ImageOps

from . import config
from .render import DARK, FONT_B, FONT_M, GREEN, font, fit_font, load_photo, logo_image, wrap

SW, SH = 1080, 1920
SAFE_TOP, SAFE_BOTTOM = 250, 1600       # fuori da qui coprono la barra del profilo e quella delle risposte
MINT = (222, 245, 232)
STORIES_PATH = config.ROOT / "piano" / "storie.json"


def load_stories(path=STORIES_PATH) -> list:
    return json.loads(path.read_text(encoding="utf-8"))


def _cover(photo: Image.Image) -> Image.Image:
    return ImageOps.fit(photo, (SW, SH), Image.LANCZOS, centering=(0.5, 0.5))


def _dim(im: Image.Image, strength=150) -> Image.Image:
    ov = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for y in range(SH):
        t = abs(y - SH * 0.55) / (SH * 0.55)
        d.line((0, y, SW, y), fill=(0, 0, 0, int(strength * (0.45 + 0.55 * min(t, 1)))))
    return Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")


def _dots(d: ImageDraw.ImageDraw, x0, y0, cols, rows, step=34, r=5):
    for i in range(cols):
        for j in range(rows):
            d.ellipse((x0 + i * step - r, y0 + j * step - r, x0 + i * step + r, y0 + j * step + r), fill=GREEN)


def _logo_top(im: Image.Image, width=300):
    logo = logo_image(width)
    box = Image.new("RGB", (logo.width + 40, logo.height + 20), "white")
    box.paste(logo, (20, 10))
    mask = Image.new("L", box.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, box.width, box.height), radius=26, fill=255)
    im.paste(box, ((SW - box.width) // 2, SAFE_TOP - 10), mask)


def _title_block(d, text, y, size, fill_a, fill_b, max_w=SW - 2 * 90, line_gap=1.08):
    """Titolo grande in maiuscolo; l'ultima riga prende il colore di evidenza."""
    fnt = font(FONT_B, size)
    lines = wrap(d, text.upper(), fnt, max_w)[:5]
    while len(lines) > 4 or any(d.textlength(l, font=fnt) > max_w for l in lines):
        size -= 4
        fnt = font(FONT_B, size)
        lines = wrap(d, text.upper(), fnt, max_w)[:5]
    for i, ln in enumerate(lines):
        w = d.textlength(ln, font=fnt)
        d.text(((SW - w) / 2, y + i * size * line_gap), ln, font=fnt,
               fill=fill_b if i == len(lines) - 1 and len(lines) > 1 else fill_a)
    return y + len(lines) * size * line_gap


def story_cartolina(frame: dict, photo: Image.Image) -> Image.Image:
    im = _dim(_cover(photo))
    _logo_top(im)
    d = ImageDraw.Draw(im)
    y = _title_block(d, frame["titolo"], 820, 112, "white", GREEN)
    d.rectangle((SW / 2 - 70, y + 44, SW / 2 + 70, y + 52), fill=GREEN)
    if frame.get("sottotitolo"):
        fnt = fit_font(d, frame["sottotitolo"], FONT_M, 44, SW - 160, 28)
        w = d.textlength(frame["sottotitolo"], font=fnt)
        d.text(((SW - w) / 2, y + 86), frame["sottotitolo"], font=fnt, fill="white")
    return im


def story_domanda(frame: dict, photo=None) -> Image.Image:
    """Fondo verde chiaro, titolo scuro e spazio libero al centro per lo sticker."""
    im = Image.new("RGB", (SW, SH), MINT)
    d = ImageDraw.Draw(im)
    d.ellipse((SW - 520, SH - 760, SW + 360, SH + 120), fill=(196, 236, 214))
    _dots(d, 90, 1180, 6, 5)
    _logo_top(im)
    d = ImageDraw.Draw(im)
    y = _title_block(d, frame["titolo"], 600, 100, DARK, DARK, line_gap=1.1)
    d.rectangle((SW / 2 - 70, y + 30, SW / 2 + 70, y + 38), fill=GREEN)
    if frame.get("sottotitolo"):
        fnt = fit_font(d, frame["sottotitolo"], FONT_M, 40, SW - 160, 28)
        w = d.textlength(frame["sottotitolo"], font=fnt)
        d.text(((SW - w) / 2, SAFE_BOTTOM - 80), frame["sottotitolo"], font=fnt, fill=DARK)
    return im


LAYOUTS = {"cartolina": story_cartolina, "domanda": story_domanda}


def pick_photo(catalog_photos: list, soggetto: str, used: set):
    """catalog_photos: lista di foto del catalogo; sceglie la migliore per soggetto, senza persone."""
    pool = [a for a in catalog_photos if a["soggetto"] == soggetto and not a["persone"] and a["sid"] not in used]
    if not pool:
        pool = [a for a in catalog_photos if not a["persone"] and a["sid"] not in used]
    if not pool:
        return None
    pool.sort(key=lambda a: (-a["qualita"], a["sid"]))
    return pool[0]


def render_frame(frame: dict, photo_bytes: bytes = None) -> Image.Image:
    photo = load_photo(photo_bytes) if photo_bytes else None
    if frame["layout"] == "cartolina" and photo is None:
        raise ValueError("La storia 'cartolina' richiede una foto.")
    return LAYOUTS[frame["layout"]](frame, photo)


def sticker_help(frame: dict) -> str:
    """Istruzioni per aggiungere a mano lo sticker, da mandare con l'immagine su Telegram."""
    st = frame.get("sticker")
    if not st:
        return ""
    if st["tipo"] == "sondaggio":
        return f"Sticker Sondaggio: \"{st['domanda']}\" | {st['opzioni'][0]} / {st['opzioni'][1]}"
    if st["tipo"] == "quiz":
        ok = st["opzioni"][st["corretta"]]
        return f"Sticker Quiz: \"{st['domanda']}\" | {' / '.join(st['opzioni'])} (giusta: {ok})"
    return f"Sticker Domande: \"{st['testo']}\""
