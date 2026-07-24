"""Перезапуск службы vfsbot на VPS и показ свежего лога."""
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)

ssh.exec_command("systemctl restart vfsbot")[1].channel.recv_exit_status()
time.sleep(7)
_, out, _ = ssh.exec_command("systemctl is-active vfsbot && journalctl -u vfsbot -n 10 --no-pager")
print(out.read().decode())
ssh.close()
