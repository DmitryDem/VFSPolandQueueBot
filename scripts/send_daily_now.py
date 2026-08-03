"""Разовая ручная публикация ежедневной сводки (после фикса разбивки на части)."""
from pathlib import Path

import paramiko

REMOTE = r'''
import asyncio, os
os.chdir("/opt/vfsbot")
from dotenv import load_dotenv
load_dotenv()
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from src import stats
from src.report_flow import CHAT_ID, CITIES, VISA_TYPES, TOPICS
from main import _split_message, _send_ranking_charts

async def go():
    bot = Bot(token=os.environ["BOT_TOKEN"],
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    topic = TOPICS["service_topics"].get("stats")
    text = stats.build_daily_summary(CITIES, VISA_TYPES)
    if not text:
        print("нет данных"); await bot.session.close(); return
    parts = _split_message(text)
    print("длина текста:", len(text), "| частей:", len(parts))
    for p in parts:
        await bot.send_message(chat_id=CHAT_ID, message_thread_id=topic, text=p)
    await _send_ranking_charts(bot, topic)
    print("опубликовано")
    await bot.session.close()

asyncio.run(go())
'''
ROOT = Path(__file__).resolve().parent.parent
key = paramiko.Ed25519Key.from_private_key_file(str(ROOT / ".ssh" / "vfsbot_deploy"))
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("83.168.90.41", username="root", pkey=key, timeout=30)
sftp = ssh.open_sftp()
with sftp.open("/tmp/sdn.py", "wb") as fh:
    fh.write(REMOTE.encode("utf-8"))
sftp.close()
_, out, err = ssh.exec_command(
    "cd /opt/vfsbot && runuser -u vfsbot -- /opt/vfsbot/.venv/bin/python /tmp/sdn.py; rm -f /tmp/sdn.py",
    timeout=90)
print(out.read().decode())
e = err.read().decode()
if e.strip():
    print("ERR:", e)
ssh.close()
