"""Utilita' comuni: richieste di rete con nuovi tentativi e protezione dei segreti nei messaggi."""
import json
import os
import time

import requests

SECRET_ENV = [
    "ANTHROPIC_API_KEY", "IG_ACCESS_TOKEN", "CLOUDINARY_API_KEY",
    "CLOUDINARY_API_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GEMINI_API_KEY",
]


class ApiError(Exception):
    pass


def redact(text) -> str:
    out = str(text)
    for name in SECRET_ENV:
        value = os.environ.get(name, "")
        if len(value) > 4:
            out = out.replace(value, "***")
    return out


def http(method: str, url: str, retries: int = 2, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", 60)
    last = None
    for i in range(retries + 1):
        try:
            r = requests.request(method, url, **kwargs)
        except requests.RequestException as e:
            # Non includo il testo dell'errore: puo' contenere l'indirizzo con il token.
            last = ApiError(f"Errore di rete ({type(e).__name__})")
            time.sleep(2 * (i + 1))
            continue
        if r.status_code >= 500 and i < retries:
            time.sleep(2 * (i + 1))
            continue
        return r
    raise last


def as_json(r: requests.Response, what: str) -> dict:
    try:
        return r.json()
    except ValueError:
        raise ApiError(f"{what}: risposta non valida (HTTP {r.status_code})")


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)
