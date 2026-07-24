"""Деплой бота на VPS: файлы -> /opt/vfsbot, venv, systemd-служба vfsbot.

Вход по ключу .ssh/vfsbot_deploy (дефолт); переопределение — env-переменные
DEPLOY_HOST, DEPLOY_USER, DEPLOY_KEY или DEPLOY_PASSWORD.
"""
import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
HOST = os.environ.get("DEPLOY_HOST", "83.168.90.41")
USER = os.environ.get("DEPLOY_USER", "root")
KEY_PATH = os.environ.get("DEPLOY_KEY", str(ROOT / ".ssh" / "vfsbot_deploy"))
PASSWORD = os.environ.get("DEPLOY_PASSWORD")

APP_DIR = "/opt/vfsbot"
FILES = [
    "main.py",
    "backup.py",
    "requirements.txt",
    ".env",
    "src/__init__.py",
    "src/browse_flow.py",
    "src/captcha.py",
    "src/db.py",
    "src/notifier.py",
    "src/report_flow.py",
    "src/stats.py",
    "src/stats_flow.py",
    "src/topic_logger.py",
    "config/topics.json",
]

SERVICE = """\
[Unit]
Description=VFS Poland queue Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={app}
ExecStart={app}/.venv/bin/python main.py
Restart=always
RestartSec=5
Environment=TZ=Europe/Minsk
User=vfsbot
Group=vfsbot

[Install]
WantedBy=multi-user.target
""".format(app=APP_DIR)


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 600) -> str:
    print(f"$ {cmd}")
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.strip()[:3000])
    if code != 0:
        print(f"STDERR: {err.strip()[:3000]}")
        raise RuntimeError(f"command failed ({code}): {cmd}")
    return out


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if PASSWORD:
        ssh.connect(HOST, username=USER, password=PASSWORD, timeout=30)
    else:
        key = paramiko.Ed25519Key.from_private_key_file(KEY_PATH)
        ssh.connect(HOST, username=USER, pkey=key, timeout=30)
    print(f"connected to {HOST}")

    run(ssh, "cat /etc/os-release | head -2")
    run(ssh, "DEBIAN_FRONTEND=noninteractive apt-get update -q", timeout=600)
    run(ssh, "DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-venv python3-pip", timeout=900)

    run(ssh, "id -u vfsbot >/dev/null 2>&1 || useradd -r -m -s /usr/sbin/nologin vfsbot")
    run(ssh, f"mkdir -p {APP_DIR}/src {APP_DIR}/config {APP_DIR}/data")

    sftp = ssh.open_sftp()
    for rel in FILES:
        local = ROOT / rel
        remote = f"{APP_DIR}/{rel}"
        sftp.put(str(local), remote)
        print(f"uploaded {rel}")
    with sftp.open(f"{APP_DIR}/deploy.service.tmp", "w") as f:
        f.write(SERVICE)
    sftp.close()

    run(ssh, f"test -d {APP_DIR}/.venv || python3 -m venv {APP_DIR}/.venv")
    run(ssh, f"{APP_DIR}/.venv/bin/pip install -q -r {APP_DIR}/requirements.txt", timeout=900)

    run(ssh, f"mv {APP_DIR}/deploy.service.tmp /etc/systemd/system/vfsbot.service")
    run(ssh, f"chown -R vfsbot:vfsbot {APP_DIR}")
    run(ssh, "systemctl daemon-reload && systemctl enable vfsbot")
    print("\nГотово к запуску. Службу стартуем отдельной командой.")
    ssh.close()


if __name__ == "__main__":
    main()
