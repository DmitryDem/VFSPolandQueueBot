"""Находит анкеты с датой постановки раньше запуска очереди (08.06.2026),
помечает их сомнительными и шлёт админу карточку модерации."""
from pathlib import Path

import paramiko

REMOTE = '''
import os, sqlite3, sys
from datetime import datetime
sys.path.insert(0, "/opt/vfsbot")
from dotenv import load_dotenv
load_dotenv("/opt/vfsbot/.env")
import requests

QUEUE_START = "2026-06-08"
conn = sqlite3.connect("/opt/vfsbot/data/reports.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT * FROM reports WHERE queue_date < ?", (QUEUE_START,)).fetchall()
print("найдено анкет с ранней датой:", len(rows))

TOKEN = os.environ["BOT_TOKEN"]; ADMIN = os.environ["ADMIN_CHAT_ID"]
LABELS = {"D_OTHER":"D (Other)","D_DRIVER":"D (Driver)","D_WORK":"D (Work)",
          "D_KARTA":"D (Карта поляка)","D_STUDENT":"D (Student)","C_OTHER":"C (Other)"}
def fmt(iso): return datetime.strptime(iso,"%Y-%m-%d").strftime("%d.%m.%Y") if iso else "—"

for r in rows:
    print("id=%s %s/%s очередь=%s письмо=%s suspect=%s user=%s" % (
        r["id"], r["city"], r["visa_type"], r["queue_date"], r["letter_date"],
        r["suspect"], r["username"] or r["user_id"]))
    conn.execute("UPDATE reports SET suspect = 1 WHERE id = ?", (r["id"],))
    conn.commit()
    text = ("⚠️ <b>Ошибочная анкета</b> (дата постановки раньше запуска очереди "
            + fmt(QUEUE_START) + "; помечена сомнительной, в статистике не учитывается)\\n\\n"
            + "🏙 " + r["city"] + " · " + LABELS.get(r["visa_type"], r["visa_type"]) + "\\n"
            + "👤 @" + str(r["username"]) + " (id " + str(r["user_id"]) + ")\\n"
            + "⏳ Очередь: " + fmt(r["queue_date"]) + " → 📬 письмо: " + fmt(r["letter_date"]))
    rid = str(r["id"])
    resp = requests.post("https://api.telegram.org/bot"+TOKEN+"/sendMessage", json={
        "chat_id": ADMIN, "text": text, "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": [
            [{"text":"🗑 Удалить","callback_data":"adm:del:"+rid},
             {"text":"👌 Оставить","callback_data":"adm:keep:"+rid}],
            [{"text":"✅ Доверять (в статистику)","callback_data":"adm:trust:"+rid}],
        ]},
    }, timeout=30).json()
    print("  карточка:", resp.get("ok"))
conn.close()
'''

ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)
sftp = ssh.open_sftp()
with sftp.open("/tmp/flag_early.py", "wb") as f:
    f.write(REMOTE.encode("utf-8"))
sftp.close()
_, out, err = ssh.exec_command(
    "runuser -u vfsbot -- /opt/vfsbot/.venv/bin/python /tmp/flag_early.py; rm -f /tmp/flag_early.py",
    timeout=120,
)
print(out.read().decode())
e = err.read().decode()
if e.strip():
    print("ERR:", e)
ssh.close()
