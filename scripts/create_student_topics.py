"""Создаёт темы D (Student) для Гомеля, Минска, Витебска: создать -> закрыть -> иконка 📆.
Публикует и закрепляет кнопки. Печатает {город: id}."""
import json
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
CAL_ICON = "5433614043006903194"
YELLOW = 16766590

TOPICS = json.loads((ROOT / "config" / "topics.json").read_text("utf-8"))
CITIES = list(TOPICS["cities"].keys())
BOT = requests.get(f"{API}/getMe", timeout=30).json()["result"]["username"]

TARGET = ["Гомель", "Минск", "Витебск"]
LABEL = "Национальная D (Student)"


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
for city in TARGET:
    t = call("createForumTopic", chat_id=CHAT_ID, name=f"{city} (D Student)", icon_color=YELLOW)
    tid = t["message_thread_id"]
    result[city] = tid
    print(f"created: {city} (D Student) -> {tid}")
    time.sleep(3)
    call("closeForumTopic", chat_id=CHAT_ID, message_thread_id=tid)
    time.sleep(2)
    call("editForumTopic", chat_id=CHAT_ID, message_thread_id=tid, icon_custom_emoji_id=CAL_ICON)
    time.sleep(2)

    idx = CITIES.index(city)
    base = f"https://t.me/{BOT}?start="
    text = (
        f"Встали в очередь VFS — <b>{city}, {LABEL}</b>?\n"
        "Поделитесь своими датами: это поможет всем оценить скорость очереди.\n\n"
        "📝 <b>Анкета</b> — заполните один раз, дальше дополняйте по мере продвижения.\n"
        "📊 <b>Статистика</b> — сводка, графики и прогноз по этой теме.\n"
        "🔮 <b>Мой прогноз</b> — когда ждать письмо именно вам."
    )
    kb = {"inline_keyboard": [
        [{"text": "📝 Заполнить / обновить анкету", "url": f"{base}r_{idx}_D_STUDENT"}],
        [{"text": "📊 Статистика очереди", "url": f"{base}s_{idx}_D_STUDENT"}],
        [{"text": "🔮 Мой прогноз", "url": f"{base}m_{idx}_D_STUDENT"}],
    ]}
    msg = call("sendMessage", chat_id=CHAT_ID, message_thread_id=tid,
               text=text, parse_mode="HTML", reply_markup=kb)
    time.sleep(1.5)
    call("pinChatMessage", chat_id=CHAT_ID, message_id=msg["message_id"], disable_notification=True)
    print(f"pinned: {city} (msg {msg['message_id']})")
    time.sleep(1.5)

print(json.dumps(result, ensure_ascii=False))
