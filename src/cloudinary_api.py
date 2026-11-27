"""Cloudinary: libreria di foto e video, anteprime e file pubblici per Instagram."""
import hashlib
import time

from . import config
from .util import ApiError, as_json, http


def _cfg():
    return (config.env("CLOUDINARY_CLOUD_NAME"), config.env("CLOUDINARY_API_KEY"),
            config.env("CLOUDINARY_API_SECRET"))


def _sign(params: dict, secret: str) -> str:
    base = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v not in (None, ""))
    return hashlib.sha1((base + secret).encode("utf-8")).hexdigest()


def upload_bytes(data: bytes, public_id: str, resource_type: str = "image") -> dict:
    cloud, key, secret = _cfg()
    params = {"public_id": public_id, "timestamp": int(time.time()), "overwrite": "true"}
    sig = _sign(params, secret)
    r = http("POST", f"https://api.cloudinary.com/v1_1/{cloud}/{resource_type}/upload",
             data={**params, "api_key": key, "signature": sig}, files={"file": ("file", data)},
             timeout=600)
    j = as_json(r, "Cloudinary")
    if "secure_url" not in j:
        raise ApiError(f"Cloudinary: caricamento fallito ({j.get('error', {}).get('message')})")
    return j


def destroy(public_id: str, resource_type: str = "image") -> None:
    cloud, key, secret = _cfg()
    params = {"public_id": public_id, "timestamp": int(time.time()), "invalidate": "true"}
    sig = _sign(params, secret)
    http("POST", f"https://api.cloudinary.com/v1_1/{cloud}/{resource_type}/destroy",
         data={**params, "api_key": key, "signature": sig})


def search_library(folder: str = None) -> list:
    """Elenca foto e video della cartella libreria.

    Gli account nuovi usano le cartelle 'dinamiche' (campo asset_folder), quelli vecchi
    le cartelle 'fisse': provo le due ricerche, piu' una per etichetta (tag).
    """
    folder = folder or config.LIBRARY_FOLDER
    cloud, key, secret = _cfg()
    last_error = None
    any_ok = False
    for expr in (f'asset_folder="{folder}"', f'folder="{folder}"', f'tags="{folder}"'):
        items, cursor, failed = [], None, False
        while True:
            body = {"expression": expr, "max_results": 100}
            if cursor:
                body["next_cursor"] = cursor
            r = http("POST", f"https://api.cloudinary.com/v1_1/{cloud}/resources/search",
                     auth=(key, secret), json=body)
            j = as_json(r, "Cloudinary")
            if r.status_code != 200:
                last_error = j.get("error", {}).get("message", f"HTTP {r.status_code}")
                failed = True
                break
            items.extend(j.get("resources", []))
            cursor = j.get("next_cursor")
            if not cursor:
                break
        if not failed:
            any_ok = True
            if items:
                return [_normalize(x) for x in items
                        if x.get("resource_type") in ("image", "video")]
    if not any_ok:
        # Tutte le ricerche hanno dato errore: lo segnalo. Se erano solo vuote, la libreria e' vuota.
        raise ApiError(f"Cloudinary: ricerca nella libreria fallita ({last_error})")
    return []


def _normalize(x: dict) -> dict:
    name = x.get("display_name") or x.get("filename") or x.get("public_id", "").split("/")[-1]
    return {
        "asset_id": x.get("asset_id") or x.get("public_id"),
        "public_id": x["public_id"],
        "resource_type": x["resource_type"],
        "nome": name,
        "url": x["secure_url"],
        "larghezza": x.get("width"),
        "altezza": x.get("height"),
        "creato": x.get("created_at"),
        "formato": x.get("format"),
        "durata": x.get("duration"),
    }


def transform_url(url: str, transformation: str) -> str:
    """Inserisce una trasformazione nell'indirizzo, es. 'c_limit,w_1000'."""
    return url.replace("/upload/", f"/upload/{transformation}/", 1)
