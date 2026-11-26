"""Prova completa del ciclo con servizi simulati (nessuna rete, nessuna chiave)."""
import io
import json
from datetime import datetime

import pytest
from PIL import Image

from src import catalog as cat
from src import claude_api, cloudinary_api, config, critic, instagram, lint, pipeline
from src import telegram_api as tg
from src.util import ApiError

CHAT = "111"


def jpeg(color=(120, 160, 200), size=(1600, 1200)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def lib_item(n, name, rtype="image", created="2026-12-20T10:00:00Z"):
    return {"asset_id": f"a{n}", "public_id": f"libreria/{name}", "resource_type": rtype,
            "nome": name, "url": f"https://res.cloudinary.com/x/{rtype}/upload/v1/libreria/{name}.jpg",
            "larghezza": 1600, "altezza": 1200, "creato": created, "formato": "jpg"}


def good_draft(price=False):
    caption = ("Il tuo studio, pronto all'uso. Studio Emme è un coworking per professionisti della salute "
               "a Cavaria: stanze arredate e climatizzate, lettino professionale, sala d'attesa condivisa. "
               "Ognuno lavora in autonomia, con i propri pazienti. Puoi scegliere mezze giornate o giornate "
               "intere, con orari flessibili dal mattino presto alla sera tardi. La stazione è a 600 metri a "
               "piedi e il parcheggio in zona è comodo. Vuoi vedere lo studio? Scrivici in direct.\n\n"
               "Via Cardinal Ferrari 26, Cavaria (VA)\n\n"
               "#coworking #studioincondivisione #professionistisalute #osteopati #cavaria")
    return {
        "slides": [
            {"tipo": "copertina", "foto": "F001", "righe": ["IL TUO STUDIO,", "PRONTO ALL'USO"], "sottotitolo": "Studio Emme"},
            {"tipo": "foto", "foto": "F002", "etichetta": "STUDIO 3", "testo": "Lettino elettrico"},
            {"tipo": "foto", "foto": "F003", "etichetta": "STUDIO 1", "testo": "Raccolto e luminoso"},
            {"tipo": "testo", "titolo": "Cosa trovi in studio", "punti": ["Stanza arredata", "Sala d'attesa condivisa", "Orari flessibili"]},
            {"tipo": "testo", "titolo": "In breve", "punti": ["Mezze giornate", "Autonomia", "Stazione a 600 metri"]},
            {"tipo": "finale", "titolo": "Vieni a vedere lo studio", "righe": ["Scegli tu giorni e orari", "Tutto incluso e già pronto"], "prezzo": price},
        ],
        "didascalia": caption, "note_per_utente": "",
    }


class Env:
    def __init__(self, tmp_path, monkeypatch):
        self.sent = []          # messaggi Telegram
        self.published = []
        self.destroyed = []
        self.library = [lib_item(1, "tavolo"), lib_item(2, "lettino"), lib_item(3, "studio1")]
        self.updates = []
        self.draft = good_draft()
        self.now = datetime(2026, 12, 20, 10, 0, tzinfo=config.TZ)
        self.publish_fail = False
        mp = monkeypatch
        mp.setenv("TELEGRAM_CHAT_ID", CHAT)
        mp.setattr(pipeline, "STATE_PATH", tmp_path / "stato.json")
        mp.setattr(cat, "CATALOG_PATH", tmp_path / "catalogo.json")
        cal = tmp_path / "cal.json"
        cal.write_text(json.dumps([
            {"id": "2026-12-22", "data": "2026-12-22", "linea": "Gli spazi", "formato": "carosello",
             "tema": "Gli spazi", "materiale": [], "prezzo": False, "note": ""}]), encoding="utf-8")
        mp.setattr(pipeline, "CALENDAR_PATH", cal)
        mp.setattr(config, "now", lambda: self.now)
        mp.setattr(cloudinary_api, "search_library", lambda folder=None: list(self.library))
        mp.setattr(cloudinary_api, "upload_bytes",
                   lambda data, pid, rt="image": {"secure_url": f"https://cdn/{pid}.jpg", "public_id": pid})
        mp.setattr(cloudinary_api, "destroy", lambda pid, rt="image": self.destroyed.append(pid))
        mp.setattr(claude_api, "classify_image", lambda url: {
            "descrizione": "foto di prova", "soggetto": "studio3", "qualita": 4, "persone": False, "verticale": False})
        mp.setattr(claude_api, "write_draft", self._write)
        self.reviews = []   # giudizi del critico, uno per chiamata; vuoto = voto 9
        self.review_calls = 0
        mp.setattr(critic, "review", self._review)
        mp.setattr(pipeline, "http", lambda method, url, **kw: type("R", (), {"content": jpeg()})())
        mp.setattr(tg, "send_message", lambda text, buttons=None, chat=None: self._msg(text, buttons))
        mp.setattr(tg, "send_photos", lambda urls: self.sent.append(("photos", urls, None)))
        mp.setattr(tg, "send_video", lambda url, caption="": self.sent.append(("video", url, None)))
        mp.setattr(tg, "answer_callback", lambda *a, **k: None)
        mp.setattr(tg, "clear_buttons", lambda *a, **k: None)
        mp.setattr(tg, "get_updates", self._updates)
        mp.setattr(instagram, "publish_carousel", self._pub)
        mp.setattr(instagram, "publish_image", self._pub)
        mp.setattr(instagram, "publish_reel", self._pub)

    def _write(self, entry, brief, photos, videos, evidence, instruction="", previous=None, errors=None):
        self.last_instruction = instruction
        d = json.loads(json.dumps(self.draft))
        if instruction:
            d["note_per_utente"] = "modificato: " + instruction
        return d

    def _review(self, entry, draft, image_urls, brief):
        self.review_calls += 1
        if self.reviews:
            return self.reviews.pop(0)
        return {"punteggio": 9, "giudizio": "Ottima.", "problemi": [], "istruzioni": ""}

    def _msg(self, text, buttons):
        self.sent.append(("msg", text, buttons))
        return {"message_id": len(self.sent)}

    def _updates(self, offset=0):
        out = [u for u in self.updates if u["update_id"] >= offset]
        return out

    def _pub(self, urls, caption=None):
        if self.publish_fail:
            raise ApiError("Instagram: token scaduto")
        self.published.append((urls, caption))
        return {"id": "99", "link": "https://instagram.com/p/xyz"}

    def callback(self, uid, data, chat=CHAT):
        self.updates.append({"update_id": uid, "callback_query": {"id": "c", "data": data,
                             "message": {"message_id": 5, "chat": {"id": int(chat)}}}})

    def message(self, uid, text, chat=CHAT):
        self.updates.append({"update_id": uid, "message": {"text": text, "chat": {"id": int(chat)}}})

    def texts(self):
        return [s[1] for s in self.sent if s[0] == "msg"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


def test_prepara_bozza_e_invia_anteprima(env):
    pipeline.tick()
    state = pipeline.load_state()
    assert state["posts"]["2026-12-22"]["stato"] == "bozza_inviata"
    kinds = [s[0] for s in env.sent]
    assert "photos" in kinds
    last = env.sent[-1]
    assert last[2][0][0]["callback_data"] == "ok:2026-12-22"
    assert len(env.sent[0][1]) == 6  # sei slide


def test_approva_e_pubblica_all_ora(env):
    pipeline.tick()
    env.callback(1, "ok:2026-12-22")
    pipeline.tick()
    assert pipeline.load_state()["posts"]["2026-12-22"]["stato"] == "approvato"
    assert env.published == []  # non e' ancora l'ora
    env.now = datetime(2026, 12, 22, 18, 40, tzinfo=config.TZ)
    pipeline.tick()
    st = pipeline.load_state()["posts"]["2026-12-22"]
    assert st["stato"] == "pubblicato" and st["link"].startswith("https://instagram.com")
    assert len(env.published) == 1 and len(env.published[0][0]) == 6
    assert len(env.destroyed) == 6  # anteprime ripulite


def test_senza_approvazione_non_pubblica(env):
    pipeline.tick()
    env.now = datetime(2026, 12, 22, 19, 0, tzinfo=config.TZ)
    pipeline.tick()
    assert env.published == []


def test_chi_non_sei_tu_viene_ignorato(env):
    pipeline.tick()
    env.callback(1, "ok:2026-12-22", chat="999")
    pipeline.tick()
    assert pipeline.load_state()["posts"]["2026-12-22"]["stato"] == "bozza_inviata"


def test_modifica_con_testo_libero(env):
    pipeline.tick()
    env.callback(1, "mod:2026-12-22")
    pipeline.tick()
    assert pipeline.load_state()["in_attesa_modifica"] == "2026-12-22"
    env.message(2, "Metti più luce nel testo")
    pipeline.tick()
    st = pipeline.load_state()
    assert st["in_attesa_modifica"] is None
    assert st["posts"]["2026-12-22"]["revisioni"] == 1
    assert "Metti più luce" in env.last_instruction
    assert any("modificato" in t for t in env.texts())


def test_manca_materiale_avvisa_e_poi_prepara(env, tmp_path):
    cal = json.loads(pipeline.CALENDAR_PATH.read_text())
    cal[0]["materiale"] = ["M6"]
    pipeline.CALENDAR_PATH.write_text(json.dumps(cal))
    pipeline.tick()
    assert pipeline.load_state()["posts"]["2026-12-22"]["stato"] == "manca_materiale"
    assert any("M6" in t for t in env.texts())
    n = len(env.sent)
    pipeline.tick()
    assert len(env.sent) == n  # non ripete l'avviso subito
    env.library.append(lib_item(4, "M6 studio1 mattina"))
    pipeline.tick()
    assert pipeline.load_state()["posts"]["2026-12-22"]["stato"] == "bozza_inviata"


def test_errore_di_pubblicazione_avvisa_con_didascalia(env):
    pipeline.tick()
    env.callback(1, "ok:2026-12-22")
    pipeline.tick()
    env.publish_fail = True
    env.now = datetime(2026, 12, 22, 19, 0, tzinfo=config.TZ)
    pipeline.tick()
    assert pipeline.load_state()["posts"]["2026-12-22"]["stato"] == "errore_pubblicazione"
    assert any("token scaduto" in t and "Didascalia" in t for t in env.texts())
    env.publish_fail = False
    env.callback(2, "retry:2026-12-22")
    pipeline.tick()
    assert pipeline.load_state()["posts"]["2026-12-22"]["stato"] == "pubblicato"


def test_post_scaduto_non_viene_pubblicato(env):
    pipeline.tick()
    env.callback(1, "ok:2026-12-22")
    pipeline.tick()
    env.now = datetime(2026, 12, 24, 12, 0, tzinfo=config.TZ)
    pipeline.tick()
    assert env.published == []
    assert pipeline.load_state()["posts"]["2026-12-22"]["stato"] == "scaduto"


def test_bozza_con_prezzo_vietato_viene_scartata_e_corretta(env, monkeypatch):
    bad = good_draft()
    bad["didascalia"] += " Costa 180 € al mese."
    drafts = [bad, bad, good_draft()]
    monkeypatch.setattr(claude_api, "write_draft", lambda *a, **k: drafts.pop(0))
    pipeline.tick()
    assert pipeline.load_state()["posts"]["2026-12-22"]["stato"] == "bozza_inviata"
    assert drafts == []


def test_tre_bozze_sbagliate_avvisano_senza_pubblicare(env, monkeypatch):
    bad = good_draft()
    bad["didascalia"] = bad["didascalia"].replace("coworking", "studio medico")
    monkeypatch.setattr(claude_api, "write_draft", lambda *a, **k: bad)
    pipeline.tick()
    assert pipeline.load_state()["posts"]["2026-12-22"]["stato"] == "errore_bozza"
    assert env.published == []


def test_lint_regole_del_prezzo():
    catalog = {"assets": {f"a{i}": {"sid": f"F00{i}", "tipo": "foto", "qualita": 4, "persone": False}
                          for i in (1, 2, 3)}}
    entry = {"formato": "carosello", "prezzo": True}
    d = good_draft(price=True)
    d["didascalia"] += " Da 180 € al mese."
    errs = lint.check(d, entry, catalog)
    assert any("a partire da" in e for e in errs)
    d["didascalia"] = d["didascalia"].replace("Da 180 € al mese.", "A partire da 180 € al mese.")
    assert lint.check(d, entry, catalog) == []
    d["slides"][0]["sottotitolo"] = "Da 180 € al mese"
    assert any("prezzo" in e.lower() for e in lint.check(d, entry, catalog))


def test_lint_pulizia_trattini():
    d = lint.clean({"didascalia": "Uno — due – tre"})
    assert "—" not in d["didascalia"] and "–" not in d["didascalia"]


def test_primo_avvio_senza_chat_id_risponde_solo_chi_scrive(env, monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_ID")
    state = pipeline.load_state()
    sent = []
    monkeypatch.setattr(tg, "send_message", lambda text, buttons=None, chat=None: sent.append((text, chat)))
    pipeline.handle_message(state, cat.load(), {"text": "/start", "chat": {"id": 555}})
    assert sent and "555" in sent[0][0] and sent[0][1] == "555"


def test_lint_nutrizionisti_ok_ma_visita_guidata_no():
    catalog = {"assets": {f"a{i}": {"sid": f"F00{i}", "tipo": "foto", "qualita": 4, "persone": False}
                          for i in (1, 2, 3)}}
    entry = {"formato": "carosello", "prezzo": False}
    d = good_draft()
    d["didascalia"] += " Nello studio lavorano due nutrizionisti, che non si fanno concorrenza."
    assert lint.check(d, entry, catalog) == []
    d["didascalia"] += " Prenota una visita guidata."
    assert any("visita guidata" in e for e in lint.check(d, entry, catalog))


def judge(score, instr=""):
    return {"punteggio": score, "giudizio": f"voto {score}", "problemi": ["x"] if instr else [], "istruzioni": instr}


def test_critico_voto_alto_mostra_giudizio_senza_correggere(env):
    pipeline.tick()
    assert env.review_calls == 1
    assert any("Giudizio del critico: 9/10. Ottima." in t for t in env.texts())
    assert pipeline.load_state()["posts"]["2026-12-22"]["critico"]["giri"] == 0


def test_critico_voto_basso_fa_correggere_e_mostra_la_migliore(env):
    env.reviews = [judge(4, "Accorcia il titolo"), judge(8)]
    pipeline.tick()
    assert env.review_calls == 2
    assert "Accorcia il titolo" in env.last_instruction
    assert any("8/10 (corretta 1 volta)" in t for t in env.texts())
    # le grafiche del primo tentativo scartato vengono cancellate
    assert any("_v1_" in pid for pid in env.destroyed)


def test_critico_si_ferma_dopo_due_correzioni_e_tiene_la_migliore(env):
    env.reviews = [judge(5, "a"), judge(3, "b"), judge(4, "c")]
    pipeline.tick()
    assert env.review_calls == 3
    assert any("5/10." in t for t in env.texts())
    assert pipeline.load_state()["posts"]["2026-12-22"]["stato"] == "bozza_inviata"


def test_critico_che_non_risponde_non_blocca_il_post(env):
    env.reviews = [None]
    pipeline.tick()
    assert pipeline.load_state()["posts"]["2026-12-22"]["stato"] == "bozza_inviata"
    assert not any("Giudizio del critico" in t for t in env.texts())


def test_critico_review_vera_gestisce_errori_e_risposte(monkeypatch):
    entry = {"data": "2026-12-22", "linea": "x", "formato": "carosello", "tema": "t", "prezzo": False, "note": ""}
    d = good_draft()
    def boom(*a, **k): raise ApiError("giu")
    monkeypatch.setattr(claude_api, "ask", boom)
    assert critic.review(entry, d, ["https://x/1.jpg"], "brief") is None
    monkeypatch.setattr(claude_api, "ask", lambda *a, **k: '{"punteggio": 6, "giudizio": "ok", "problemi": ["a"], "istruzioni": "fai"}')
    r = critic.review(entry, d, [], "brief")
    assert r["punteggio"] == 6 and r["istruzioni"] == "fai"
    monkeypatch.setattr(claude_api, "ask", lambda *a, **k: '{"punteggio": 42}')
    assert critic.review(entry, d, [], "brief") is None


def test_storie_piano_valido_e_render():
    from src import stories
    S = stories.load_stories()
    ids = [s["id"] for s in S]
    assert len(ids) == len(set(ids))
    for s in S:
        for f in s["frames"]:
            assert f["layout"] in stories.LAYOUTS
            if s["consegna"] == "auto":
                assert not f.get("sticker")
            elif f.get("sticker"):
                assert stories.sticker_help(f)
    im = stories.render_frame({"layout": "domanda", "titolo": "Lettino o scrivania?"})
    assert im.size == (1080, 1920)


def test_calendario_senza_troppi_inviti_ripetuti():
    cal = json.loads((config.ROOT / "piano" / "calendario.json").read_text(encoding="utf-8"))
    rec = [e for e in cal if e["obiettivo"] == "reclutamento"]
    assert len(rec) / len(cal) <= 0.4
    for a, b in zip(cal, cal[1:]):
        assert not (a["obiettivo"] == b["obiettivo"] == "reclutamento")


def test_critico_review_images_storie_e_byte(monkeypatch):
    seen = {}
    def fake(system, content, max_tokens=900):
        seen["system"], seen["content"] = system, content
        return '{"punteggio": 8, "giudizio": "ok", "problemi": [], "istruzioni": ""}'
    monkeypatch.setattr(claude_api, "ask", fake)
    png = b"\x89PNG" + b"0" * 10
    r = critic.review_images("storia", "Natale", [png, "https://x/2.jpg"], "brief")
    assert r["punteggio"] == 8
    assert "STORIA Instagram" in seen["system"] and "numerazione" in seen["system"]
    assert seen["content"][1]["source"]["type"] == "base64" and seen["content"][2]["source"]["type"] == "url"
    r = critic.review_images("grafica", "Carosello", [png], "brief", "didascalia")
    assert "grafica gia' finita" in seen["system"]
    def boom(*a, **k): raise ApiError("giu")
    monkeypatch.setattr(claude_api, "ask", boom)
    assert critic.review_images("storia", "x", [png], "b") is None


def test_render_senza_numeri_ne_handle():
    from src import render
    assert not hasattr(render, "stamp") and not hasattr(render, "HANDLE")
