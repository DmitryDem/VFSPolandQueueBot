"""Публикует и закрепляет в каждой городской теме сообщение с кнопкой «Заполнить анкету»
(deep-link на личку с ботом с предвыбранными городом и типом визы)."""
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

TOPICS = json.loads((ROOT / "config" / "topics.json").read_text("utf-8"))
CHAT_ID = TOPICS["chat_id"]
CITIES = list(TOPICS["cities"].keys())
TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"

VISA_LABELS = {
    "D_OTHER": "Национальная D (Other)",
    "D_DRIVER": "Национальная D (Driver)",
    "D_WORK": "Национальная D (Work)",
    "C_OTHER": "Шенген C (Other)",
}

BOT_USERNAME = requests.get(f"{API}/getMe", timeout=30).json()["result"]["username"]


def call(method: str, **params):
    while True:
        resp = requests.post(f"{API}/{method}", json=params, timeout=30).json()
        if resp.get("ok"):
            return resp["result"]
        if resp.get("error_code") == 429:
            wait = resp["parameters"]["retry_after"] + 1
            print(f"429, ждём {wait} сек...")
            time.sleep(wait)
            continue
        raise RuntimeError(f"{method} failed: {resp}")


# уже опубликованные кнопки (при повторном запуске не дублировать)
DONE = {
    (city, visa)
    for city, types in TOPICS["cities"].items()
    for visa in types
} - {("Гомель", "D_WORK")}


def main() -> None:
    for city, types in TOPICS["cities"].items():
        for visa, tid in types.items():
            if (city, visa) in DONE:
                print(f"skip (уже сделано): {city} {visa}")
                continue
            if not tid:
                print(f"skip (нет ID темы): {city} {visa}")
                continue
            payload = f"r_{CITIES.index(city)}_{visa}"
            url = f"https://t.me/{BOT_USERNAME}?start={payload}"
            msg = call(
                "sendMessage",
                chat_id=CHAT_ID,
                message_thread_id=tid,
                text=(
                    f"Встали в очередь VFS — <b>{city}, {VISA_LABELS[visa]}</b>?\n"
                    "Поделитесь своими датами: это поможет всем оценить скорость очереди.\n\n"
                    "Нажмите кнопку — анкета откроется в личке с ботом, город и тип визы "
                    "уже будут выбраны."
                ),
                parse_mode="HTML",
                reply_markup={
                    "inline_keyboard": [[{"text": "📝 Заполнить анкету", "url": url}]]
                },
            )
            time.sleep(2)
            call(
                "pinChatMessage",
                chat_id=CHAT_ID,
                message_id=msg["message_id"],
                disable_notification=True,
            )
            print(f"pinned: {city} {visa} (message {msg['message_id']})")
            time.sleep(2)


if __name__ == "__main__":
    main()
