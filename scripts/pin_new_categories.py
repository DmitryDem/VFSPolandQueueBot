"""Публикует и закрепляет кнопки анкеты в новых темах (D Карта поляка, D Учёба)."""
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"
TOPICS = json.loads((ROOT / "config" / "topics.json").read_text("utf-8"))
CHAT_ID = TOPICS["chat_id"]
CITIES = list(TOPICS["cities"].keys())
BOT = requests.get(f"{API}/getMe", timeout=30).json()["result"]["username"]

LABELS = {"D_KARTA": "Национальная D (Карта поляка)", "D_STUDY": "Национальная D (Учёба)"}
NEW_KEYS = list(LABELS.keys())


def call(method, **params):
    while True:
        r = requests.post(f"{API}/{method}", json=params, timeout=30).json()
        if r.get("ok"):
            return r["result"]
        if r.get("error_code") == 429:
            wait = r["parameters"]["retry_after"] + 1
            print(f"429, ждём {wait} c...")
            time.sleep(wait)
            continue
        return {"__error__": r.get("description")}


for city in CITIES:
    idx = CITIES.index(city)
    for visa in NEW_KEYS:
        tid = TOPICS["cities"][city][visa]
        base = f"https://t.me/{BOT}?start="
        text = (
            f"Встали в очередь VFS — <b>{city}, {LABELS[visa]}</b>?\n"
            "Поделитесь своими датами: это поможет всем оценить скорость очереди.\n\n"
            "📝 <b>Анкета</b> — заполните один раз, дальше дополняйте по мере продвижения "
            "(письмо → запись → подача → паспорт). Город и тип визы подставятся автоматически.\n"
            "📊 <b>Статистика</b> — сводка, графики и прогноз по этой теме.\n"
            "🔮 <b>Мой прогноз</b> — когда ждать письмо именно вам."
        )
        kb = {"inline_keyboard": [
            [{"text": "📝 Заполнить / обновить анкету", "url": f"{base}r_{idx}_{visa}"}],
            [{"text": "📊 Статистика очереди", "url": f"{base}s_{idx}_{visa}"}],
            [{"text": "🔮 Мой прогноз", "url": f"{base}m_{idx}_{visa}"}],
        ]}
        msg = call("sendMessage", chat_id=CHAT_ID, message_thread_id=tid,
                   text=text, parse_mode="HTML", reply_markup=kb)
        if isinstance(msg, dict) and "__error__" in msg:
            print(f"FAIL {city} {visa}: {msg['__error__']}")
            continue
        time.sleep(1.5)
        call("pinChatMessage", chat_id=CHAT_ID, message_id=msg["message_id"], disable_notification=True)
        print(f"pinned: {city} {visa} (msg {msg['message_id']})")
        time.sleep(1.5)
