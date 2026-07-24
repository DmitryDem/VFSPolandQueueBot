"""Смотрит содержимое reports на VPS."""
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)

cmd = (
    "/opt/vfsbot/.venv/bin/python - <<'EOF'\n"
    "import sqlite3\n"
    "try:\n"
    "    conn = sqlite3.connect('/opt/vfsbot/data/reports.db')\n"
    "    rows = conn.execute('SELECT id, user_id, city, visa_type, queue_date, letter_date FROM reports').fetchall()\n"
    "    print('rows:', len(rows))\n"
    "    for r in rows:\n"
    "        print(r)\n"
    "except Exception as e:\n"
    "    print('err:', e)\n"
    "EOF"
)
_, out, err = ssh.exec_command(cmd, timeout=60)
print(out.read().decode())
e = err.read().decode()
if e.strip():
    print("STDERR:", e)
ssh.close()
