"""Проверяет, существуют ли темы (по попытке editForumTopic — не меняя данных)."""
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
API = f"https://api.telegram.org/bot{TOKEN}"

CHECK = {
    "Гомель KARTA": 1320, "Минск KARTA": 1326, "Могилев KARTA": 1332,
    "Барановичи KARTA": 1338, "Пинск KARTA": 1344, "Брест KARTA": 1350,
    "Витебск KARTA": 1368, "Гродно KARTA (оставить)": 1356, "Лида KARTA (оставить)": 1362,
}

for name, tid in CHECK.items():
    # closeForumTopic — безвредно (тема и так закрыта); ответ покажет, существует ли тема
    r = requests.post(f"{API}/closeForumTopic",
                      json={"chat_id": CHAT_ID, "message_thread_id": tid}, timeout=30).json()
    if r.get("ok"):
        status = "СУЩЕСТВУЕТ"
    else:
        status = f"нет ({r.get('description')})"
    print(f"{tid} {name}: {status}")
    time.sleep(1)
