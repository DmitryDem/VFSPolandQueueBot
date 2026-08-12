"""Публикует и закрепляет приветственный пост с кнопками в «Общении» и «Статистике».
Обновляет описание группы (упоминание бота)."""
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
GENERAL = TOPICS["service_topics"]["general"]
STATS = TOPICS["service_topics"].get("stats")
BOT = requests.get(f"{API}/getMe", timeout=30).json()["result"]["username"]
base = f"https://t.me/{BOT}?start="

TEXT = (
    "👋 <b>Добро пожаловать!</b>\n\n"
    "Это группа-статистика очереди на польскую визу (VFS Global, Беларусь). "
    "Все действия — через нашего бота, прямо тут в кнопках:\n\n"
    "📝 <b>Анкета</b> — поделитесь своими датами (постановка в очередь, письмо-приглашение). "
    "Чем больше данных — тем точнее прогнозы для всех.\n"
    "📊 <b>Статистика</b> — скорость очереди, даты приглашений, прогноз ожидания по городам.\n"
    "🔮 <b>Мой прогноз</b> — когда ждать письмо именно вам.\n"
    "📋 <b>Документы и сборы</b> — что нужно для подачи, справочно.\n\n"
    "Темы городов — витрины статистики (пишет только бот). "
    "Свои данные вносите кнопкой «Анкета» здесь или в теме своего города.\n\n"
    f"➡️ Не видите кнопки выше? Откройте бота напрямую: @{BOT}"
)
KB = {"inline_keyboard": [
    [{"text": "📝 Заполнить анкету", "url": f"{base}go"}],
    [{"text": "📊 Статистика", "url": f"{base}menu_stats"},
     {"text": "🔮 Мой прогноз", "url": f"{base}menu_my"}],
    [{"text": "📋 Документы и сборы", "url": f"{base}docs"}],
]}

DESCRIPTION = (
    "Очередь на польскую визу (VFS Global, Беларусь): статистика и прогнозы от участников. "
    "Как пользоваться: напишите боту @" + BOT + " — заполнить анкету, статистика, прогноз, "
    "документы. Точность прогнозов зависит от ваших данных."
)


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


for name, tid in [("Общение", GENERAL), ("Статистика", STATS)]:
    if not tid:
        continue
    msg = call("sendMessage", chat_id=CHAT_ID, message_thread_id=tid,
               text=TEXT, parse_mode="HTML", reply_markup=KB)
    if isinstance(msg, dict) and "__error__" in msg:
        print(f"FAIL post {name}: {msg['__error__']}")
        continue
    time.sleep(1.5)
    call("pinChatMessage", chat_id=CHAT_ID, message_id=msg["message_id"], disable_notification=True)
    print(f"pinned in {name}: msg {msg['message_id']}")
    time.sleep(1.5)

print(f"description length: {len(DESCRIPTION)}")
r = call("setChatDescription", chat_id=CHAT_ID, description=DESCRIPTION)
print("setChatDescription:", "ok" if r is True or (isinstance(r, dict) and "__error__" not in r) else r)
