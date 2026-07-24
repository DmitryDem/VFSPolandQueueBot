"""Отправка уведомлений в Telegram-группу/канал."""
import os

import requests

API_URL = "https://api.telegram.org/bot{token}/{method}"


def send_message(
    text: str,
    chat_id: str | None = None,
    topic_id: int | None = None,
    token: str | None = None,
) -> dict:
    token = token or os.environ["BOT_TOKEN"]
    chat_id = chat_id or os.environ["CHAT_ID"]
    if topic_id is None and os.environ.get("TOPIC_GENERAL"):
        topic_id = int(os.environ["TOPIC_GENERAL"])
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if topic_id is not None:
        payload["message_thread_id"] = topic_id
    resp = requests.post(
        API_URL.format(token=token, method="sendMessage"),
        json=payload,
        timeout=30,
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    return data["result"]
