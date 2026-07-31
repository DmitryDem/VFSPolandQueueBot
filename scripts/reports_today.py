"""Анкеты, созданные сегодня (по Europe/Minsk)."""
from pathlib import Path

import paramiko

REMOTE = r'''
import sqlite3
from datetime import datetime, timezone, timedelta
MINSK = timezone(timedelta(hours=3))
c = sqlite3.connect("/opt/vfsbot/data/reports.db"); c.row_factory = sqlite3.Row
now = datetime.now(MINSK)
start = now.replace(hour=0, minute=0, second=0, microsecond=0)
# created_at хранится в UTC ISO -> сравниваем в UTC
start_utc = start.astimezone(timezone.utc).isoformat(timespec="seconds")
rows = c.execute("SELECT * FROM reports WHERE created_at > ? ORDER BY created_at", (start_utc,)).fetchall()
upd = c.execute("SELECT COUNT(*) FROM reports WHERE updated_at > ? AND created_at <= ?",
                (start_utc, start_utc)).fetchone()[0]
print("дата (Минск):", now.strftime("%d.%m.%Y %H:%M"))
print("новых анкет сегодня:", len(rows))
print("дополнено сегодня (созданы ранее):", upd)
print()
from collections import Counter
by_city = Counter((r["city"], r["visa_type"]) for r in rows)
for (city, visa), n in by_city.most_common():
    print("  %2d  %s / %s" % (n, city, visa))
c.close()
'''
ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)
sftp = ssh.open_sftp()
with sftp.open("/tmp/rt.py", "wb") as fh:
    fh.write(REMOTE.encode("utf-8"))
sftp.close()
_, out, err = ssh.exec_command(
    "runuser -u vfsbot -- /opt/vfsbot/.venv/bin/python /tmp/rt.py; rm -f /tmp/rt.py", timeout=60)
print(out.read().decode())
e = err.read().decode()
if e.strip():
    print("ERR:", e)
ssh.close()
