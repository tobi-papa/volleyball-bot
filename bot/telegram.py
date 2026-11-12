"""Send a message through the Telegram Bot API."""
from __future__ import annotations

import requests

from bot.messages import split_message

API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramError(Exception):
    """Sending failed. The message never contains the bot token."""


def send(text: str, token: str, chat_id: str, *, session=None) -> None:
    session = session or requests.Session()
    url = API.format(token=token)
    for chunk in split_message(text):
        payload = {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}
        try:
            r = session.post(url, json=payload, timeout=30)
        except Exception as e:  # network errors may echo the URL, which holds the token
            raise TelegramError(f"network error: {type(e).__name__}".replace(token, "<token>")) from None
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code != 200 or not body.get("ok"):
            desc = str(body.get("description", "")).replace(token, "<token>")
            raise TelegramError(f"Telegram API {r.status_code}: {desc}")
