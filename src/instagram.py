"""Instagram: pubblicazione di foto, caroselli e reel con l'API di Meta."""
import time

from . import config
from .util import ApiError, as_json, http


def _post(path: str, **fields) -> dict:
    token = config.env("IG_ACCESS_TOKEN")
    r = http("POST", f"{config.GRAPH}/{path}", data={**fields, "access_token": token})
    j = as_json(r, "Instagram")
    if "error" in j:
        raise ApiError(f"Instagram: {j['error'].get('message')}")
    return j


def _get(path: str, fields: str) -> dict:
    token = config.env("IG_ACCESS_TOKEN")
    r = http("GET", f"{config.GRAPH}/{path}", params={"fields": fields, "access_token": token})
    j = as_json(r, "Instagram")
    if "error" in j:
        raise ApiError(f"Instagram: {j['error'].get('message')}")
    return j


def _wait(container_id: str, timeout: int = 900, step: int = 5) -> None:
    waited = 0
    while waited <= timeout:
        status = _get(container_id, "status_code").get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise ApiError(f"Instagram ha rifiutato il contenuto (stato {status}).")
        time.sleep(step)
        waited += step
    raise ApiError("Tempo scaduto in attesa di Instagram.")


def _publish(container_id: str) -> dict:
    media_id = _post(f"{config.IG_USER_ID}/media_publish", creation_id=container_id)["id"]
    link = _get(media_id, "permalink").get("permalink", "")
    return {"id": media_id, "link": link}


def publish_image(image_url: str, caption: str) -> dict:
    c = _post(f"{config.IG_USER_ID}/media", image_url=image_url, caption=caption)["id"]
    _wait(c)
    return _publish(c)


def publish_carousel(image_urls: list, caption: str) -> dict:
    children = []
    for u in image_urls:
        children.append(_post(f"{config.IG_USER_ID}/media", image_url=u,
                              is_carousel_item="true")["id"])
    for c in children:
        _wait(c)
    carousel = _post(f"{config.IG_USER_ID}/media", media_type="CAROUSEL",
                     children=",".join(children), caption=caption)["id"]
    _wait(carousel)
    return _publish(carousel)


def publish_reel(video_url: str, caption: str) -> dict:
    c = _post(f"{config.IG_USER_ID}/media", media_type="REELS", video_url=video_url,
              caption=caption, share_to_feed="true")["id"]
    _wait(c, timeout=1200, step=10)
    return _publish(c)
