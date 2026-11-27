"""Catalogo del materiale: elenco di foto e video della libreria Cloudinary, con descrizioni."""
import re
from datetime import datetime, timezone

from . import claude_api, cloudinary_api, config
from .util import ApiError, load_json, save_json

CATALOG_PATH = config.ROOT / "stato" / "catalogo.json"
CODE_RE = re.compile(r"^\s*(M\d{1,2})\b", re.I)
AUDIO_FORMATS = ("mp3", "wav", "m4a", "aac", "ogg", "flac")


def load() -> dict:
    return load_json(CATALOG_PATH, {"assets": {}, "prossimo_id": 1})


def save(catalog: dict) -> None:
    save_json(CATALOG_PATH, catalog)


def code_of(name: str):
    m = CODE_RE.match(name or "")
    return m.group(1).upper() if m else None


def sync(catalog: dict, classify=True) -> int:
    """Allinea il catalogo con Cloudinary. Restituisce quanti elementi nuovi ha aggiunto."""
    items = cloudinary_api.search_library()
    seen = set()
    new = 0
    retry_budget = 10
    for it in items:
        aid = it["asset_id"]
        seen.add(aid)
        if aid in catalog["assets"]:
            old = catalog["assets"][aid]
            if it.get("durata") and not old.get("durata"):
                old["durata"] = it["durata"]
            if old["tipo"] == "foto" and not old.get("classificato") and classify and retry_budget > 0:
                retry_budget -= 1
                try:
                    small = cloudinary_api.transform_url(it["url"], "c_limit,w_1100,q_auto:good")
                    old.update(claude_api.classify_image(small))
                    old["classificato"] = True
                except ApiError:
                    pass
            continue
        sid = f"F{catalog['prossimo_id']:03d}"
        catalog["prossimo_id"] += 1
        tipo = "video" if it["resource_type"] == "video" else "foto"
        if (it.get("formato") or "").lower() in AUDIO_FORMATS or it.get("resource_type") == "raw":
            tipo = "audio"
        entry = {
            "sid": sid, "asset_id": aid, "public_id": it["public_id"], "tipo": tipo,
            "nome": it["nome"], "codice": code_of(it["nome"]), "url": it["url"],
            "larghezza": it["larghezza"], "altezza": it["altezza"], "creato": it["creato"],
            "descrizione": it["nome"], "soggetto": "altro", "qualita": 3,
            "persone": False, "durata": it.get("durata"), "verticale": bool(it["altezza"] and it["larghezza"]
                                                 and it["altezza"] > it["larghezza"]),
        }
        if tipo == "foto" and classify:
            try:
                small = cloudinary_api.transform_url(it["url"], "c_limit,w_1100,q_auto:good")
                entry.update(claude_api.classify_image(small))
                entry["classificato"] = True
            except ApiError:
                pass  # restano i valori di base: ci riprova ai giri successivi
        catalog["assets"][aid] = entry
        new += 1
    for aid in [a for a in catalog["assets"] if a not in seen]:
        del catalog["assets"][aid]
    return new


def photos(catalog: dict, min_quality: int = 3) -> list:
    out = [a for a in catalog["assets"].values()
           if a["tipo"] == "foto" and a["qualita"] >= min_quality
           and a["soggetto"] not in ("disponibilita", "recensioni")]
    return sorted(out, key=lambda a: a["sid"])


def videos(catalog: dict) -> list:
    return sorted((a for a in catalog["assets"].values() if a["tipo"] == "video"),
                  key=lambda a: a["sid"])


def music(catalog: dict) -> list:
    """Brani per i reel: file audio della libreria il cui nome inizia con MUSICA."""
    return sorted((a for a in catalog["assets"].values()
                   if a["tipo"] == "audio" and (a["nome"] or "").strip().upper().startswith("MUSICA")),
                  key=lambda a: a["sid"])


def by_sid(catalog: dict, sid: str):
    for a in catalog["assets"].values():
        if a["sid"] == sid:
            return a
    return None


def with_code(catalog: dict, code: str, tipo: str = None) -> list:
    return [a for a in catalog["assets"].values()
            if a["codice"] == code and (tipo is None or a["tipo"] == tipo)]


def age_days(asset: dict, today=None) -> float:
    try:
        created = datetime.fromisoformat(asset["creato"].replace("Z", "+00:00"))
    except Exception:
        return 0.0
    today = today or datetime.now(timezone.utc)
    return (today - created).total_seconds() / 86400
