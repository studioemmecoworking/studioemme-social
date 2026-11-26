"""Il critico di marketing e grafica: guarda slide e didascalia prima che arrivino su Telegram."""
import json

from . import claude_api, config
from .util import ApiError

CRITIC_PATH = config.ROOT / "brand" / "critico.md"

OUTPUT_RULES = """
Rispondi SOLO con un JSON con questi campi:
"punteggio" (intero da 1 a 10),
"giudizio" (una o due frasi in italiano, max 220 caratteri, il succo per il titolare),
"problemi" (elenco di frasi brevi; vuoto se il post e' buono),
"istruzioni" (testo per il redattore con le correzioni precise da fare, citando slide o foto;
stringa vuota se il punteggio e' 7 o piu').
Le regole del brief valgono sempre e hanno la precedenza su ogni tuo gusto personale.
"""


def review(entry: dict, draft: dict, image_urls: list, brief: str):
    """Restituisce il giudizio, oppure None se il critico non e' riuscito (il post prosegue comunque)."""
    try:
        rules = CRITIC_PATH.read_text(encoding="utf-8")
        spec = {k: entry.get(k) for k in ("data", "linea", "formato", "tema", "obiettivo", "prezzo", "note")}
        text = "\n\n".join([
            f"BRIEF DEL BRAND\n{brief}",
            f"POST\n{json.dumps(spec, ensure_ascii=False)}",
            f"TESTI DELLE SLIDE (JSON)\n{json.dumps(draft.get('slides', draft.get('video')), ensure_ascii=False)}",
            f"DIDASCALIA\n{draft.get('didascalia', '')}",
            "Qui sotto ci sono le slide gia' disegnate, nell'ordine di uscita." if image_urls
            else "Questo e' un reel: valuta solo i testi, il video non e' visibile.",
        ])
        content = [{"type": "text", "text": text}]
        for url in image_urls:
            content.append({"type": "image", "source": {"type": "url", "url": url}})
        j = claude_api.extract_json(claude_api.ask(rules + "\n" + OUTPUT_RULES, content, max_tokens=900))
        score = int(j.get("punteggio", 0))
        if not 1 <= score <= 10:
            return None
        return {"punteggio": score, "giudizio": str(j.get("giudizio", "")).strip()[:300],
                "problemi": [str(p) for p in j.get("problemi", [])][:8],
                "istruzioni": str(j.get("istruzioni", "")).strip()}
    except (ApiError, ValueError, TypeError, OSError):
        return None
