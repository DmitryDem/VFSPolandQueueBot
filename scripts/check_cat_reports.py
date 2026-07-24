"""Проверяет, есть ли анкеты по категориям D_KARTA/D_STUDY в БД на VPS."""
from pathlib import Path

import paramiko

REMOTE = '''
import sqlite3
conn = sqlite3.connect("/opt/vfsbot/data/reports.db")
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT id, city, visa_type FROM reports WHERE visa_type IN (?, ?)",
    ("D_KARTA", "D_STUDY"),
).fetchall()
print("анкет по D_KARTA/D_STUDY:", len(rows))
for r in rows:
    print(dict(r))
conn.close()
'''
ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)
sftp = ssh.open_sftp()
with sftp.open("/tmp/chk.py", "wb") as f:
    f.write(REMOTE.encode("utf-8"))
sftp.close()
_, out, _ = ssh.exec_command(
    "runuser -u vfsbot -- /opt/vfsbot/.venv/bin/python /tmp/chk.py; rm -f /tmp/chk.py", timeout=60
)
print(out.read().decode())
ssh.close()
