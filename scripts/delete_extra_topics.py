"""Удаляет лишние темы: все D_STUDY и D_KARTA кроме Гродно(1356)/Лида(1362)."""
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
API = f"https://api.telegram.org/bot{TOKEN}"

D_STUDY = [1323, 1329, 1335, 1341, 1347, 1353, 1359, 1365, 1371]
D_KARTA_EXTRA = [1320, 1326, 1332, 1338, 1344, 1350, 1368]  # без Гродно 1356, Лида 1362
TO_DELETE = D_STUDY + D_KARTA_EXTRA


def call(method, **params):
    while True:
        r = requests.post(f"{API}/{method}", json=params, timeout=30).json()
        if r.get("ok"):
            return True
        if r.get("error_code") == 429:
            wait = r["parameters"]["retry_after"] + 1
            print(f"429, ждём {wait} c...")
            time.sleep(wait)
            continue
        print(f"  {method} {params.get('message_thread_id')}: {r.get('description')}")
        return False


for tid in TO_DELETE:
    ok = call("deleteForumTopic", chat_id=CHAT_ID, message_thread_id=tid)
    print(f"deleted {tid}: {'ok' if ok else 'FAIL'}")
    time.sleep(1.5)
print(f"итого удалено тем: {len(TO_DELETE)}")
