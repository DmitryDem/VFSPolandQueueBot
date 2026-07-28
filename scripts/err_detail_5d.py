"""Детали ошибок за 5 дней: полные сообщения, распределение по дням, последний трейсбек."""
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)

cmds = [
    ("Ошибки по дням",
     "journalctl -u vfsbot --since '5 days ago' --no-pager | grep 'Cause exception' | awk '{print $1, $2}' | sort | uniq -c"),
    ("Тексты BadRequest",
     "journalctl -u vfsbot --since '5 days ago' --no-pager | grep 'TelegramBadRequest' | grep -oE 'message.*|chat.*|Bad Request.*' | sort | uniq -c | head"),
    ("Тексты Forbidden",
     "journalctl -u vfsbot --since '5 days ago' --no-pager | grep 'TelegramForbiddenError' | grep -oE 'Forbidden.*' | sort | uniq -c | head"),
    ("Последний полный трейсбек (наш код)",
     "journalctl -u vfsbot --since '5 days ago' --no-pager | grep -A40 'update id=359819441' | grep -E 'src/|Error|line [0-9]' | head -25"),
    ("Ошибки ПОСЛЕ 27.07 (после мульти/удаление/валидация)",
     "journalctl -u vfsbot --since '2026-07-27 00:00' --no-pager | grep -c 'Cause exception' || true"),
]
for title, cmd in cmds:
    _, out, err = ssh.exec_command(cmd, timeout=120)
    print(f"=== {title} ===")
    print(out.read().decode().strip() or "(пусто)")
    print()
ssh.close()
