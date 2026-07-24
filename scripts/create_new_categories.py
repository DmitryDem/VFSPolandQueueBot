"""Создаёт темы двух новых категорий — D (Карта поляка) и D (Учёба) — для всех городов.
Создать -> закрыть -> иконка 📆. Обработка 429. Печатает JSON-карту {город: {ключ: id}}."""
import json
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
import os

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
API = f"https://api.telegram.org/bot{TOKEN}"
CAL_ICON = "5433614043006903194"  # 📆
YELLOW = 16766590

TOPICS = json.loads((ROOT / "config" / "topics.json").read_text("utf-8"))
CITIES = list(TOPICS["cities"].keys())

NEW = [("D_KARTA", "Карта поляка"), ("D_STUDY", "Учёба")]


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
        raise RuntimeError(f"{method}: {r.get('description')}")


result = {}
for city in CITIES:
    result[city] = {}
    for key, label in NEW:
        name = f"{city} (D {label})"
        t = call("createForumTopic", chat_id=CHAT_ID, name=name, icon_color=YELLOW)
        tid = t["message_thread_id"]
        result[city][key] = tid
        print(f"created: {name} -> {tid}")
        time.sleep(3)
        call("closeForumTopic", chat_id=CHAT_ID, message_thread_id=tid)
        time.sleep(2)
        call("editForumTopic", chat_id=CHAT_ID, message_thread_id=tid, icon_custom_emoji_id=CAL_ICON)
        time.sleep(2)

print(json.dumps(result, ensure_ascii=False))
