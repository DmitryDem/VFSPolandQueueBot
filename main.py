"""Точка входа: Telegram-бот сбора статистики очереди на польскую визу."""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BotCommand, BotCommandScopeAllPrivateChats, ErrorEvent, FSInputFile,
    InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto,
)
from dotenv import load_dotenv

from src import stats
from src.browse_flow import router as browse_router
from src.captcha import router as captcha_router
from src.docs_flow import router as docs_router
from src.report_flow import CHAT_ID, CITIES, TOPICS, VISA_TYPES, router
from src.stats_flow import router as stats_router
from src.topic_logger import router as topic_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("matplotlib").setLevel(logging.WARNING)  # не спамить info при построении графиков
log = logging.getLogger("main")

DAILY_SUMMARY_HOUR = 9  # локальное время ежедневной сводки

# Ссылка на группу — для кнопки под постами канала (канал ведёт в группу)
GROUP_URL = "https://t.me/vfspolandstats"


TELEGRAM_MSG_LIMIT = 4096


def _split_message(text: str, limit: int = 3900) -> list[str]:
    """Режет длинный текст на части по границам строк (лимит Telegram — 4096)."""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for line in text.split("\n"):
        # одна строка длиннее лимита — жёстко режем по символам (крайне маловероятно)
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def _channel_id() -> int | str | None:
    """Публичный канал для дублирования сводки (опционально). ID (int) или @username."""
    v = os.environ.get("CHANNEL_ID")
    if not v:
        return None
    return int(v) if v.lstrip("-").isdigit() else v


async def daily_summary_loop(bot: Bot) -> None:
    stats_topic = TOPICS["service_topics"].get("stats")
    if not stats_topic:
        log.warning("Тема «Статистика» не настроена — автосводка выключена")
        return
    channel_id = _channel_id()
    while True:
        now = datetime.now()
        target = now.replace(hour=DAILY_SUMMARY_HOUR, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            text = stats.build_daily_summary(CITIES, VISA_TYPES)
            if not text:
                log.info("Ежедневная сводка пропущена: данных нет")
                continue
            paths = _render_ranking_charts() + stats.render_wait_charts()
            channel_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💬 Обсуждение и анкета — в группе", url=GROUP_URL)
            ]])
            try:
                await _publish_summary(bot, text, paths, CHAT_ID, stats_topic)
                if channel_id:
                    await _publish_summary(bot, text, paths, channel_id, None, reply_markup=channel_kb)
            finally:
                for p in paths:
                    Path(p).unlink(missing_ok=True)
            log.info("Ежедневная сводка опубликована%s", " (+канал)" if channel_id else "")
        except Exception:
            log.exception("Ошибка публикации ежедневной сводки")


async def membership_refresh_loop(bot: Bot) -> None:
    """Раз в сутки (08:30) обновляет членство ожидающих: ушедшие исключаются из KM-оценки."""
    from src import db

    while True:
        now = datetime.now()
        target = now.replace(hour=8, minute=30, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            uids = db.waiting_user_ids()
            checked = left = 0
            for uid in uids:
                try:
                    m = await bot.get_chat_member(CHAT_ID, uid)
                    st = m.status
                    in_group = st not in ("left", "kicked") and not (
                        st == "restricted" and getattr(m, "is_member", True) is False
                    )
                    db.set_membership(uid, in_group)
                    checked += 1
                    if not in_group:
                        left += 1
                except Exception:
                    pass
                await asyncio.sleep(0.12)
            log.info("Членство обновлено: проверено %d, ушедших %d", checked, left)
        except Exception:
            log.exception("Ошибка обновления членства")


def _render_ranking_charts() -> list[str]:
    """Рейтинг городов по медиане ожидания — по одному графику на категорию с данными."""
    paths = []
    for visa, label in VISA_TYPES.items():
        entries = []
        for city in CITIES:
            s = stats.collect_cached(city, visa)
            if s.median_wait is not None:
                entries.append((city, s.median_wait))
        chart = stats.render_city_ranking(label, entries)
        if chart:
            paths.append(chart)
    return paths


async def _publish_summary(bot: Bot, text: str, chart_paths: list[str],
                           chat_id: int | str, thread_id: int | None,
                           reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Публикует текст сводки (с разбивкой) и графики в один адресат (тему или канал).

    reply_markup (если задан) отправляется отдельным финальным сообщением ПОСЛЕ
    графиков — так кнопка-ссылка в группу оказывается в самом низу поста (медиа-группа
    свои кнопки нести не может).
    """
    for chunk in _split_message(text):
        await bot.send_message(chat_id=chat_id, message_thread_id=thread_id, text=chunk)
    if chart_paths:
        if len(chart_paths) == 1:
            await bot.send_photo(chat_id=chat_id, message_thread_id=thread_id,
                                 photo=FSInputFile(chart_paths[0]))
        else:
            media = [InputMediaPhoto(media=FSInputFile(p)) for p in chart_paths]
            await bot.send_media_group(chat_id=chat_id, message_thread_id=thread_id, media=media)
    if reply_markup:
        await bot.send_message(
            chat_id=chat_id, message_thread_id=thread_id,
            text="💬 Вопросы, обсуждение и заполнение анкеты — в нашей группе 👇",
            reply_markup=reply_markup, disable_web_page_preview=True,
        )


# безобидные ошибки Telegram: гасим тихо, чтобы не засорять лог и не рвать обработчик
_BENIGN = ("message is not modified", "query is too old", "message to edit not found",
           "message can't be edited")


async def on_error(event: ErrorEvent) -> bool:
    exc = event.exception
    if isinstance(exc, TelegramBadRequest) and any(s in str(exc) for s in _BENIGN):
        log.debug("benign Telegram error ignored: %s", exc)
        return True  # обработано — не логируем как ERROR
    log.exception("Unhandled update error", exc_info=exc)
    return True


async def main() -> None:
    load_dotenv()
    bot = Bot(
        token=os.environ["BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.errors.register(on_error)
    dp.include_router(captcha_router)
    dp.include_router(docs_router)
    dp.include_router(browse_router)
    dp.include_router(stats_router)
    dp.include_router(router)
    dp.include_router(topic_router)
    await bot.set_my_commands(
        [
            BotCommand(command="report", description="Заполнить/дополнить анкету"),
            BotCommand(command="mine", description="Моя анкета"),
            BotCommand(command="near", description="Люди рядом в очереди"),
            BotCommand(command="list", description="Анкеты по городу"),
            BotCommand(command="queue", description="Очередь города по порядку постановки"),
            BotCommand(command="stats", description="Статистика и прогноз очереди"),
            BotCommand(command="wait", description="Сроки ожидания приглашения (графики)"),
            BotCommand(command="my", description="Персональный прогноз по вашей дате"),
            BotCommand(command="docs", description="Документы, сборы, порядок подачи"),
            BotCommand(command="cancel", description="Отменить текущую анкету"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )
    await bot.delete_webhook(drop_pending_updates=False)
    asyncio.create_task(daily_summary_loop(bot))
    asyncio.create_task(membership_refresh_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
