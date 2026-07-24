"""Сброс тестовых данных: удаляет публикации бота из тем и очищает базу отчётов."""
import os
import sqlite3
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
API = f"https://api.telegram.org/bot{TOKEN}"
DB = ROOT / "data" / "reports.db"

# известные тестовые сообщения пользователей времён настройки тем
EXTRA_MESSAGE_IDS = [20, 22, 23, 24, 25]


def delete_message(message_id: int) -> None:
    resp = requests.post(
        f"{API}/deleteMessage",
        json={"chat_id": CHAT_ID, "message_id": message_id},
        timeout=30,
    ).json()
    status = "ok" if resp.get("ok") else resp.get("description")
    print(f"delete {message_id}: {status}")
    time.sleep(0.5)


def main() -> None:
    if DB.exists():
        conn = sqlite3.connect(DB)
        rows = conn.execute(
            "SELECT id, message_id FROM reports WHERE message_id IS NOT NULL"
        ).fetchall()
        for report_id, message_id in rows:
            delete_message(message_id)
        deleted = conn.execute("DELETE FROM reports").rowcount
        conn.commit()
        conn.close()
        print(f"DB: удалено {deleted} отчётов")
    else:
        print("DB не найдена — пропускаю")

    for mid in EXTRA_MESSAGE_IDS:
        delete_message(mid)


if __name__ == "__main__":
    main()
