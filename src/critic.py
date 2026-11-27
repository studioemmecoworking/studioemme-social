"""Il critico di marketing e grafica: guarda slide e didascalia prima che arrivino su Telegram."""
import base64
import json

from . import claude_api, config
from .util import ApiError

CRITIC_PATH = config.ROOT / "brand" / "critico.md"

OUTPUT_RULES = """
Usa la scheda a punti qui sopra per ragionare, poi rispondi SOLO con un JSON (non con lo schema a testo) con questi campi:
"punteggio" (intero da 1 a 10),
"giudizio" (una o due frasi in italiano, max 220 caratteri, il succo per il titolare),
"problemi" (elenco di frasi brevi; vuoto se il post e' buono),
"istruzioni" (testo per il redattore con le correzioni precise da fare, citando slide o foto;
stringa vuota se il punteggio e' 7 o piu').
Se scatta un controllo bloccante, il punteggio e' al massimo 4 e il primo problema lo dice.
Le slide non devono avere numerazione ne' nome del profilo (@): se compaiono, segnalalo.
Le regole del brief valgono sempre e hanno la precedenza su ogni tuo gusto personale.
"""


STORY_RULES = """
Questo contenuto e' una STORIA Instagram (1080x1920), non un carosello: valuta con questi criteri al posto
dei punti 2 e 6 della scheda. Testo dentro la zona sicura (fra y 250 e y 1600), una sola idea, logo
trasparente e non in un riquadro bianco, aspetto caldo e non freddo, elementi festivi se e' una festivita',
nessuna promessa non presente nel brief. Se serve uno sticker (sondaggio, domanda), il testo deve lasciargli spazio.
"""

FINISHED_RULES = """
Questa e' una grafica gia' finita (non disegnata dal programma): guardala come la vedrebbe un professionista
sul telefono e valuta solo cio' che si vede.
"""


def _judge(rules: str, content: list):
    j = claude_api.extract_json(claude_api.ask(rules + "\n" + OUTPUT_RULES, content, max_tokens=900))
    score = int(j.get("punteggio", 0))
    if not 1 <= score <= 10:
        return None
    return {"punteggio": score, "giudizio": str(j.get("giudizio", "")).strip()[:300],
            "problemi": [str(p) for p in j.get("problemi", [])][:8],
            "istruzioni": str(j.get("istruzioni", "")).strip()}


def _image_block(img) -> dict:
    """Un'immagine puo' arrivare come indirizzo web o come byte (per esempio una grafica esportata da Canva)."""
    if isinstance(img, (bytes, bytearray)):
        media = "image/png" if bytes(img[:4]) == b"\x89PNG" else "image/jpeg"
        return {"type": "image", "source": {"type": "base64", "media_type": media,
                                            "data": base64.b64encode(bytes(img)).decode()}}
    return {"type": "image", "source": {"type": "url", "url": img}}


REEL_CRITIC_RULES = """
Questo contenuto e' un REEL gia' montato, non un carosello: al posto dei punti 2 e 3 della scheda usa le
regole di montaggio qui sotto. Le immagini sono fotogrammi del video: il primo e' il fotogramma iniziale (che fa
anche da copertina), poi uno per ogni scena e l'ultimo e' la schermata finale. Controlla che il gancio si legga
gia' nel primo fotogramma, che le scritte siano brevi, accattivanti e leggibili, che le immagini AI diano solo
contesto e non sembrino lo studio, che non ci siano scritte o persone inventate nelle immagini AI, che le foto
siano belle e varie. Nelle "istruzioni" indica cosa cambiare nella scaletta (scene, righe, inquadrature con id
o descrizione AI): il redattore riscrive la scaletta e il programma rimonta il video.
"""


def review(entry: dict, draft: dict, image_urls: list, brief: str, outline: str = ""):
    """Restituisce il giudizio, oppure None se il critico non e' riuscito (il post prosegue comunque).
    Per i reel image_urls sono i fotogrammi del video montato (byte) e outline la scaletta in parole."""
    try:
        rules = CRITIC_PATH.read_text(encoding="utf-8")
        is_reel = entry.get("formato") == "reel"
        if is_reel:
            montaggio = (config.ROOT / "brand" / "montaggio.md").read_text(encoding="utf-8")
            rules += REEL_CRITIC_RULES + "\nREGOLE DI MONTAGGIO\n" + montaggio
        spec = {k: entry.get(k) for k in ("data", "linea", "formato", "tema", "obiettivo", "prezzo", "note")}
        shown = draft.get("reel") if is_reel else draft.get("slides")
        text = "\n\n".join([
            f"BRIEF DEL BRAND\n{brief}",
            f"POST\n{json.dumps(spec, ensure_ascii=False)}",
            f"{'SCALETTA DEL REEL' if is_reel else 'TESTI DELLE SLIDE'} (JSON)\n{json.dumps(shown, ensure_ascii=False)}",
            f"SCALETTA IN PAROLE\n{outline}" if outline else "",
            f"DIDASCALIA\n{draft.get('didascalia', '')}",
            ("Qui sotto ci sono i fotogrammi del reel, nell'ordine." if is_reel else
             "Qui sotto ci sono le slide gia' disegnate, nell'ordine di uscita.") if image_urls
            else "Il contenuto visivo non e' disponibile: valuta solo i testi.",
        ])
        content = [{"type": "text", "text": text}] + [_image_block(u) for u in image_urls]
        return _judge(rules, content)
    except (ApiError, ValueError, TypeError, OSError):
        return None


def review_images(kind: str, title: str, images: list, brief: str, caption: str = ""):
    """Giudizio su qualunque contenuto che sta per andare su Telegram: storie, grafiche Canva gia' finite,
    caroselli esportati. kind: "storia" o "grafica". images: indirizzi web o byte.
    Restituisce il giudizio oppure None (il contenuto prosegue comunque)."""
    try:
        rules = CRITIC_PATH.read_text(encoding="utf-8")
        rules += STORY_RULES if kind == "storia" else FINISHED_RULES
        text = "\n\n".join([f"BRIEF DEL BRAND\n{brief}", f"CONTENUTO ({kind})\n{title}",
                             f"DIDASCALIA\n{caption}" if caption else "Nessuna didascalia: valuta solo l'immagine.",
                             "Qui sotto ci sono le immagini, nell'ordine di uscita."])
        content = [{"type": "text", "text": text}] + [_image_block(u) for u in images]
        return _judge(rules, content)
    except (ApiError, ValueError, TypeError, OSError):
        return None
