"""Immagini AI di contesto per i reel (Google Gemini, modelli "Nano Banana").

La chiave arriva dal segreto GEMINI_API_KEY. Ogni immagine costa pochi centesimi.
Il modello si puo' cambiare con la variabile GEMINI_IMAGE_MODEL senza toccare il codice.
"""
import base64
import os

from . import config
from .util import ApiError, as_json, http

BASE = "https://generativelanguage.googleapis.com"
DEFAULT_MODELS = ["gemini-nano-banana-2.1", "gemini-3.1-flash-image"]

STYLE = (
    "Vertical 9:16 photograph for an Instagram reel of a small, bright coworking for health "
    "professionals in northern Italy. Photorealistic, like a beautiful magazine photo: soft natural "
    "warm daylight, calm and tidy, gentle colours with soft sage green and white tones, shallow depth "
    "of field. No people, no faces, no hands, no text, no letters, no numbers, no logos, no brands, "
    "no watermarks. Subject: "
)


def models() -> list:
    custom = os.environ.get("GEMINI_IMAGE_MODEL", "").strip()
    return [custom] if custom else DEFAULT_MODELS


def _bodies(prompt: str):
    """La forma della richiesta e' cambiata nel tempo: provo prima quella attuale, poi le precedenti."""
    parts = [{"parts": [{"text": prompt}]}]
    yield "v1", {"contents": parts, "generationConfig": {
        "responseModalities": ["IMAGE"],
        "responseFormat": {"image": {"aspectRatio": "9:16", "imageSize": "2K"}}}}
    yield "v1beta", {"contents": parts, "generationConfig": {
        "responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16", "imageSize": "2K"}}}
    yield "v1beta", {"contents": parts, "generationConfig": {
        "responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16"}}}


def _image_from(j: dict):
    for cand in j.get("candidates", []) or []:
        for part in ((cand.get("content") or {}).get("parts") or []):
            data = part.get("inlineData") or part.get("inline_data")
            if data and data.get("data"):
                return base64.b64decode(data["data"])
    return None


def generate(subject: str) -> bytes:
    """Restituisce i byte di un'immagine verticale per il soggetto (descritto in inglese)."""
    key = config.env("GEMINI_API_KEY")
    prompt = STYLE + subject.strip()
    last = "nessuna risposta"
    for model in models():
        for version, body in _bodies(prompt):
            r = http("POST", f"{BASE}/{version}/models/{model}:generateContent",
                     headers={"x-goog-api-key": key, "content-type": "application/json"},
                     json=body, timeout=180)
            try:
                j = as_json(r, "Gemini")
            except ApiError as e:
                last = str(e)
                continue
            if r.status_code == 200:
                img = _image_from(j)
                if img:
                    return img
                last = "risposta senza immagine (forse bloccata dai filtri)"
                continue
            last = (j.get("error") or {}).get("message", f"HTTP {r.status_code}")
            if r.status_code in (401, 403):
                raise ApiError(f"Gemini: chiave non valida o fatturazione non attiva ({last})")
            if r.status_code == 429:
                raise ApiError(f"Gemini: limite raggiunto ({last})")
    raise ApiError(f"Gemini: immagine non generata ({last[:200]})")
