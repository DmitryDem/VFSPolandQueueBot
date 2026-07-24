"""Заливает и запускает миграцию публикаций на VPS (от пользователя vfsbot)."""
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)

sftp = ssh.open_sftp()
try:
    sftp.mkdir("/opt/vfsbot/scripts")
except IOError:
    pass
sftp.put(str(ROOT / "scripts" / "rollback_to_city_topics.py"), "/opt/vfsbot/scripts/migrate.py")
sftp.close()

cmds = [
    "chown -R vfsbot:vfsbot /opt/vfsbot/scripts",
    "runuser -u vfsbot -- /opt/vfsbot/.venv/bin/python /opt/vfsbot/scripts/migrate.py",
]
for cmd in cmds:
    _, out, err = ssh.exec_command(cmd, timeout=900)
    o, e, c = out.read().decode(), err.read().decode(), out.channel.recv_exit_status()
    print(f"$ {cmd}")
    if o.strip():
        print(o.strip())
    if c != 0:
        print("ERR:", e.strip())
ssh.close()
