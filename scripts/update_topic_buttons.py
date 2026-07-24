"""Обновляет закреплённые сообщения в городских темах: две кнопки — анкета и статистика."""
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

TOPICS = json.loads((ROOT / "config" / "topics.json").read_text("utf-8"))
CHAT_ID = TOPICS["chat_id"]
CITIES = list(TOPICS["cities"].keys())
TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"

VISA_LABELS = {
    "D_OTHER": "Национальная D (Other)",
    "D_DRIVER": "Национальная D (Driver)",
    "D_WORK": "Национальная D (Work)",
    "C_OTHER": "Шенген C (Other)",
}

BOT_USERNAME = requests.get(f"{API}/getMe", timeout=30).json()["result"]["username"]

# id закреплённых сообщений с кнопками (из логов публикации)
BUTTON_MESSAGES: dict[tuple[str, str], int] = {
    ("Гомель", "D_OTHER"): 128,
    ("Гомель", "D_DRIVER"): 130,
    ("Гомель", "C_OTHER"): 132,
    ("Гомель", "D_WORK"): 200,
    ("Минск", "D_OTHER"): 134, ("Минск", "D_DRIVER"): 136,
    ("Минск", "D_WORK"): 138, ("Минск", "C_OTHER"): 140,
    ("Могилев", "D_OTHER"): 142, ("Могилев", "D_DRIVER"): 144,
    ("Могилев", "D_WORK"): 146, ("Могилев", "C_OTHER"): 148,
    ("Барановичи", "D_OTHER"): 150, ("Барановичи", "D_DRIVER"): 152,
    ("Барановичи", "D_WORK"): 154, ("Барановичи", "C_OTHER"): 156,
    ("Пинск", "D_OTHER"): 158, ("Пинск", "D_DRIVER"): 160,
    ("Пинск", "D_WORK"): 162, ("Пинск", "C_OTHER"): 164,
    ("Брест", "D_OTHER"): 166, ("Брест", "D_DRIVER"): 168,
    ("Брест", "D_WORK"): 170, ("Брест", "C_OTHER"): 172,
    ("Гродно", "D_OTHER"): 174, ("Гродно", "D_DRIVER"): 176,
    ("Гродно", "D_WORK"): 178, ("Гродно", "C_OTHER"): 180,
    ("Лида", "D_OTHER"): 182, ("Лида", "D_DRIVER"): 184,
    ("Лида", "D_WORK"): 186, ("Лида", "C_OTHER"): 188,
    ("Витебск", "D_OTHER"): 190, ("Витебск", "D_DRIVER"): 192,
    ("Витебск", "D_WORK"): 194, ("Витебск", "C_OTHER"): 196,
}
# Гомель D_OTHER публиковался в упавшем прогоне — id неизвестен, подбираем из кандидатов
GOMEL_D_OTHER_CANDIDATES = [126, 127, 128, 129]


def call(method: str, **params):
    while True:
        resp = requests.post(f"{API}/{method}", json=params, timeout=30).json()
        if resp.get("ok"):
            return resp["result"]
        if resp.get("error_code") == 429:
            wait = resp["parameters"]["retry_after"] + 1
            print(f"429, ждём {wait} сек...")
            time.sleep(wait)
            continue
        return {"__error__": resp.get("description")}


def build(city: str, visa: str):
    idx = CITIES.index(city)
    text = (
        f"Встали в очередь VFS — <b>{city}, {VISA_LABELS[visa]}</b>?\n"
        "Поделитесь своими датами: это поможет всем оценить скорость очереди.\n\n"
        "📝 <b>Анкета</b> — заполните один раз, а дальше дополняйте её по мере "
        "продвижения: пришло письмо → записались → подали документы → получили паспорт. "
        "Город и тип визы подставятся автоматически.\n"
        "📊 <b>Статистика</b> — сводка, графики и общий прогноз по этой теме.\n"
        "🔮 <b>Мой прогноз</b> — оценка, когда ждать письмо именно вам."
    )
    kb = {
        "inline_keyboard": [
            [{"text": "📝 Заполнить / обновить анкету",
              "url": f"https://t.me/{BOT_USERNAME}?start=r_{idx}_{visa}"}],
            [{"text": "📊 Статистика очереди",
              "url": f"https://t.me/{BOT_USERNAME}?start=s_{idx}_{visa}"}],
            [{"text": "🔮 Мой прогноз",
              "url": f"https://t.me/{BOT_USERNAME}?start=m_{idx}_{visa}"}],
        ]
    }
    return text, kb


def edit(city: str, visa: str, message_id: int) -> bool:
    text, kb = build(city, visa)
    result = call(
        "editMessageText",
        chat_id=CHAT_ID, message_id=message_id,
        text=text, parse_mode="HTML", reply_markup=kb,
    )
    if isinstance(result, dict) and "__error__" in result:
        print(f"FAIL {city} {visa} (msg {message_id}): {result['__error__']}")
        return False
    expected_tid = TOPICS["cities"][city][visa]
    got_tid = result.get("message_thread_id")
    status = "ok" if got_tid == expected_tid else f"ВНИМАНИЕ: thread {got_tid} != {expected_tid}"
    print(f"edit {city} {visa} (msg {message_id}): {status}")
    return True


for (city, visa), mid in BUTTON_MESSAGES.items():
    edit(city, visa, mid)
    time.sleep(1.5)
