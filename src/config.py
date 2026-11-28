"""Impostazioni fisse del progetto.

Le chiavi NON stanno qui: arrivano solo dalle variabili d'ambiente
(segreti di GitHub). Questo file e' pubblico.
"""
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("Europe/Rome")

IG_USER_ID = "17841448284555941"
GRAPH = "https://graph.facebook.com/v26.0"

MODEL = "claude-sonnet-5-5"
ANTHROPIC_VERSION = "2023-06-01"

LIBRARY_FOLDER = "libreria"      # cartella di Cloudinary dove carichi foto e video
PREVIEW_PREFIX = "anteprime"     # dove il programma mette le grafiche pronte

PUBLISH_TIME = (18, 30)          # ora di uscita dei post (ora italiana)
PREPARE_DAYS_AHEAD = 5           # quanti giorni prima prepara la bozza
MAX_LATE_HOURS = 24              # oltre questo ritardo un post approvato non esce piu'
CRITIC_MIN_SCORE = 7             # sotto questo voto il critico rimanda la bozza al redattore
CRITIC_MAX_LOOPS = 2             # quante volte al massimo si corregge prima di mostrartela
MAX_REVISIONS = 5                # modifiche richieste per ogni post
MAX_PREPARE_ERRORS = 3           # dopo tanti errori di preparazione si ferma e aspetta /riprova
M13_MAX_AGE_DAYS = 20            # la tabella disponibilita' non deve essere piu' vecchia

ADDRESS = "Via Cardinal Ferrari 168 · Cavaria (VA)"
PRICE_LINE = "A partire da 180 € al mese · contratti semestrali"
HASHTAGS_BASE = [
    "#coworking", "#studioincondivisione", "#professionistisalute",
    "#fisioterapisti", "#osteopati", "#psicologi", "#cavaria", "#varese",
]

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def now() -> datetime:
    return datetime.now(TZ)


def env(name: str, required: bool = True):
    value = os.environ.get(name, "").strip()
    if required and not value:
        raise RuntimeError(f"Manca il segreto {name} (variabile d'ambiente).")
    return value


def data_it(d) -> str:
    """Es. 'martedì 22 dicembre'."""
    return f"{GIORNI[d.weekday()]} {d.day} {MESI[d.month]}"
