"""Controlli automatici sulle bozze: se qualcosa non rispetta il brief, la bozza viene scartata."""
import re

from . import catalog as cat
from . import config

FORBIDDEN = ["studio medico", "poliambulatorio", "ambulatorio", "clinica", "centro medico",
             "guarigione", "guarire", "garantiamo", "garantito", "visita guidata",
             "senza vincol", "terapi", "trattament", "risultati"]
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⬆]")
PRICE_RE = re.compile(r"€|\beuro\b|\b180\b", re.I)
HASHTAG_RE = re.compile(r"#\w+")


def clean(draft: dict) -> dict:
    """Correzioni automatiche: trattini lunghi e spazi."""
    def fix(s):
        if not isinstance(s, str):
            return s
        s = s.replace("—", ",").replace("–", "-")
        return re.sub(r"[ \t]+", " ", s).strip()

    def walk(x):
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return fix(x)

    return walk(draft)


def _texts(draft: dict):
    """(posizione, testo, e_titolo) di ogni testo mostrato o scritto."""
    for i, s in enumerate(draft.get("slides", [])):
        for key in ("righe", "punti"):
            for t in s.get(key, []) or []:
                yield (f"slide {i + 1}", t, key == "righe" and s.get("tipo") != "finale")
        for key in ("sottotitolo", "etichetta", "testo", "titolo"):
            if s.get(key):
                yield (f"slide {i + 1}", s[key], True)
    for i, sc in enumerate((draft.get("reel") or {}).get("scene") or []):
        for t in (sc.get("righe") or []) + ([sc["etichetta"]] if sc.get("etichetta") else []):
            yield (f"scena {i + 1}", str(t), True)
    yield ("didascalia", draft.get("didascalia", ""), False)


def check(draft: dict, entry: dict, catalog: dict) -> list:
    errors = []
    formato = entry["formato"]
    slides = draft.get("slides") or []
    caption = draft.get("didascalia") or ""

    # struttura
    if formato == "reel":
        errors += check_reel(draft.get("reel"), entry, catalog)
        if slides:
            errors.append("Un reel non deve avere slide.")
    elif formato == "foto":
        if len(slides) != 1:
            errors.append("Un post con foto singola ha una sola slide.")
    else:
        if not 6 <= len(slides) <= 10:
            errors.append("Il carosello deve avere da 6 a 10 slide.")
        if len(slides) >= 3 and slides[-2].get("tipo") != "testo":
            errors.append("La penultima slide deve essere un riepilogo (tipo testo) che si possa salvare.")
        if slides and slides[0].get("tipo") != "copertina":
            errors.append("La prima slide del carosello deve essere una copertina.")
        if slides and slides[-1].get("tipo") != "finale":
            errors.append("L'ultima slide del carosello deve essere di tipo finale.")

    # foto
    used = []
    for i, s in enumerate(slides):
        t = s.get("tipo")
        if t not in ("copertina", "foto", "testo", "finale"):
            errors.append(f"Slide {i + 1}: tipo non ammesso.")
            continue
        if t in ("copertina", "foto"):
            a = cat.by_sid(catalog, s.get("foto", ""))
            if not a or a["tipo"] != "foto":
                errors.append(f"Slide {i + 1}: la foto '{s.get('foto')}' non e' nell'elenco.")
            else:
                if a["persone"] and not entry.get("persone_ok"):
                    errors.append(f"Slide {i + 1}: la foto {a['sid']} mostra persone riconoscibili.")
                used.append(a["sid"])
        limits = {"righe": (3 if t == "copertina" else 4, 22 if t == "copertina" else 55),
                  "sottotitolo": (1, 60), "etichetta": (1, 18), "testo": (1, 40),
                  "titolo": (1, 50), "punti": (5, 70)}
        for key, (maxn, maxlen) in limits.items():
            val = s.get(key)
            if val is None:
                continue
            items = val if isinstance(val, list) else [val]
            if len(items) > maxn:
                errors.append(f"Slide {i + 1}: troppi elementi in '{key}'.")
            for it in items:
                if len(str(it)) > maxlen:
                    errors.append(f"Slide {i + 1}: '{str(it)[:25]}...' supera {maxlen} caratteri.")
        if t == "copertina" and not s.get("righe"):
            errors.append("La copertina deve avere 'righe'.")
        if t == "testo" and not 2 <= len(s.get("punti") or []) <= 5:
            errors.append(f"Slide {i + 1}: servono da 2 a 5 punti.")
    if len(used) != len(set(used)):
        errors.append("La stessa foto e' usata piu' volte.")

    # didascalia
    if not 350 <= len(caption) <= 1900:
        errors.append("La didascalia deve essere tra 350 e 1900 caratteri.")
    tags = HASHTAG_RE.findall(caption)
    if not 3 <= len(tags) <= 5:
        errors.append("Servono da 3 a 5 hashtag nella didascalia (Instagram ne ammette al massimo 5).")
    if len(EMOJI_RE.findall(caption + " ".join(t for _, t, _ in _texts(draft)))) > 2:
        errors.append("Troppe emoji (massimo 2).")

    # parole vietate, trattini, prezzo, indirizzo
    for where, text, is_title in _texts(draft):
        low = text.lower()
        for bad in FORBIDDEN:
            if re.search(r"(?<![a-zà-ù])" + re.escape(bad), low):
                errors.append(f"{where}: contiene '{bad}'.")
        if "—" in text or "–" in text:
            errors.append(f"{where}: contiene un trattino lungo.")
        if PRICE_RE.search(text):
            if not entry.get("prezzo"):
                errors.append(f"{where}: il prezzo non e' previsto in questo post.")
            elif is_title:
                errors.append(f"{where}: il prezzo non va in titoli o copertine.")
            else:
                if "a partire da" not in low or not ("al mese" in low or "mensil" in low):
                    errors.append(f"{where}: il prezzo va scritto come 'a partire da 180 € al mese'.")
        m = re.search(r"cardinal ferrari\D{0,6}(\d+)", low)
        if m and m.group(1) != "168":
            errors.append(f"{where}: numero civico sbagliato (e' il 168).")
    if slides:
        if slides[0].get("tipo") == "copertina" and any(
                PRICE_RE.search(str(x)) for x in (slides[0].get("righe") or []) + [slides[0].get("sottotitolo", "")]):
            errors.append("Il prezzo non puo' stare in copertina.")
    fin = [s for s in slides if s.get("tipo") == "finale"]
    if fin and fin[-1].get("prezzo") and not entry.get("prezzo"):
        errors.append("La slide finale mostra il prezzo ma il post non lo prevede.")
    return errors


def _scene_text_errors(i: int, sc: dict) -> list:
    errors = []
    righe = sc.get("righe") or []
    if not 1 <= len(righe) <= 3:
        errors.append(f"Scena {i + 1}: servono da 1 a 3 righe.")
    for r in righe:
        if len(str(r)) > 22:
            errors.append(f"Scena {i + 1}: la riga '{str(r)[:20]}...' supera 20 caratteri.")
    words = " ".join(str(r) for r in righe).split()
    if len(words) > 7:
        errors.append(f"Scena {i + 1}: troppe parole (massimo 6).")
    acc = (sc.get("accento") or "").strip()
    if acc and acc.lower() not in " ".join(str(r) for r in righe).lower():
        errors.append(f"Scena {i + 1}: l'accento '{acc}' non compare nelle righe.")
    if sc.get("etichetta") and len(sc["etichetta"]) > 32:
        errors.append(f"Scena {i + 1}: etichetta troppo lunga (massimo 32 caratteri).")
    return errors


def check_reel(reel, entry: dict, catalog: dict) -> list:
    """Controlli sulla scaletta del reel (vedi brand/montaggio.md)."""
    if not isinstance(reel, dict):
        return ["Per un reel serve il campo 'reel' con la scaletta del montaggio."]
    errors = []
    scenes = reel.get("scene") or []
    tipo = reel.get("tipo")
    if tipo == "parlato":
        v = cat.by_sid(catalog, reel.get("video", ""))
        if not v or v["tipo"] != "video":
            errors.append("Reel parlato: serve 'video' con l'id di un video della libreria.")
        elif v["persone"] and not entry.get("persone_ok"):
            errors.append("Reel parlato: il video mostra persone ma il post non lo consente.")
        if len(scenes) != 1:
            errors.append("Reel parlato: serve una sola scena, il gancio.")
        try:
            da, a = float(reel.get("da") or 0), reel.get("a")
            if a is not None and not 5 <= float(a) - da <= 90:
                errors.append("Reel parlato: la parte scelta deve durare tra 5 e 90 secondi.")
        except (TypeError, ValueError):
            errors.append("Reel parlato: 'da' e 'a' devono essere numeri di secondi.")
    elif tipo == "montaggio":
        if not 4 <= len(scenes) <= 6:
            errors.append("Il reel deve avere da 4 a 6 scene (gancio, idee, chiusura).")
    else:
        return ["Il campo reel.tipo deve essere 'montaggio' o 'parlato'."]
    used, ai, prev_ai = [], 0, False
    for i, sc in enumerate(scenes):
        errors += _scene_text_errors(i, sc)
        if i == 0 and any(PRICE_RE.search(str(r)) for r in sc.get("righe") or []):
            errors.append("Il prezzo non puo' stare nel gancio.")
        if tipo != "montaggio":
            continue
        shots = sc.get("inquadrature") or []
        maxn = 3 if i in (0, len(scenes) - 1) else 2
        if not 1 <= len(shots) <= maxn:
            errors.append(f"Scena {i + 1}: servono da 1 a {maxn} inquadrature.")
        for sh in shots:
            if sh.get("ai"):
                ai += 1
                if prev_ai:
                    errors.append(f"Scena {i + 1}: due immagini AI di fila; alternale con foto vere.")
                prev_ai = True
                if len(str(sh["ai"])) < 25:
                    errors.append(f"Scena {i + 1}: descrivi meglio l'immagine AI (in inglese).")
                continue
            prev_ai = False
            sid = sh.get("foto") or sh.get("video")
            a = cat.by_sid(catalog, sid or "")
            if not a or a["tipo"] not in ("foto", "video"):
                errors.append(f"Scena {i + 1}: '{sid}' non e' nella libreria.")
                continue
            if sh.get("video") and a["tipo"] != "video":
                errors.append(f"Scena {i + 1}: '{sid}' e' una foto, non un video.")
            if sh.get("foto") and a["tipo"] != "foto":
                errors.append(f"Scena {i + 1}: '{sid}' e' un video: usa il campo 'video'.")
            if a["persone"] and not entry.get("persone_ok"):
                errors.append(f"Scena {i + 1}: {sid} mostra persone riconoscibili.")
            if a["tipo"] == "foto":
                used.append(sid)
    if tipo == "montaggio" and ai > 4:
        errors.append("Troppe immagini AI: massimo 4 per reel.")
    if len(used) != len(set(used)):
        errors.append("La stessa foto e' usata piu' volte nel reel.")
    return errors
