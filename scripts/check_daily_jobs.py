"""Диагностика ежедневных задач: сводка в «Статистику» + бэкап-дамп админу."""
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)

cmds = [
    ("Публикации ежедневной сводки (7 дней)",
     "journalctl -u vfsbot --since '7 days ago' --no-pager | grep -iE 'Ежедневная сводка|автосводка|daily_summary' || echo '(нет записей)'"),
    ("Ошибки публикации сводки",
     "journalctl -u vfsbot --since '7 days ago' --no-pager | grep -iE 'Ошибка публикации' -A15 || echo '(нет)'"),
    ("backup.timer — статус и расписание",
     "systemctl status vfsbot-backup.timer --no-pager 2>/dev/null | grep -E 'Active|Trigger' ; systemctl list-timers vfsbot-backup* --no-pager 2>/dev/null | head -5"),
    ("backup.service — последние запуски (7 дней)",
     "journalctl -u vfsbot-backup --since '7 days ago' --no-pager | tail -40 || echo '(нет юнита)'"),
    ("Файлы бэкапов на сервере (последние)",
     "ls -la /opt/vfsbot/backups 2>/dev/null | tail -10 || ls -la /opt/vfsbot/data/backups 2>/dev/null | tail -10 || echo '(каталог не найден)'"),
    ("Где ищет ADMIN_CHAT_ID",
     "grep -E 'ADMIN_CHAT_ID' /opt/vfsbot/.env || echo '(нет в .env)'"),
]
for title, cmd in cmds:
    _, out, err = ssh.exec_command(cmd, timeout=60)
    print(f"=== {title} ===")
    o = out.read().decode().strip()
    e = err.read().decode().strip()
    print(o or "(пусто)")
    if e:
        print("STDERR:", e)
    print()
ssh.close()
