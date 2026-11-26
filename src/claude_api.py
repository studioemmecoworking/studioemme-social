"""Claude (API Anthropic): descrive le foto nuove e scrive le bozze dei post."""
import json
import re

from . import config
from .util import ApiError, as_json, http

API_URL = "https://api.anthropic.com/v1/messages"


def ask(system: str, content: list, max_tokens: int = 3000) -> str:
    r = http("POST", API_URL, headers={
        "x-api-key": config.env("ANTHROPIC_API_KEY"),
        "anthropic-version": config.ANTHROPIC_VERSION,
        "content-type": "application/json",
    }, json={
        "model": config.MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": content}],
    }, timeout=180)
    j = as_json(r, "Claude")
    if "error" in j:
        raise ApiError(f"Claude: {j['error'].get('message')}")
    parts = [b.get("text", "") for b in j.get("content", []) if b.get("type") == "text"]
    return "".join(parts)


def extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ApiError("Claude non ha risposto con un JSON valido.")
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        raise ApiError("Claude ha risposto con un JSON non leggibile.")


CLASSIFY_SYSTEM = (
    "Descrivi una foto dello studio Studio Emme (coworking per professionisti della salute) "
    "per un archivio. Rispondi SOLO con un JSON con questi campi: "
    '"descrizione" (una frase in italiano, cosa si vede, max 140 caratteri), '
    '"soggetto" (uno tra: studio1, studio3, sala_attesa, antibagno, ingresso, esterno, strada, '
    'parcheggio, dettaglio, disponibilita, recensioni, persone, altro), '
    '"qualita" (intero da 1 a 5: nitidezza, luce, ordine, inquadratura), '
    '"persone" (true se compaiono persone riconoscibili), '
    '"verticale" (true se e\' piu\' alta che larga). '
    "Lo studio 1 e' la stanza piccola con una sola finestra; lo studio 3 e' la stanza grande "
    "con due finestroni e lettino elettrico. "
    "Se e' una tabella o schermata di agenda, soggetto 'disponibilita'; se sono frasi o "
    "recensioni, 'recensioni'."
)


def classify_image(url: str) -> dict:
    text = ask(CLASSIFY_SYSTEM, [
        {"type": "image", "source": {"type": "url", "url": url}},
        {"type": "text", "text": "Descrivi questa foto."},
    ], max_tokens=400)
    j = extract_json(text)
    return {
        "descrizione": str(j.get("descrizione", ""))[:200],
        "soggetto": str(j.get("soggetto", "altro")),
        "qualita": int(j.get("qualita", 3) or 3),
        "persone": bool(j.get("persone", False)),
        "verticale": bool(j.get("verticale", False)),
    }


WRITER_RULES = """
Sei l'assistente social di Studio Emme. Scrivi la bozza di UN post Instagram seguendo il brief del brand e le regole.

REGOLE DURE (un controllo automatico le verifica, se le violi la bozza viene scartata):
- Dai del "tu". Frasi corte, concrete, niente gergo da marketing. Non usare il trattino lungo (—) ne' il trattino medio (–).
- Studio Emme e' un COWORKING, mai "studio medico", "poliambulatorio", "ambulatorio", "clinica", "centro medico". Non usare parole come "terapia", "trattamento", "risultati", "visita guidata" ne' "senza vincoli" (il contratto e' semestrale: l'appuntamento per visitare lo studio e' "senza impegno", il contratto no). Nello studio lavorano anche due nutrizionisti (il titolare e Cristiana): se il tema lo permette si possono citare come valore (due nutrizionisti non in competizione), senza cercarne altri come inquilini.
- Il prezzo compare SOLO se il post ha "prezzo": true, mai in copertina ne' in titoli, e sempre come "a partire da 180 € al mese". Se il post ha "prezzo": false non scrivere cifre, ne' "€", ne' "euro".
- Indirizzo, se lo scrivi: via Cardinal Ferrari 26, Cavaria (VA). Zona: stazione a circa 600 metri a piedi, molto parcheggio.
- Nessuna promessa o consiglio sanitario ai pazienti. Persone riconoscibili e nomi di professionisti solo se il post lo consente (campo "persone_ok") e solo per chi ha dato il consenso nel brief; frasi dei professionisti solo se leggibili nel materiale fornito.
- L'unico invito finale e' sempre: prendi un appuntamento per visitare lo studio, senza impegno (si scrive in direct). Non dire "visita guidata".
- Non inventare nulla: orari di chiusura, date, disponibilita' o frasi che non ti sono state date. Se ti servono dati che non hai, usa formule generiche e scrivi la domanda in "note_per_utente".
- Usa solo foto dell'elenco, indicate con il loro id (es. "F012"). Scegli quelle con qualita' piu' alta e adatte al tema; nello stesso carosello non ripetere la stessa foto.
- Didascalia: 350-1400 caratteri; prima riga forte e chiara (e' quella che si legge prima del "altro..."); un solo invito finale; da 6 a 9 hashtag, partendo da quelli base. Al massimo un'emoji in tutto il post.

FORMATO DI RISPOSTA: SOLO un JSON, senza altro testo, con questi campi:
{
  "slides": [ ... ],
  "video": "<id del video, solo per i reel>",
  "didascalia": "...",
  "note_per_utente": "una riga, oppure stringa vuota"
}
Tipi di slide ammessi (per "carosello" da 4 a 8 slide; per "foto" una sola slide di tipo copertina o foto; per "reel" nessuna slide):
 {"tipo":"copertina","foto":"F001","righe":["IL TUO STUDIO,","PRONTO ALL'USO"],"sottotitolo":"..."}   (righe: 1-3, max 22 caratteri l'una; sottotitolo max 60)
 {"tipo":"foto","foto":"F002","etichetta":"STUDIO 3","testo":"Lettino elettrico, luce naturale"}   (etichetta max 18, testo max 40)
 {"tipo":"testo","titolo":"...","punti":["...","..."]}   (titolo max 50; da 2 a 5 punti, max 70 caratteri l'uno)
 {"tipo":"finale","titolo":"Visita lo studio, senza impegno","righe":["..."],"prezzo":false}   (righe: 2-4, max 55 caratteri; "prezzo": true solo se il post lo prevede; ultima slide)
Nel carosello la prima slide e' una copertina, l'ultima e' una "finale".
"""


def _asset_lines(photos: list) -> str:
    rows = []
    for p in photos:
        flag = "verticale" if p.get("verticale") else "orizzontale"
        code = f" codice {p['codice']}" if p.get("codice") else ""
        rows.append(f"{p['sid']} | {p['soggetto']}{code} | q{p['qualita']} | {flag} | {p['descrizione']}")
    return "\n".join(rows) if rows else "(nessuna foto disponibile)"


def write_draft(entry: dict, brief: str, photos: list, videos: list, evidence: list,
                instruction: str = "", previous: dict = None, errors: list = None) -> dict:
    """evidence: immagini (url) di materiale da leggere, come la tabella delle disponibilita'."""
    spec = {k: entry.get(k) for k in ("data", "linea", "formato", "tema", "prezzo", "note")}
    parts = [
        f"BRIEF DEL BRAND\n{brief}",
        f"POST DA SCRIVERE\n{json.dumps(spec, ensure_ascii=False)}",
        f"HASHTAG BASE: {' '.join(config.HASHTAGS_BASE)}",
        "FOTO DISPONIBILI (id | soggetto | qualita' | orientamento | descrizione)\n" + _asset_lines(photos),
    ]
    if videos:
        parts.append("VIDEO DISPONIBILI (id | nome)\n" + "\n".join(f"{v['sid']} | {v['nome']}" for v in videos))
    if entry.get("materiale"):
        parts.append("Materiale richiesto dal piano (usalo in priorita'): " + ", ".join(entry["materiale"]))
    if previous:
        parts.append("BOZZA PRECEDENTE\n" + json.dumps(previous, ensure_ascii=False))
    if instruction:
        parts.append("MODIFICA RICHIESTA DALL'UTENTE (applicala)\n" + instruction)
    if errors:
        parts.append("PROBLEMI DELLA VERSIONE PRECEDENTE DA CORREGGERE\n- " + "\n- ".join(errors))
    content = [{"type": "text", "text": "\n\n".join(parts)}]
    for ev in evidence:
        content.append({"type": "image", "source": {"type": "url", "url": ev}})
    if evidence:
        content.append({"type": "text", "text": "Le immagini qui sopra sono materiale da leggere "
                        "(per esempio la tabella delle disponibilita'): usa solo cio' che e' scritto."})
    return extract_json(ask(WRITER_RULES, content, max_tokens=3500))
