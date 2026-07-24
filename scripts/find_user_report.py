"""Ищет анкеты пользователя в БД на VPS и проверяет их публикации."""
import sys
from pathlib import Path

import paramiko

USERNAME = sys.argv[1] if len(sys.argv) > 1 else "alyonushka_0611"

REMOTE = '''
import sqlite3
conn = sqlite3.connect("/opt/vfsbot/data/reports.db")
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT id, user_id, username, city, visa_type, queue_date, queue_time, "
    "letter_date, message_id, suspect, created_at, updated_at "
    "FROM reports WHERE username LIKE ?", ("%__USERNAME__%",)
).fetchall()
print("найдено анкет:", len(rows))
for r in rows:
    print(dict(r))
total = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
brest = conn.execute(
    "SELECT id, username, queue_date, message_id FROM reports WHERE city = ? AND visa_type = ?",
    ("Брест", "D_OTHER"),
).fetchall()
print("всего анкет в базе:", total)
print("анкеты Брест/D_OTHER:")
for r in brest:
    print(dict(r))
conn.close()
'''.replace("__USERNAME__", USERNAME)

ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)
sftp = ssh.open_sftp()
with sftp.open("/tmp/find_user.py", "wb") as f:
    f.write(REMOTE.encode("utf-8"))
sftp.close()
_, out, err = ssh.exec_command(
    "runuser -u vfsbot -- /opt/vfsbot/.venv/bin/python /tmp/find_user.py && rm /tmp/find_user.py",
    timeout=120,
)
print(out.read().decode())
e = err.read().decode()
if e.strip():
    print("ERR:", e)
ssh.close()
