"""Перенос публикаций анкет из городских тем в единую тему «Анкеты».

Для каждой анкеты из БД: удалить старое сообщение (если было), опубликовать
заново в «Анкеты» (новый формат: шапка города + хэштеги + кнопки), обновить
message_id. Затем закрепить в «Анкеты» сообщение-приглашение с кнопками.

Запускать НА VPS (работает с живой БД): деплой копирует скрипт, запуск по SSH.
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
import os

TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"
TOPICS = json.loads((ROOT / "config" / "topics.json").read_text("utf-8"))
CHAT_ID = TOPICS["chat_id"]
REPORTS_TOPIC = TOPICS["service_topics"]["reports"]
CITIES = list(TOPICS["cities"].keys())
DB = ROOT / "data" / "reports.db"

VISA_LABELS = {
    "D_OTHER": "Национальная D (Other)",
    "D_DRIVER": "Национальная D (Driver)",
    "D_WORK": "Национальная D (Work)",
    "C_OTHER": "Шенген C (Other)",
}
OUTCOME_LABELS = {"APPROVED": "✅ Виза получена", "REFUSED": "❌ В визе отказано"}

BOT_USERNAME = requests.get(f"{API}/getMe", timeout=30).json()["result"]["username"]


def call(method: str, **params):
    while True:
        resp = requests.post(f"{API}/{method}", json=params, timeout=30).json()
        if resp.get("ok"):
            return resp["result"]
        if resp.get("error_code") == 429:
            wait = resp["parameters"]["retry_after"] + 1
            print(f"429, ждём {wait} c...")
            time.sleep(wait)
            continue
        return {"__error__": resp.get("description")}


def fmt(iso):
    if not iso:
        return "—"
    from datetime import datetime

    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d.%m.%Y")


def fmt_slots(slots_json):
    if not slots_json:
        return None
    parts = []
    for start, end in json.loads(slots_json):
        parts.append(fmt(start) if start == end else f"{fmt(start)} – {fmt(end)}")
    return ", ".join(parts)


def build_text(r: sqlite3.Row) -> str:
    from datetime import datetime

    lines = [
        f"🏙 <b>{r['city']} — {VISA_LABELS[r['visa_type']]}</b>",
        f"👤 {'@' + r['username'] if r['username'] else 'аноним'}",
    ]
    when = fmt(r["queue_date"])
    if r["queue_time"]:
        when += f" в {r['queue_time']}"
    lines.append(f"⏳ Встал(а) в очередь: <b>{when}</b>")
    if r["letter_date"]:
        waited = (
            datetime.strptime(r["letter_date"], "%Y-%m-%d")
            - datetime.strptime(r["queue_date"], "%Y-%m-%d")
        ).days
        lines.append(f"📬 Письмо-приглашение: <b>{fmt(r['letter_date'])}</b> (ожидание {waited} дн.)")
    else:
        lines.append("📬 Письмо-приглашение: <b>ещё не пришло</b>")
    slots = fmt_slots(r["slots"])
    if slots:
        lines.append(f"📆 Доступные даты записи: <b>{slots}</b>")
    if r["submit_date"]:
        lines.append(f"📄 Документы поданы: <b>{fmt(r['submit_date'])}</b>")
    if r["passport_date"]:
        lines.append(f"🛂 Паспорт получен: <b>{fmt(r['passport_date'])}</b>")
    if r["outcome"]:
        lines.append(f"<b>{OUTCOME_LABELS[r['outcome']]}</b>")
    visa_tag = r["visa_type"].replace("OTHER", "Other").replace("DRIVER", "Driver").replace("WORK", "Work")
    lines.append(f"\n#{r['city']} #{visa_tag}")
    return "\n".join(lines)


def post_kb(city: str, visa: str) -> dict:
    idx = CITIES.index(city)
    base = f"https://t.me/{BOT_USERNAME}?start="
    return {
        "inline_keyboard": [[
            {"text": "📝 Анкета", "url": f"{base}r_{idx}_{visa}"},
            {"text": "📊 Статистика", "url": f"{base}s_{idx}_{visa}"},
            {"text": "🔮 Прогноз", "url": f"{base}m_{idx}_{visa}"},
        ]]
    }


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM reports ORDER BY id").fetchall()
    print(f"анкет в БД: {len(rows)}")
    for r in rows:
        if r["message_id"]:
            res = call("deleteMessage", chat_id=CHAT_ID, message_id=r["message_id"])
            if isinstance(res, dict) and "__error__" in res:
                print(f"  старое сообщение {r['message_id']}: {res['__error__']}")
        time.sleep(1)
        posted = call(
            "sendMessage",
            chat_id=CHAT_ID,
            message_thread_id=REPORTS_TOPIC,
            text=build_text(r),
            parse_mode="HTML",
            reply_markup=post_kb(r["city"], r["visa_type"]),
        )
        if isinstance(posted, dict) and "__error__" in posted:
            print(f"  FAIL публикация анкеты id={r['id']}: {posted['__error__']}")
            continue
        conn.execute("UPDATE reports SET message_id = ? WHERE id = ?", (posted["message_id"], r["id"]))
        conn.commit()
        print(f"  анкета id={r['id']} ({r['city']}, {r['visa_type']}) -> msg {posted['message_id']}")
        time.sleep(1.5)
    conn.close()

    # закреп-приглашение в «Анкеты»
    base = f"https://t.me/{BOT_USERNAME}?start="
    cta = call(
        "sendMessage",
        chat_id=CHAT_ID,
        message_thread_id=REPORTS_TOPIC,
        text=(
            "📄 <b>Анкеты участников</b> — все города и типы виз в одной ленте.\n\n"
            "• Фильтр: тапните хэштег города (например, #Минск) под любой анкетой.\n"
            "• Просмотр по городу списком, своя анкета, статистика и прогноз — кнопки ниже.\n"
            "• Пришло письмо / подали документы / получили паспорт? Дополните свою анкету!"
        ),
        parse_mode="HTML",
        reply_markup={
            "inline_keyboard": [
                [{"text": "📝 Заполнить / обновить анкету", "url": f"{base}go"}],
                [{"text": "👤 Моя анкета", "url": f"{base}menu_mine"},
                 {"text": "📄 Анкеты по городу", "url": f"{base}menu_list"}],
                [{"text": "📊 Статистика", "url": f"{base}menu_stats"},
                 {"text": "🔮 Мой прогноз", "url": f"{base}menu_my"}],
            ]
        },
    )
    if "__error__" not in cta:
        time.sleep(1)
        call("pinChatMessage", chat_id=CHAT_ID, message_id=cta["message_id"], disable_notification=True)
        print(f"закреп в «Анкеты»: msg {cta['message_id']}")


if __name__ == "__main__":
    main()
