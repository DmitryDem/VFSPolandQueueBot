"""Устанавливает аватарку и описание группы."""
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
API = f"https://api.telegram.org/bot{TOKEN}"

DESCRIPTION = (
    "Очередь на польскую визу в Беларуси (VFS Global): статистика от участников "
    "и прогнозы — скорость очереди, даты приглашений, ожидание по городам. "
    "Заполните анкету у бота @Visa_Poland_Info_Bot: точность прогнозов зависит "
    "от ваших данных."
)

with open(ROOT / "assets" / "avatar_3_minimal.png", "rb") as photo:
    r = requests.post(
        f"{API}/setChatPhoto",
        data={"chat_id": CHAT_ID},
        files={"photo": ("avatar.png", photo, "image/png")},
        timeout=60,
    ).json()
print("setChatPhoto:", r.get("ok") or r)

r = requests.post(
    f"{API}/setChatDescription",
    json={"chat_id": CHAT_ID, "description": DESCRIPTION},
    timeout=30,
).json()
print("setChatDescription:", r.get("ok") or r)
print("len(description) =", len(DESCRIPTION))
