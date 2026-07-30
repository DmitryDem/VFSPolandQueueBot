"""Детали анкет, обновлённых за последние сутки."""
from pathlib import Path

import paramiko

REMOTE = r'''
import sqlite3
from datetime import datetime, timedelta, timezone
c = sqlite3.connect("/opt/vfsbot/data/reports.db"); c.row_factory = sqlite3.Row
th = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
rows = c.execute("SELECT * FROM reports WHERE updated_at > ? ORDER BY updated_at DESC", (th,)).fetchall()
print("дополнено анкет за сутки:", len(rows))
print()
def f(x): return x if x else "—"
for r in rows:
    who = ("@"+r["username"]) if r["username"] else ("id"+str(r["user_id"]))
    lbl = (" ["+r["label"]+"]") if r["label"] else ""
    print("id=%s %s%s | %s %s" % (r["id"], who, lbl, r["city"], r["visa_type"]))
    print("   очередь: %s %s | письмо: %s | слоты: %s" % (
        f(r["queue_date"]), f(r["queue_time"]), f(r["letter_date"]), "есть" if r["slots"] else "—"))
    print("   подача: %s | паспорт: %s | результат: %s | виза_дней: %s%s" % (
        f(r["submit_date"]), f(r["passport_date"]), f(r["outcome"]), f(r["visa_days"]),
        " | СОМНИТ." if r["suspect"] else ""))
    print("   создана: %s | обновлена: %s" % (r["created_at"][:16], r["updated_at"][:16]))
    print()
c.close()
'''
ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)
sftp = ssh.open_sftp()
with sftp.open("/tmp/upd.py", "wb") as fh:
    fh.write(REMOTE.encode("utf-8"))
sftp.close()
_, out, err = ssh.exec_command(
    "runuser -u vfsbot -- /opt/vfsbot/.venv/bin/python /tmp/upd.py; rm -f /tmp/upd.py", timeout=60)
print(out.read().decode())
e = err.read().decode()
if e.strip():
    print("ERR:", e)
ssh.close()
