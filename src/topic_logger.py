"""Обработчики сообщений в группе.

1. /report в городской теме: команда удаляется (чтобы не засорять readonly-тему),
   а пользователю в личку уходит кнопка с анкетой, где город и тип визы уже выбраны.
2. Логгер ID тем: Bot API не умеет перечислять темы форума, поэтому для каждого
   сообщения в группе пишем в лог название темы и её message_thread_id.
"""
import json
import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

log = logging.getLogger("group")

TOPICS = json.loads(
    (Path(__file__).resolve().parent.parent / "config" / "topics.json").read_text("utf-8")
)
CHAT_ID = TOPICS["chat_id"]

# thread_id -> (город, тип визы)
TOPIC_TO_CITY: dict[int, tuple[str, str]] = {
    tid: (city, visa)
    for city, types in TOPICS["cities"].items()
    for visa, tid in types.items()
    if tid
}

router = Router()
router.message.filter(F.chat.id == CHAT_ID)


@router.message(Command("report", "start"))
async def report_in_topic(message: Message) -> None:
    # Реагируем только в городских темах. В «Общении» и прочих темах бот
    # не вмешивается — там обычная дискуссия участников.
    target = TOPIC_TO_CITY.get(message.message_thread_id)
    if not target or not message.from_user:
        return
    try:
        await message.delete()
    except Exception:
        pass
    from src.report_flow import VISA_TYPES, make_payload  # локальный импорт против цикла

    city, visa = target
    me = await message.bot.me()
    url = f"https://t.me/{me.username}?start={make_payload(city, visa)}"
    try:
        await message.bot.send_message(
            chat_id=message.from_user.id,
            text=f"Заполнить анкету для <b>{city} ({VISA_TYPES[visa]})</b>?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="📝 Открыть анкету", url=url)]]
            ),
        )
    except Exception:
        # пользователь ещё не открывал личку с ботом — написать ему нельзя
        log.info("cannot DM user %s", message.from_user.id)


@router.message()
async def log_topic_message(message: Message) -> None:
    name = "?"
    reply = message.reply_to_message
    if reply and reply.forum_topic_created:
        name = reply.forum_topic_created.name
    log.info(
        "group message: topic=%r thread_id=%s text=%r",
        name,
        message.message_thread_id,
        (message.text or "")[:50],
    )
