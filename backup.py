"""Ежедневный дамп базы анкет: копия -> gzip -> ротация 30 дней -> отправка админу в Telegram."""
import gzip
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DB = ROOT / "data" / "reports.db"
BACKUPS = ROOT / "backups"
KEEP_DAYS = 30


def _health_line() -> str:
    """Однострочная сводка здоровья сервера для подписи к бэкапу."""
    import shutil as _shutil

    parts = []
    try:
        conn = sqlite3.connect(DB)
        n = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        conn.close()
        parts.append(f"📋 анкет: {n}")
    except Exception:
        pass
    try:
        disk = _shutil.disk_usage("/")
        parts.append(
            f"💾 диск: {disk.used / 1e9:.1f}/{disk.total / 1e9:.1f} ГБ "
            f"({100 * disk.used // disk.total}%)"
        )
    except Exception:
        pass
    try:
        mem = {}
        for line in open("/proc/meminfo"):
            key, val = line.split(":", 1)
            mem[key] = int(val.strip().split()[0])  # кБ
        used = (mem["MemTotal"] - mem["MemAvailable"]) / 1024 / 1024
        total = mem["MemTotal"] / 1024 / 1024
        parts.append(f"🧠 RAM: {used:.1f}/{total:.1f} ГБ")
    except Exception:
        pass
    try:
        parts.append(f"⚙️ load: {os.getloadavg()[1]:.2f}")
    except Exception:
        pass
    return " · ".join(parts)


def main() -> None:
    if not DB.exists():
        print("база ещё не создана — бэкапить нечего")
        return
    BACKUPS.mkdir(exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    raw = BACKUPS / f"reports-{stamp}.db"
    gz = raw.with_suffix(".db.gz")

    # консистентная копия даже при работающем боте
    src = sqlite3.connect(DB)
    dst = sqlite3.connect(raw)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()

    with open(raw, "rb") as f_in, gzip.open(gz, "wb") as f_out:
        f_out.write(f_in.read())
    raw.unlink()
    print(f"дамп: {gz.name} ({gz.stat().st_size} байт)")

    # ротация
    cutoff = time.time() - KEEP_DAYS * 86400
    for old in BACKUPS.glob("reports-*.db.gz"):
        if old.stat().st_mtime < cutoff:
            old.unlink()
            print(f"удалён старый: {old.name}")

    # офсайт-копия админу в личку (в подписи — здоровье сервера)
    token = os.environ["BOT_TOKEN"]
    admin = os.environ.get("ADMIN_CHAT_ID")
    if not admin:
        print("ADMIN_CHAT_ID не задан — отправка пропущена")
        return
    with open(gz, "rb") as doc:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={
                "chat_id": admin,
                "caption": f"Бэкап базы анкет {stamp}\n{_health_line()}",
                "disable_notification": True,
            },
            files={"document": (gz.name, doc, "application/gzip")},
            timeout=120,
        ).json()
    if not resp.get("ok"):
        print(f"ошибка отправки в Telegram: {resp}", file=sys.stderr)
        sys.exit(1)
    print("отправлен админу в Telegram")


if __name__ == "__main__":
    main()
