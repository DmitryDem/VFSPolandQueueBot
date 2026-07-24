"""Полный трейсбек последней ошибки + тип падающего апдейта."""
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)

cmds = [
    ("Полный трейсбек (последний случай)",
     "journalctl -u vfsbot --since '1 day ago' --no-pager | grep -A60 'Cause exception while process update id=359818629' | head -70"),
    ("Первые ошибки этого типа (когда началось)",
     "journalctl -u vfsbot --since '7 days ago' --no-pager | grep 'Cause exception' | head -3"),
    ("Ошибки по дням",
     "journalctl -u vfsbot --since '7 days ago' --no-pager | grep 'Cause exception' | awk '{print $1, $2}' | sort | uniq -c"),
]
for title, cmd in cmds:
    _, out, err = ssh.exec_command(cmd, timeout=120)
    print(f"=== {title} ===")
    print(out.read().decode().strip() or "(пусто)")
    print()
ssh.close()
