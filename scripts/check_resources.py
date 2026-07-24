"""Снимок ресурсов VPS: CPU, RAM, диск, нагрузка, потребление бота."""
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)

cmds = [
    ("CPU", "nproc && cat /proc/cpuinfo | grep 'model name' | head -1"),
    ("Load average", "uptime"),
    ("Память", "free -h"),
    ("Диск", "df -h / /opt"),
    ("Топ процессов по памяти", "ps aux --sort=-%mem | head -8"),
    ("Служба vfsbot", "systemctl status vfsbot --no-pager | grep -E 'Memory|CPU|Active' ; ps -o pid,%cpu,%mem,rss,etime,cmd -C python | head -5"),
    ("Размер данных бота", "du -sh /opt/vfsbot /opt/vfsbot/data /opt/vfsbot/backups 2>/dev/null"),
]
for title, cmd in cmds:
    _, out, err = ssh.exec_command(cmd, timeout=60)
    print(f"=== {title} ===")
    print(out.read().decode().strip() or err.read().decode().strip())
    print()
ssh.close()
