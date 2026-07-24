"""Логи с момента фикса deep-link кнопки (деплой 23.07 ~17:47 UTC)."""
from pathlib import Path

import paramiko

SINCE = "2026-07-23 17:47:00"

ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)

cmds = [
    ("Ошибки после фикса",
     f"journalctl -u vfsbot --since '{SINCE}' --no-pager | grep -cE 'Cause exception|Traceback' || true"),
    ("Тексты ошибок (если есть)",
     f"journalctl -u vfsbot --since '{SINCE}' --no-pager | grep -E 'Cause exception|aiogram.exceptions' | sort | uniq -c | head -10"),
    ("Капча: отправлено",
     f"journalctl -u vfsbot --since '{SINCE}' --no-pager | grep -c 'капча отправлена' || true"),
    ("Капча: одобрено",
     f"journalctl -u vfsbot --since '{SINCE}' --no-pager | grep -c 'заявка одобрена' || true"),
    ("Служба: перезапуски/статус",
     "systemctl status vfsbot --no-pager | grep -E 'Active|Memory'"),
]
for title, cmd in cmds:
    _, out, err = ssh.exec_command(cmd, timeout=120)
    print(f"=== {title} ===")
    print(out.read().decode().strip() or "(пусто)")
    print()

remote_py = '''
import sqlite3
conn = sqlite3.connect("/opt/vfsbot/data/reports.db")
n = conn.execute("SELECT COUNT(*) FROM reports WHERE created_at > ?", ("2026-07-23T17:47:00",)).fetchone()[0]
total = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
print("новых анкет после фикса:", n, "| всего:", total)
'''
sftp = ssh.open_sftp()
with sftp.open("/tmp/cnt.py", "wb") as f:
    f.write(remote_py.encode("utf-8"))
sftp.close()
_, out, _ = ssh.exec_command(
    "runuser -u vfsbot -- /opt/vfsbot/.venv/bin/python /tmp/cnt.py; rm -f /tmp/cnt.py", timeout=60
)
print("=== Анкеты ===")
print(out.read().decode().strip())
ssh.close()
