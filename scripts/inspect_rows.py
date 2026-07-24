"""Детали конкретных анкет из БД на VPS."""
from pathlib import Path

import paramiko

REMOTE = '''
import sqlite3
conn = sqlite3.connect("/opt/vfsbot/data/reports.db")
conn.row_factory = sqlite3.Row
for rid in (16, 94, 105):
    r = conn.execute("SELECT * FROM reports WHERE id = ?", (rid,)).fetchone()
    if r:
        print({k: r[k] for k in ("id", "user_id", "username", "city", "visa_type",
                                 "queue_date", "queue_time", "letter_date",
                                 "created_at", "updated_at", "message_id", "suspect")})
conn.close()
'''

ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)
sftp = ssh.open_sftp()
with sftp.open("/tmp/inspect_rows.py", "wb") as f:
    f.write(REMOTE.encode("utf-8"))
sftp.close()
_, out, err = ssh.exec_command(
    "runuser -u vfsbot -- /opt/vfsbot/.venv/bin/python /tmp/inspect_rows.py; rm -f /tmp/inspect_rows.py",
    timeout=60,
)
print(out.read().decode())
e = err.read().decode()
if e.strip():
    print("ERR:", e)
ssh.close()
