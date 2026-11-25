"""Telegram: anteprime, pulsanti di approvazione e risposte."""
import os

from . import config
from .util import ApiError, as_json, http


def _call(method: str, **params):
    token = config.env("TELEGRAM_BOT_TOKEN")
    r = http("POST", f"https://api.telegram.org/bot{token}/{method}", json=params, timeout=40)
    j = as_json(r, "Telegram")
    if not j.get("ok"):
        raise ApiError(f"Telegram {method}: {j.get('description')}")
    return j["result"]


def chat_id() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def send_message(text: str, buttons=None, chat=None):
    params = {"chat_id": chat or config.env("TELEGRAM_CHAT_ID"), "text": text[:4000],
              "disable_web_page_preview": True}
    if buttons:
        params["reply_markup"] = {"inline_keyboard": buttons}
    return _call("sendMessage", **params)


def send_photos(urls: list):
    cid = config.env("TELEGRAM_CHAT_ID")
    if len(urls) == 1:
        return _call("sendPhoto", chat_id=cid, photo=urls[0])
    return _call("sendMediaGroup", chat_id=cid,
                 media=[{"type": "photo", "media": u} for u in urls[:10]])


def send_video(url: str, caption: str = ""):
    return _call("sendVideo", chat_id=config.env("TELEGRAM_CHAT_ID"), video=url,
                 caption=caption[:900])


def answer_callback(callback_id: str, text: str = ""):
    try:
        _call("answerCallbackQuery", callback_query_id=callback_id, text=text[:150])
    except ApiError:
        pass


def clear_buttons(message_id: int):
    try:
        _call("editMessageReplyMarkup", chat_id=config.env("TELEGRAM_CHAT_ID"),
              message_id=message_id, reply_markup={"inline_keyboard": []})
    except ApiError:
        pass


def get_updates(offset: int = 0) -> list:
    return _call("getUpdates", offset=offset, timeout=0,
                 allowed_updates=["message", "callback_query"])
