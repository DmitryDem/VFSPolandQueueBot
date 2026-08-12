"""Локальная выгрузка бэкапов БД с VPS на эту машину.

Скачивает из /opt/vfsbot/backups все дампы, которых ещё нет локально
(зеркалирование). Путь к SSH-ключу определяется автоматически, поэтому
скрипт работает независимо от расположения репозитория.

Локальная папка назначения: C:\\Work\\PetProjects\\TelegramBotBackup
Запуск: python scripts/fetch_backups.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import paramiko

HOST = "83.168.90.41"
USER = "root"
REMOTE_DIR = "/opt/vfsbot/backups"
LOCAL_DIR = Path(r"C:\Work\PetProjects\TelegramBotBackup")

# ключ ищем относительно репозитория (этот файл лежит в <repo>/scripts/)
KEY = Path(__file__).resolve().parent.parent / ".ssh" / "vfsbot_deploy"


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} {msg}"
    print(line)
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    with (LOCAL_DIR / "fetch.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main() -> int:
    if not KEY.exists():
        log(f"ОШИБКА: ключ не найден: {KEY}")
        return 1
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    key = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, pkey=key, timeout=30)
    sftp = ssh.open_sftp()
    remote = [f for f in sftp.listdir(REMOTE_DIR) if f.endswith(".db.gz")]
    have = {p.name for p in LOCAL_DIR.glob("*.db.gz")}
    todo = sorted(f for f in remote if f not in have)
    if not todo:
        log(f"актуально: {len(remote)} дампов, новых нет")
        sftp.close(); ssh.close(); return 0
    for name in todo:
        dst = LOCAL_DIR / name
        sftp.get(f"{REMOTE_DIR}/{name}", str(dst))
        log(f"скачан {name} ({dst.stat().st_size} байт)")
    log(f"готово: скачано {len(todo)}, всего локально {len(have) + len(todo)}")
    sftp.close(); ssh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
