"""Помечает анкеты пользователя сомнительными и шлёт админу карточки модерации.

Запуск: python flag_suspect.py <username_без_@>
"""
import sys
from pathlib import Path

import paramiko

USERNAME = sys.argv[1] if len(sys.argv) > 1 else "perfectengenen"

REMOTE = '''
import os, sqlite3, sys
from datetime import datetime
sys.path.insert(0, "/opt/vfsbot")
from dotenv import load_dotenv
load_dotenv("/opt/vfsbot/.env")
import requests

USERNAME = "__USERNAME__"
conn = sqlite3.connect("/opt/vfsbot/data/reports.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT * FROM reports WHERE username = ?", (USERNAME,)).fetchall()
if not rows:
    print("анкеты пользователя не найдены")
    sys.exit(0)

TOKEN = os.environ["BOT_TOKEN"]
ADMIN = os.environ["ADMIN_CHAT_ID"]
LABELS = {"D_OTHER": "D (Other)", "D_DRIVER": "D (Driver)",
          "D_WORK": "D (Work)", "C_OTHER": "C (Other)"}

def fmt(iso):
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d.%m.%Y") if iso else "—"

for r in rows:
    wait = None
    if r["letter_date"]:
        wait = (datetime.strptime(r["letter_date"], "%Y-%m-%d")
                - datetime.strptime(r["queue_date"], "%Y-%m-%d")).days
    print("id=" + str(r["id"]) + " " + r["city"] + "/" + r["visa_type"]
          + " очередь=" + str(r["queue_date"]) + " письмо=" + str(r["letter_date"])
          + " ожидание=" + str(wait) + " suspect=" + str(r["suspect"]))
    conn.execute("UPDATE reports SET suspect = 1 WHERE id = ?", (r["id"],))
    conn.commit()
    text = ("⚠️ <b>Сомнительная анкета</b> (помечена вручную; в статистике не учитывается)\\n\\n"
            + "🏙 " + r["city"] + " · " + LABELS[r["visa_type"]] + "\\n"
            + "👤 @" + str(r["username"]) + " (id " + str(r["user_id"]) + ")\\n"
            + "⏳ Очередь: " + fmt(r["queue_date"]) + " → 📬 письмо: " + fmt(r["letter_date"])
            + (" = <b>" + str(wait) + " дн.</b>" if wait is not None else ""))
    rid = str(r["id"])
    resp = requests.post(
        "https://api.telegram.org/bot" + TOKEN + "/sendMessage",
        json={
            "chat_id": ADMIN, "text": text, "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": [
                [{"text": "🗑 Удалить", "callback_data": "adm:del:" + rid},
                 {"text": "👌 Оставить", "callback_data": "adm:keep:" + rid}],
                [{"text": "✅ Доверять (в статистику)", "callback_data": "adm:trust:" + rid}],
            ]},
        },
        timeout=30,
    ).json()
    print("карточка отправлена:", resp.get("ok"))
conn.close()
'''.replace("__USERNAME__", USERNAME)

ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)
sftp = ssh.open_sftp()
with sftp.open("/tmp/flag_suspect_remote.py", "wb") as f:
    f.write(REMOTE.encode("utf-8"))
sftp.close()
_, out, err = ssh.exec_command(
    "runuser -u vfsbot -- /opt/vfsbot/.venv/bin/python /tmp/flag_suspect_remote.py && rm /tmp/flag_suspect_remote.py",
    timeout=120,
)
print(out.read().decode())
e = err.read().decode()
if e.strip():
    print("ERR:", e)
ssh.close()
