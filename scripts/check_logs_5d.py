"""Сводка логов бота за последние 5 дней."""
from pathlib import Path

import paramiko

SINCE = "5 days ago"
ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)

cmds = [
    ("Ошибки/трейсбеки за 5 дней",
     f"journalctl -u vfsbot --since '{SINCE}' --no-pager | grep -cE 'Cause exception|Traceback' || true"),
    ("Тексты ошибок (типы)",
     f"journalctl -u vfsbot --since '{SINCE}' --no-pager | grep -oE 'aiogram.exceptions.[A-Za-z]+|Traceback' | sort | uniq -c"),
    ("Последние ошибки (когда)",
     f"journalctl -u vfsbot --since '{SINCE}' --no-pager | grep 'Cause exception' | tail -5"),
    ("Капча: отправлено / одобрено",
     f"echo -n 'отправлено: '; journalctl -u vfsbot --since '{SINCE}' | grep -c 'капча отправлена' || true; "
     f"echo -n 'одобрено: '; journalctl -u vfsbot --since '{SINCE}' | grep -c 'заявка одобрена' || true"),
    ("Модерация / всплески",
     f"journalctl -u vfsbot --since '{SINCE}' --no-pager | grep -iE 'спайк|всплеск|Очередь двинул|SendingCancel' | tail -5"),
    ("Перезапуски (деплои)",
     f"journalctl -u vfsbot --since '{SINCE}' | grep -c 'Start polling' || true"),
    ("Служба сейчас",
     "systemctl status vfsbot --no-pager | grep -E 'Active|Memory'"),
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
th = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(timespec="seconds")
total = c.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
new = c.execute("SELECT COUNT(*) FROM reports WHERE created_at > ?", (th,)).fetchone()[0]
upd = c.execute("SELECT COUNT(*) FROM reports WHERE updated_at > ?", (th,)).fetchone()[0]
susp = c.execute("SELECT COUNT(*) FROM reports WHERE suspect = 1").fetchone()[0]
lbl = c.execute("SELECT COUNT(*) FROM reports WHERE label IS NOT NULL").fetchone()[0]
ev = c.execute("SELECT event, COUNT(*) FROM events WHERE created_at > ? GROUP BY event", (th,)).fetchall()
print("анкет всего:", total, "| новых за 5 дн:", new, "| обновлено:", upd)
print("сомнительных:", susp, "| с меткой (мульти):", lbl)
print("воронка за 5 дн:", {r[0]: r[1] for r in ev})
c.close()
'''
sftp = ssh.open_sftp()
with sftp.open("/tmp/l5.py", "wb") as f:
    f.write(remote.encode("utf-8"))
sftp.close()
_, out, _ = ssh.exec_command(
    "runuser -u vfsbot -- /opt/vfsbot/.venv/bin/python /tmp/l5.py; rm -f /tmp/l5.py", timeout=60
)
print("=== БД за 5 дней ===")
print(out.read().decode().strip())
ssh.close()
