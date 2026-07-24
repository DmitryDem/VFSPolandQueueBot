"""Точка входа: Telegram-бот сбора статистики очереди на польскую визу."""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, FSInputFile, InputMediaPhoto
from dotenv import load_dotenv

from src import stats
from src.browse_flow import router as browse_router
from src.captcha import router as captcha_router
from src.docs_flow import router as docs_router
from src.report_flow import CHAT_ID, CITIES, TOPICS, VISA_TYPES, router
from src.stats_flow import router as stats_router
from src.topic_logger import router as topic_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("main")

DAILY_SUMMARY_HOUR = 9  # локальное время ежедневной сводки


async def daily_summary_loop(bot: Bot) -> None:
    stats_topic = TOPICS["service_topics"].get("stats")
    if not stats_topic:
        log.warning("Тема «Статистика» не настроена — автосводка выключена")
        return
    while True:
        now = datetime.now()
        target = now.replace(hour=DAILY_SUMMARY_HOUR, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            text = stats.build_daily_summary(CITIES, VISA_TYPES)
            if text:
                await bot.send_message(chat_id=CHAT_ID, message_thread_id=stats_topic, text=text)
                await _send_ranking_charts(bot, stats_topic)
                log.info("Ежедневная сводка опубликована")
            else:
                log.info("Ежедневная сводка пропущена: данных нет")
        except Exception:
            log.exception("Ошибка публикации ежедневной сводки")


async def _send_ranking_charts(bot: Bot, stats_topic: int) -> None:
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
    if not paths:
        return
    try:
        if len(paths) == 1:
            await bot.send_photo(
                chat_id=CHAT_ID, message_thread_id=stats_topic, photo=FSInputFile(paths[0])
            )
        else:
            media = [InputMediaPhoto(media=FSInputFile(p)) for p in paths]
            await bot.send_media_group(chat_id=CHAT_ID, message_thread_id=stats_topic, media=media)
    finally:
        for p in paths:
            Path(p).unlink(missing_ok=True)


async def main() -> None:
    load_dotenv()
    bot = Bot(
        token=os.environ["BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
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
            BotCommand(command="stats", description="Статистика и прогноз очереди"),
            BotCommand(command="my", description="Персональный прогноз по вашей дате"),
            BotCommand(command="docs", description="Документы, сборы, порядок подачи"),
            BotCommand(command="cancel", description="Отменить текущую анкету"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )
    await bot.delete_webhook(drop_pending_updates=False)
    asyncio.create_task(daily_summary_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
