"""Il ciclo automatico: legge le tue risposte su Telegram, pubblica i post approvati,
prepara le nuove bozze e ti avvisa se manca del materiale."""
from datetime import date, datetime, timedelta

from . import catalog as cat
from . import claude_api, cloudinary_api, config, critic, instagram, lint, reel, render, telegram_api as tg
from .util import ApiError, http, load_json, redact, save_json

STATE_PATH = config.ROOT / "stato" / "stato.json"
CALENDAR_PATH = config.ROOT / "piano" / "calendario.json"
MATERIALS_PATH = config.ROOT / "piano" / "materiali.json"
BRIEF_PATH = config.ROOT / "brand" / "brief.md"

OPEN_STATES = ("pianificato", "manca_materiale")


# ---------------------------------------------------------------- stato

def load_state() -> dict:
    return load_json(STATE_PATH, {"posts": {}, "telegram_offset": 0, "in_attesa_modifica": None,
                                  "ultimo_battito": ""})


def save_state(state: dict) -> None:
    save_json(STATE_PATH, state)


def post_state(state: dict, entry_id: str) -> dict:
    return state["posts"].setdefault(entry_id, {"stato": "pianificato", "revisioni": 0})


def calendar() -> list:
    return load_json(CALENDAR_PATH, [])


def materials_info() -> dict:
    return load_json(MATERIALS_PATH, {})


def entry_by_id(entry_id: str):
    return next((e for e in calendar() if e["id"] == entry_id), None)


def publish_moment(entry: dict) -> datetime:
    d = date.fromisoformat(entry["data"])
    return datetime(d.year, d.month, d.day, *config.PUBLISH_TIME, tzinfo=config.TZ)


def label(entry: dict) -> str:
    d = date.fromisoformat(entry["data"])
    return f"{config.data_it(d)} ({entry['linea']}, {entry['formato']})"


# ---------------------------------------------------------------- materiale

def missing_materials(entry: dict, catalog: dict) -> list:
    """Elenco di codici mancanti, con indicazione del tipo (foto o video)."""
    missing = []
    for code in entry.get("materiale", []):
        # nei reel montati vanno bene sia i video sia le foto con il codice richiesto
        tipo = None if entry["formato"] == "reel" else "foto"
        found = [a for a in cat.with_code(catalog, code, tipo) if a["tipo"] != "audio"]
        if code == "M13":
            found = [a for a in found if cat.age_days(a) <= config.M13_MAX_AGE_DAYS]
        if not found:
            missing.append(code)
    return missing


def describe_missing(codes: list) -> str:
    info = materials_info()
    lines = []
    for c in codes:
        m = info.get(c, {})
        lines.append(f"- {c}: {m.get('nome', 'materiale')}. {m.get('come', '')}".strip())
    return "\n".join(lines)


# ---------------------------------------------------------------- bozze

class DraftError(Exception):
    pass


def make_draft(entry: dict, catalog: dict, instruction: str = "", previous: dict = None) -> dict:
    brief = BRIEF_PATH.read_text(encoding="utf-8")
    photos = cat.photos(catalog)
    videos = cat.videos(catalog) if entry["formato"] == "reel" else []
    evidence = []
    for code in entry.get("materiale", []):
        if code in ("M13", "M11"):
            for a in cat.with_code(catalog, code, "foto"):
                evidence.append(cloudinary_api.transform_url(a["url"], "c_limit,w_1600,q_auto:good"))
    # le foto con il codice richiesto devono poter essere scelte anche se la qualita' e' bassa
    for code in entry.get("materiale", []):
        for a in cat.with_code(catalog, code, "foto"):
            if a not in photos and a["soggetto"] not in ("disponibilita", "recensioni"):
                photos.append(a)
    errors = []
    draft = None
    for _ in range(3):
        draft = claude_api.write_draft(entry, brief, photos, videos, evidence, instruction,
                                       previous, errors)
        draft = lint.clean(draft)
        errors = lint.check(draft, entry, catalog)
        if not errors:
            return draft
    raise DraftError("; ".join(errors[:6]))


def build_assets(entry: dict, draft: dict, catalog: dict, version) -> dict:
    """Crea le immagini (o sceglie il video), le carica e restituisce gli indirizzi pubblici."""
    if entry["formato"] == "reel":
        return reel.build(entry, draft, catalog, version)
    photo_bytes = {}
    for s in draft["slides"]:
        if s["tipo"] in ("copertina", "foto") and s["foto"] not in photo_bytes:
            a = cat.by_sid(catalog, s["foto"])
            url = cloudinary_api.transform_url(a["url"], "c_limit,w_2000")
            photo_bytes[s["foto"]] = http("GET", url).content
    images = render.render_slides(draft, photo_bytes)
    urls, ids = [], []
    for i, im in enumerate(images, 1):
        pid = f"{config.PREVIEW_PREFIX}/{entry['id']}_v{version}_{i}"
        res = cloudinary_api.upload_bytes(render.to_jpeg(im), pid)
        urls.append(res["secure_url"])
        ids.append(res["public_id"])
    return {"video": "", "anteprima_video": "", "immagini": urls, "public_ids": ids}


def send_preview(entry: dict, draft: dict, assets: dict, review: dict = None, rounds: int = 0) -> int:
    head = f"Bozza per {label(entry)}\nUscita prevista: {config.data_it(date.fromisoformat(entry['data']))} alle " \
           f"{config.PUBLISH_TIME[0]}:{config.PUBLISH_TIME[1]:02d}"
    if assets["immagini"]:
        tg.send_photos(assets["immagini"])
    elif assets.get("video"):
        send_reel_video(assets)
    text = f"{head}\n\nDidascalia:\n{draft['didascalia']}"
    if assets.get("scaletta"):
        text += f"\n\nScaletta del montaggio:\n{assets['scaletta']}"
    if assets.get("ai"):
        text += "\n\nContiene immagini generate con l'AI: alla pubblicazione il reel viene segnato come contenuto AI."
    for n in assets.get("note_montaggio") or []:
        text += f"\nNota sul montaggio: {n}"
    if draft.get("note_per_utente"):
        text += f"\n\nDa controllare: {draft['note_per_utente']}"
    if review:
        corrected = f" (corretta {rounds} {'volta' if rounds == 1 else 'volte'})" if rounds else ""
        text += f"\n\nGiudizio del critico: {review['punteggio']}/10{corrected}. {review['giudizio']}"
    eid = entry["id"]
    msg = tg.send_message(text, buttons=[
        [{"text": "✅ Approva", "callback_data": f"ok:{eid}"},
         {"text": "✏️ Modifica", "callback_data": f"mod:{eid}"}],
        [{"text": "⏭ Salta questo post", "callback_data": f"skip:{eid}"}],
    ])
    return msg["message_id"]


def send_reel_video(assets: dict, caption: str = "Il reel montato") -> None:
    for url in (assets["video"], assets.get("anteprima_video")):
        if not url:
            continue
        try:
            tg.send_video(url, caption)
            return
        except ApiError:
            continue
    tg.send_message("Il video è troppo pesante per Telegram, lo vedi qui: " + assets["video"])


def _review(entry: dict, draft: dict, assets: dict, brief: str):
    if entry["formato"] == "reel":
        return critic.review(entry, draft, assets.get("fotogrammi") or [], brief,
                             outline=assets.get("scaletta", ""))
    return critic.review(entry, draft, assets["immagini"], brief)


def refine(entry: dict, catalog: dict, draft: dict, assets: dict, version: int):
    """Il critico guarda la bozza gia' disegnata e, se il voto e' basso, la fa correggere (al massimo
    CRITIC_MAX_LOOPS volte). Restituisce (bozza, grafiche, giudizio, giri) della versione migliore."""
    brief = BRIEF_PATH.read_text(encoding="utf-8")
    tried = []          # (bozza, grafiche, giudizio)
    for i in range(config.CRITIC_MAX_LOOPS + 1):
        review = _review(entry, draft, assets, brief)
        tried.append((draft, assets, review))
        if review is None or review["punteggio"] >= config.CRITIC_MIN_SCORE or i == config.CRITIC_MAX_LOOPS \
                or not review["istruzioni"]:
            break
        try:
            draft = make_draft(entry, catalog, review["istruzioni"], draft)
            assets = build_assets(entry, draft, catalog, f"{version}c{i + 1}")
        except (DraftError, ApiError):
            break
    scored = [t for t in tried if t[2]]
    best = max(scored, key=lambda t: t[2]["punteggio"]) if scored else tried[-1]
    for t in tried:
        if t is not best:
            for pid in t[1]["public_ids"]:
                _safe_destroy(pid)
    return best[0], best[1], best[2], tried.index(best)


def prepare_entry(state: dict, catalog: dict, entry: dict, instruction: str = "") -> None:
    ps = post_state(state, entry["id"])
    previous = ps.get("bozza") if instruction else None
    try:
        draft = make_draft(entry, catalog, instruction, previous)
    except DraftError as e:
        ps["stato"] = "errore_bozza"
        tg.send_message(f"Non sono riuscito a preparare la bozza per {label(entry)}: i controlli "
                        f"automatici hanno scartato i testi ({redact(e)}). Riprovo al prossimo giro "
                        f"se scrivi /riprova {entry['id']}.")
        return
    ps["revisioni"] = ps.get("revisioni", 0) + (1 if instruction else 0)
    version = ps["revisioni"] + 1
    assets = build_assets(entry, draft, catalog, version)
    draft, assets, review, rounds = refine(entry, catalog, draft, assets, version)
    old_ids = ps.get("public_ids", [])
    ps.update({"bozza": draft, "immagini": assets["immagini"], "video": assets["video"],
               "copertina": assets.get("copertina", ""), "ai": bool(assets.get("ai")),
               "public_ids": assets["public_ids"], "stato": "bozza_inviata", "errori": 0,
               "critico": {"punteggio": review["punteggio"], "giudizio": review["giudizio"],
                           "giri": rounds} if review else None})
    ps["messaggio"] = send_preview(entry, draft, assets, review, rounds)
    for pid in old_ids:
        _safe_destroy(pid)


def _safe_destroy(pid: str) -> None:
    kind = "image"
    if pid.startswith("video:"):
        kind, pid = "video", pid[len("video:"):]
    try:
        cloudinary_api.destroy(pid, resource_type=kind)
    except ApiError:
        pass


# ---------------------------------------------------------------- ciclo

def prepare_due(state: dict, catalog: dict) -> None:
    today = config.now().date()
    for entry in calendar():
        ps = post_state(state, entry["id"])
        if ps["stato"] not in OPEN_STATES:
            continue
        d = date.fromisoformat(entry["data"])
        if d < today:
            ps["stato"] = "scaduto"
            tg.send_message(f"Il post {label(entry)} non è uscito perché non era pronto in tempo. "
                            "Lo salto: se vuoi recuperarlo dimmelo e lo spostiamo nel calendario.")
            continue
        if (d - today).days > config.PREPARE_DAYS_AHEAD:
            continue
        missing = [] if ps.get("forza") else missing_materials(entry, catalog)
        if missing:
            last = ps.get("ultimo_avviso", "")
            if not last or (config.now() - datetime.fromisoformat(last)) > timedelta(hours=48):
                tg.send_message(
                    f"Per il post {label(entry)} mi manca del materiale:\n{describe_missing(missing)}\n\n"
                    "Caricalo nella cartella \"libreria\" di Cloudinary, con il codice all'inizio del nome "
                    "del file (per esempio \"M3 tour.mp4\"). Appena c'è, preparo la bozza.",
                    buttons=[[{"text": "Prepara con ciò che c'è", "callback_data": f"force:{entry['id']}"},
                              {"text": "⏭ Salta", "callback_data": f"skip:{entry['id']}"}]])
                ps["ultimo_avviso"] = config.now().isoformat()
            ps["stato"] = "manca_materiale"
            continue
        try:
            prepare_entry(state, catalog, entry)
        except ApiError as e:
            ps["errori"] = ps.get("errori", 0) + 1
            if ps["errori"] >= config.MAX_PREPARE_ERRORS:
                ps["stato"] = "errore_bozza"
                tg.send_message(f"Non riesco a preparare {label(entry)} ({redact(e)}). Mi fermo per non "
                                f"sprecare tentativi: quando vuoi riprovare scrivi /riprova {entry['id']}.")
            else:
                ps["stato"] = "pianificato"
                tg.send_message(f"Errore nel preparare {label(entry)}: {redact(e)}. Riprovo tra poco.")


def publish_due(state: dict) -> None:
    now = config.now()
    for entry in calendar():
        ps = post_state(state, entry["id"])
        if ps["stato"] != "approvato":
            continue
        due = publish_moment(entry)
        if now < due:
            continue
        if now - due > timedelta(hours=config.MAX_LATE_HOURS):
            ps["stato"] = "scaduto"
            tg.send_message(f"Il post {label(entry)} era approvato ma l'orario è passato da troppo: "
                            "non l'ho pubblicato.")
            continue
        publish_entry(state, entry)


def publish_entry(state: dict, entry: dict) -> None:
    ps = post_state(state, entry["id"])
    draft = ps["bozza"]
    try:
        if entry["formato"] == "reel":
            res = instagram.publish_reel(ps["video"], draft["didascalia"], cover_url=ps.get("copertina") or None,
                                         ai=bool(ps.get("ai")))
        elif entry["formato"] == "foto":
            res = instagram.publish_image(ps["immagini"][0], draft["didascalia"])
        else:
            res = instagram.publish_carousel(ps["immagini"], draft["didascalia"])
    except ApiError as e:
        ps["stato"] = "errore_pubblicazione"
        extra = ""
        if entry["formato"] == "reel":
            extra = "\nSe il problema sono i video, puoi pubblicarlo a mano dall'app con questa didascalia."
        tg.send_message(f"Non sono riuscito a pubblicare {label(entry)}: {redact(e)}{extra}\n\n"
                        f"Didascalia:\n{draft['didascalia']}",
                        buttons=[[{"text": "🔁 Riprova", "callback_data": f"retry:{entry['id']}"}]])
        return
    ps["stato"] = "pubblicato"
    ps["link"] = res["link"]
    ps["media_id"] = res["id"]
    ps["pubblicato_il"] = config.now().isoformat()
    for pid in ps.get("public_ids", []):
        _safe_destroy(pid)
    extra = ""
    if res.get("etichetta_ai_mancante"):
        extra = ("\nInstagram non ha accettato l'etichetta AI dal programma: aggiungila dall'app "
                 "(modifica il post, Impostazioni avanzate, Etichetta AI).")
    tg.send_message(f"Pubblicato: {label(entry)}\n{res['link']}{extra}")


# ---------------------------------------------------------------- Telegram

def handle_callback(state: dict, catalog: dict, cq: dict) -> None:
    data = cq.get("data", "")
    action, _, eid = data.partition(":")
    entry = entry_by_id(eid)
    tg.answer_callback(cq["id"])
    if not entry:
        return
    ps = post_state(state, eid)
    msg_id = (cq.get("message") or {}).get("message_id")
    if action == "ok" and ps["stato"] in ("bozza_inviata", "errore_pubblicazione"):
        ps["stato"] = "approvato"
        if msg_id:
            tg.clear_buttons(msg_id)
        tg.send_message(f"Approvato. {label(entry)} uscirà "
                        f"{config.data_it(date.fromisoformat(entry['data']))} alle "
                        f"{config.PUBLISH_TIME[0]}:{config.PUBLISH_TIME[1]:02d}.")
    elif action == "mod" and ps["stato"] == "bozza_inviata":
        if ps.get("revisioni", 0) >= config.MAX_REVISIONS:
            tg.send_message("Abbiamo già fatto 5 modifiche a questo post: approvalo, saltalo o dimmi "
                            "come cambiare il piano.")
            return
        state["in_attesa_modifica"] = eid
        if msg_id:
            tg.clear_buttons(msg_id)
        tg.send_message("Scrivimi cosa vuoi cambiare, con un unico messaggio.")
    elif action == "skip" and ps["stato"] not in ("pubblicato", "saltato"):
        ps["stato"] = "saltato"
        if msg_id:
            tg.clear_buttons(msg_id)
        for pid in ps.get("public_ids", []):
            _safe_destroy(pid)
        tg.send_message(f"Saltato: {label(entry)}.")
    elif action == "force" and ps["stato"] in OPEN_STATES:
        ps["forza"] = True
        ps["stato"] = "pianificato"
        if msg_id:
            tg.clear_buttons(msg_id)
    elif action == "retry" and ps["stato"] == "errore_pubblicazione":
        ps["stato"] = "approvato"
        if msg_id:
            tg.clear_buttons(msg_id)


def handle_message(state: dict, catalog: dict, m: dict) -> None:
    text = (m.get("text") or "").strip()
    chat = str((m.get("chat") or {}).get("id", ""))
    if not tg.chat_id():
        # Primo avvio: rispondo solo a chi scrive, con il suo numero di chat.
        if text.startswith("/start"):
            tg.send_message(f"Ciao! Il tuo numero di chat è {chat}. Salvalo nel segreto di GitHub "
                            "chiamato TELEGRAM_CHAT_ID: poi potrò scriverti le anteprime.", chat=chat)
        return
    if chat != tg.chat_id():
        return  # ignoro chiunque altro
    if text.startswith("/stato"):
        tg.send_message(status_text(state))
        return
    if text.startswith("/start"):
        tg.send_message("Ciao! Ti scrivo qui le bozze dei post e il materiale che mi serve. "
                        "/stato mostra a che punto siamo.")
        return
    pending = state.get("in_attesa_modifica")
    if pending and text and not text.startswith("/"):
        entry = entry_by_id(pending)
        state["in_attesa_modifica"] = None
        if entry:
            tg.send_message("Ricevuto, preparo la nuova versione.")
            try:
                prepare_entry(state, catalog, entry, instruction=text)
            except ApiError as e:
                tg.send_message(f"Errore nel rifare il post: {redact(e)}. La bozza precedente resta valida.")
        return
    if text.startswith("/riprova"):
        eid = text.partition(" ")[2].strip()
        if entry_by_id(eid):
            post_state(state, eid)["stato"] = "pianificato"
            post_state(state, eid)["errori"] = 0
            tg.send_message("Va bene, riprovo.")


def status_text(state: dict) -> str:
    today = config.now().date()
    rows = []
    for e in calendar():
        d = date.fromisoformat(e["data"])
        s = post_state(state, e["id"])["stato"]
        if d >= today - timedelta(days=2) and s not in ("saltato",):
            rows.append(f"{config.data_it(d)}: {e['linea']} ({e['formato']}), {s.replace('_', ' ')}")
        if len(rows) >= 8:
            break
    return "Prossimi post:\n" + ("\n".join(rows) if rows else "nessuno in calendario.")


def process_updates(state: dict, catalog: dict) -> None:
    updates = tg.get_updates(state.get("telegram_offset", 0))
    for u in updates:
        state["telegram_offset"] = u["update_id"] + 1
        if "callback_query" in u:
            cq = u["callback_query"]
            chat = str(((cq.get("message") or {}).get("chat") or {}).get("id", ""))
            if tg.chat_id() and chat == tg.chat_id():
                handle_callback(state, catalog, cq)
        elif "message" in u:
            handle_message(state, catalog, u["message"])


def tick() -> None:
    state = load_state()
    catalog = cat.load()
    try:
        for fase, funzione in (("libreria", lambda: cat.sync(catalog)),
                               ("telegram", lambda: process_updates(state, catalog)),
                               ("pubblicazione", lambda: publish_due(state)),
                               ("bozze", lambda: prepare_due(state, catalog))):
            try:
                funzione()
            except Exception as e:  # una fase che fallisce non deve bloccare le altre
                print(f"Errore nella fase '{fase}': {redact(e)}")
    finally:
        save_state(state)
        cat.save(catalog)


# ---------------------------------------------------------------- promemoria

def remind() -> None:
    """Ogni settimana: materiale che serve nelle prossime settimane e segnale che tutto funziona."""
    state = load_state()
    catalog = cat.load()
    try:
        cat.sync(catalog)
    except ApiError as e:
        print("Avviso:", redact(e))
    today = config.now().date()
    lines, nxt = [], None
    for e in calendar():
        d = date.fromisoformat(e["data"])
        s = post_state(state, e["id"])["stato"]
        if d < today or s in ("pubblicato", "saltato", "scaduto"):
            continue
        if nxt is None:
            nxt = e
        if (d - today).days <= 28:
            miss = missing_materials(e, catalog)
            if miss:
                lines.append(f"{config.data_it(d)}, {e['linea']}:\n{describe_missing(miss)}")
    text = "Promemoria settimanale di Studio Emme.\n"
    if nxt:
        text += f"Prossimo post: {label(nxt)}.\n"
    if lines:
        text += "\nMateriale da preparare nelle prossime 4 settimane:\n\n" + "\n\n".join(lines)
    else:
        text += "\nPer le prossime 4 settimane il materiale c'è tutto."
    tg.send_message(text)
    cat.save(catalog)
    save_state(state)


# ---------------------------------------------------------------- prova del montaggio

def trial_reel(entry_id: str = "") -> None:
    """Monta un reel del calendario e lo manda su Telegram come PROVA: niente pulsanti, niente
    pubblicazione, lo stato dei post non cambia."""
    catalog = cat.load()
    try:
        cat.sync(catalog)
    except ApiError as e:
        print("Avviso:", redact(e))
    reels = [e for e in calendar() if e["formato"] == "reel"]
    today = config.now().date()
    entry = entry_by_id(entry_id) if entry_id else next(
        (e for e in reels if date.fromisoformat(e["data"]) >= today), reels[0] if reels else None)
    if not entry or entry["formato"] != "reel":
        print("Nessun reel da provare con questo id.")
        return
    tg.send_message(f"PROVA del montaggio automatico per {label(entry)}. Non verrà pubblicato: "
                    "serve solo per vedere il risultato. Ci vogliono alcuni minuti.")
    try:
        draft = make_draft(entry, catalog)
        assets = build_assets(entry, draft, catalog, "prova")
        draft, assets, review, rounds = refine(entry, catalog, draft, assets, 0)
    except (DraftError, ApiError) as e:
        tg.send_message(f"PROVA non riuscita: {redact(e)}")
        raise
    send_reel_video(assets, "PROVA: il reel montato")
    text = f"PROVA, {label(entry)}\n\nScaletta del montaggio:\n{assets.get('scaletta', '')}"
    if assets.get("ai"):
        text += "\n\nContiene immagini AI: alla pubblicazione verrebbe segnato come contenuto AI."
    for n in assets.get("note_montaggio") or []:
        text += f"\nNota sul montaggio: {n}"
    if review:
        corr = f" (corretto {rounds} {'volta' if rounds == 1 else 'volte'})" if rounds else ""
        text += f"\n\nGiudizio del critico: {review['punteggio']}/10{corr}. {review['giudizio']}"
    text += f"\n\nDidascalia:\n{draft['didascalia']}\n\nCopertina: {assets.get('copertina', '')}"
    tg.send_message(text)
    print("Reel di prova:", assets["video"])
