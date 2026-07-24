"""Сводка логов бота за последние сутки: ошибки, капча, анкеты, активность."""
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)

cmds = [
    ("Ошибки/трейсбеки за сутки",
     "journalctl -u vfsbot --since '1 day ago' --no-pager | grep -cE 'Cause exception|Traceback' || true"),
    ("Тексты ошибок (если есть)",
     "journalctl -u vfsbot --since '1 day ago' --no-pager | grep -E 'ERROR|aiogram.exceptions' | sort | uniq -c | head"),
    ("Капча: отправлено / одобрено",
     "echo -n 'отправлено: '; journalctl -u vfsbot --since '1 day ago' | grep -c 'капча отправлена' || true; "
     "echo -n 'одобрено: '; journalctl -u vfsbot --since '1 day ago' | grep -c 'заявка одобрена' || true"),
    ("Сохранённые анкеты (события saved_new/saved_edit в логах нет — считаем по updates)",
     "journalctl -u vfsbot --since '1 day ago' | grep -c 'is handled' || true"),
    ("Перезапуски службы за сутки",
     "journalctl -u vfsbot --since '1 day ago' | grep -c 'Start polling' || true"),
    ("Служба сейчас",
     "systemctl status vfsbot --no-pager | grep -E 'Active|Memory'"),
    ("Последние 8 значимых строк",
     "journalctl -u vfsbot --since '1 day ago' --no-pager | grep -vE 'is handled|is not handled' | tail -8"),
]
for title, cmd in cmds:
    _, out, err = ssh.exec_command(cmd, timeout=120)
    print(f"=== {title} ===")
    print(out.read().decode().strip() or "(пусто)")
    print()

remote = '''
import sqlite3
from datetime import datetime, timedelta, timezone
c = sqlite3.connect("/opt/vfsbot/data/reports.db"); c.row_factory = sqlite3.Row
th = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
new = c.execute("SELECT COUNT(*) FROM reports WHERE created_at > ?", (th,)).fetchone()[0]
upd = c.execute("SELECT COUNT(*) FROM reports WHERE updated_at > ?", (th,)).fetchone()[0]
total = c.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
ev = c.execute("SELECT event, COUNT(*) FROM events WHERE created_at > ? GROUP BY event", (th,)).fetchall()
print("анкет всего:", total, "| новых за сутки:", new, "| обновлено:", upd)
print("воронка за сутки:", {r[0]: r[1] for r in ev})
c.close()
'''
sftp = ssh.open_sftp()
with sftp.open("/tmp/l24.py", "wb") as f:
    f.write(remote.encode("utf-8"))
sftp.close()
_, out, _ = ssh.exec_command(
    "runuser -u vfsbot -- /opt/vfsbot/.venv/bin/python /tmp/l24.py; rm -f /tmp/l24.py", timeout=60
)
print("=== БД за сутки ===")
print(out.read().decode().strip())
ssh.close()
