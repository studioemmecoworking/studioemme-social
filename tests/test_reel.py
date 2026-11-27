"""Controlli sul montaggio automatico dei reel (senza rete e senza video)."""
from src import catalog as cat, lint, reel


def catalog():
    assets = {}
    for i in range(1, 9):
        assets[f"a{i}"] = {"sid": f"F{i:03d}", "tipo": "foto", "nome": f"foto{i}", "codice": None,
                           "persone": i == 8, "qualita": 5, "soggetto": "studio1", "verticale": True,
                           "url": "u", "descrizione": "d"}
    assets["v"] = {"sid": "F020", "tipo": "video", "nome": "M3 tour", "codice": "M3", "persone": False,
                   "qualita": 3, "soggetto": "altro", "url": "u", "durata": 40}
    assets["m"] = {"sid": "F030", "tipo": "audio", "nome": "MUSICA ambient", "codice": None,
                   "persone": False, "qualita": 3, "soggetto": "altro", "url": "u"}
    return {"assets": assets, "prossimo_id": 31}


def scaletta():
    return {"tipo": "montaggio", "scene": [
        {"etichetta": "PER PROFESSIONISTI DELLA SALUTE", "righe": ["3 motivi per", "scegliere", "Studio Emme"],
         "accento": "3 motivi", "inquadrature": [{"foto": "F001"}, {"foto": "F002"}]},
        {"righe": ["Stanze pronte", "all'uso"], "accento": "pronte",
         "inquadrature": [{"foto": "F003"}, {"ai": "an open paper agenda on a white desk with a plant"}]},
        {"righe": ["Massima flessibilità", "negli orari"], "accento": "flessibilità",
         "inquadrature": [{"video": "F020", "da": 3}]},
        {"righe": ["Tutto incluso:", "entri e lavori"], "accento": "Tutto incluso",
         "inquadrature": [{"ai": "a small italian railway station at golden hour"}, {"foto": "F004"}]},
    ]}


ENTRY = {"id": "2027-02-12", "formato": "reel", "prezzo": False}


def test_scaletta_valida():
    assert lint.check_reel(scaletta(), ENTRY, catalog()) == []


def test_scaletta_errori():
    r = scaletta()
    r["scene"][0]["righe"] = ["Uno studio da 180 € al mese"]
    r["scene"][1]["inquadrature"] = [{"foto": "F008"}]           # persone senza consenso
    r["scene"][2]["inquadrature"] = [{"foto": "F001"}]           # foto ripetuta
    r["scene"][3]["inquadrature"] = [{"ai": "station"}, {"ai": "a white door closing in a corridor"}]
    errs = " ".join(lint.check_reel(r, ENTRY, catalog()))
    for frag in ("prezzo", "persone", "stessa foto", "due immagini AI", "descrivi meglio", "20 caratteri"):
        assert frag in errs, frag
    assert lint.check_reel(None, ENTRY, catalog())


def test_tempi_e_transizioni():
    t = reel.plan(scaletta())
    assert t["tipo"] == "montaggio"
    assert abs(t["totale"] - (3.15 + 3.5 + 3.5 + 4.6)) < 0.01
    starts = [s["start"] for s in t["inquadrature"]]
    assert starts == sorted(starts) and starts[0] == 0
    # ogni inquadratura copre fino all'inizio della successiva piu' la transizione
    for a, b in zip(t["inquadrature"], t["inquadrature"][1:]):
        assert abs(a["start"] + a["dur"] - reel.XFADE - b["start"]) < 0.01
        assert a["dur"] >= reel.MIN_SHOT
    last = t["inquadrature"][-1]
    assert abs(last["start"] + last["dur"] - t["totale"]) < 0.01
    p = reel.props(t)
    assert p["scenes"][0]["box"] == reel.BOX_TOP and p["scenes"][1]["box"] == reel.BOX_LOW
    assert p["endCard"]["line1"] == "Vieni a vedere lo studio"
    assert "dissolve" not in reel.TRANSITIONS


def test_parlato():
    r = {"tipo": "parlato", "video": "F020", "da": 2, "a": 47,
         "scene": [{"righe": ["Perché ho creato", "Studio Emme"], "accento": "Studio Emme"}]}
    assert lint.check_reel(r, ENTRY, catalog()) == []
    t = reel.plan(r)
    assert t["totale"] == 45 and len(t["scene"]) == 1 and t["scene"][0]["dur"] == 3.0
    assert reel.props(t)["scenes"][0]["box"] == reel.BOX_LOW


def test_musica_dalla_libreria():
    c = catalog()
    assert [a["sid"] for a in cat.music(c)] == ["F030"]
    assert reel.pick_music(c, ENTRY)["sid"] == "F030"
    assert all(a["tipo"] != "audio" for a in cat.videos(c))
