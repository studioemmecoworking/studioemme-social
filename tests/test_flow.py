"""Prova completa del ciclo con servizi simulati (nessuna rete, nessuna chiave)."""
import io
import json
from datetime import datetime

import pytest
from PIL import Image

from src import catalog as cat
from src import claude_api, cloudinary_api, config, instagram, lint, pipeline
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
               "#coworking #studioincondivisione #professionistisalute #fisioterapisti #osteopati #cavaria")
    return {
        "slides": [
            {"tipo": "copertina", "foto": "F001", "righe": ["IL TUO STUDIO,", "PRONTO ALL'USO"], "sottotitolo": "Studio Emme"},
            {"tipo": "foto", "foto": "F002", "etichetta": "STUDIO 3", "testo": "Lettino elettrico"},
            {"tipo": "foto", "foto": "F003", "etichetta": "STUDIO 1", "testo": "Raccolto e luminoso"},
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
    assert len(env.sent[0][1]) == 4  # quattro slide


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
    assert len(env.published) == 1 and len(env.published[0][0]) == 4
    assert len(env.destroyed) == 4  # anteprime ripulite


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
