"""Разовая диагностика: ошибки в обработчиках, воронка капчи, конверсия в анкеты."""
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)

cmds = [
    ("Ошибки/трейсбеки за 7 дней (последние 40 строк)",
     "journalctl -u vfsbot --since '7 days ago' | grep -iE 'Cause exception|Traceback|ERROR' | tail -40"),
    ("Сколько всего ошибок за 7 дней",
     "journalctl -u vfsbot --since '7 days ago' | grep -icE 'Cause exception|Traceback' || true"),
    ("Капча: отправлено в личку (по дням)",
     "journalctl -u vfsbot --since '7 days ago' | grep -oE '^[A-Z][a-z]{2} [0-9]+' -m 10000 --line-buffered < /dev/null; journalctl -u vfsbot --since '7 days ago' | grep 'капча отправлена' | awk '{print $1, $2}' | sort | uniq -c"),
    ("Капча: пройдена/одобрена (по дням)",
     "journalctl -u vfsbot --since '7 days ago' | grep 'заявка одобрена' | awk '{print $1, $2}' | sort | uniq -c"),
    ("Капча: не удалось отправить личку",
     "journalctl -u vfsbot --since '7 days ago' | grep -c 'не удалось отправить капчу' || true"),
    ("Уникальные user_id: капча отправлена",
     "journalctl -u vfsbot --since '7 days ago' | grep -oP 'капча отправлена в личку: user=\\K[0-9]+' | sort -u | wc -l"),
    ("Уникальные user_id: заявка одобрена",
     "journalctl -u vfsbot --since '7 days ago' | grep -oP 'заявка одобрена: user=\\K[0-9]+' | sort -u | wc -l"),
]
for title, cmd in cmds:
    _, out, err = ssh.exec_command(cmd, timeout=120)
    print(f"=== {title} ===")
    o = out.read().decode().strip()
    print(o if o else "(пусто)")
    print()

remote_py = '''
import json, os, sqlite3
from dotenv import load_dotenv
load_dotenv("/opt/vfsbot/.env")
import requests
conn = sqlite3.connect("/opt/vfsbot/data/reports.db")
total = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
users = conn.execute("SELECT COUNT(DISTINCT user_id) FROM reports").fetchone()[0]
week = conn.execute("SELECT COUNT(*) FROM reports WHERE created_at > datetime(\\'now\\', \\'-7 days\\')").fetchone()[0]
conn.close()
TOKEN = os.environ["BOT_TOKEN"]
r = requests.get("https://api.telegram.org/bot" + TOKEN + "/getChatMemberCount",
                 params={"chat_id": os.environ["CHAT_ID"]}, timeout=30).json()
members = r.get("result")
print("участников группы:", members)
print("анкет в базе:", total, "| уникальных авторов:", users, "| анкет за 7 дней:", week)
if members:
    print("конверсия участник->анкета: {:.0f}%".format(100 * users / members))
'''
sftp = ssh.open_sftp()
with sftp.open("/tmp/conv.py", "wb") as f:
    f.write(remote_py.encode("utf-8"))
sftp.close()
_, out, err = ssh.exec_command(
    "runuser -u vfsbot -- /opt/vfsbot/.venv/bin/python /tmp/conv.py; rm -f /tmp/conv.py", timeout=60
)
print("=== Конверсия ===")
print(out.read().decode().strip())
e = err.read().decode()
if e.strip():
    print("ERR:", e)
ssh.close()
