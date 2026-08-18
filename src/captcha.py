"""Капча через заявки на вступление: проверка в личке, в группе — тишина.

Флоу: человек жмёт «Подать заявку» → Telegram разрешает боту написать ему
в личку → бот шлёт кнопку «Я не бот» → по нажатию заявка одобряется.
Заявка не отклоняется по таймауту: кнопку можно нажать в любой момент,
пока заявка активна. Спам-боты в группу не попадают вовсе.

Требуется включить «Одобрение новых участников» в настройках группы.
"""
import html
import json
import logging
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

log = logging.getLogger("captcha")

TOPICS = json.loads(
    (Path(__file__).resolve().parent.parent / "config" / "topics.json").read_text("utf-8")
)
CHAT_ID = TOPICS["chat_id"]
GENERAL_TOPIC = TOPICS["service_topics"]["general"]
GROUP_LINK = f"https://t.me/c/{str(CHAT_ID).removeprefix('-100')}/{GENERAL_TOPIC}"

router = Router()


@router.chat_join_request(F.chat.id == CHAT_ID)
async def on_join_request(event: ChatJoinRequest, bot: Bot) -> None:
    user = event.from_user
    if user.is_bot:
        return
    try:
        await bot.send_message(
            chat_id=user.id,
            text=(
                f"👋 {html.escape(user.full_name)}, вы подали заявку в группу "
                "<b>VFS Poland Stats</b>.\n\n"
                "Подтвердите, что вы человек, — нажмите кнопку, и заявка будет "
                "одобрена автоматически."
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Я не бот", callback_data=f"captcha:{user.id}")]
                ]
            ),
        )
        log.info("капча отправлена в личку: user=%s", user.id)
    except Exception:
        # личка недоступна (например, бот в блоке) — заявка останется висеть админам
        log.exception("не удалось отправить капчу в личку user=%s", user.id)


@router.callback_query(F.data.startswith("captcha:"))
async def on_captcha_click(callback: CallbackQuery) -> None:
    user_id = int(callback.data.split(":", 1)[1])
    if callback.from_user.id != user_id:
        await callback.answer("Эта кнопка для другого пользователя.", show_alert=True)
        return
    try:
        await callback.bot.approve_chat_join_request(CHAT_ID, user_id)
    except Exception as e:
        # заявка отозвана/уже обработана
        log.warning("approve_chat_join_request user=%s: %s", user_id, e)
        await callback.answer(
            "Не нашёл активную заявку. Подайте заявку в группу ещё раз.", show_alert=True
        )
        return
    me = await callback.bot.me()
    try:
        await callback.message.edit_text(
            "🎉 <b>Заявка одобрена — вы в группе!</b>\n\n"
            "Встали в очередь VFS? Заполните анкету прямо сейчас — это займёт минуту, "
            "а статистика и прогнозы группы станут точнее.\n\n"
            "Подсказки:\n"
            "• Темы городов — витрины статистики, писать в них может только бот.\n"
            "• Анкета: кнопка ниже, команда /report или кнопки под сообщениями в темах.\n"
            "• Очередь по порядку постановки (город + тип визы) — /queue; "
            "«люди рядом» с вами — /near; все анкеты города — /list.\n"
            "• Статистика и прогноз: /stats и /my.\n"
            "• Сроки и статистика по городам — также на сайте vfsstats.by.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    # deep-link, а не callback: до первого сообщения пользователя бот не
                    # может сам писать в личку (исключение для заявок — разовое), а тап
                    # по ссылке отправляет /start от имени пользователя и открывает диалог
                    [InlineKeyboardButton(
                        text="📝 Заполнить анкету", url=f"https://t.me/{me.username}?start=go"
                    )],
                    [InlineKeyboardButton(
                        text="🌐 Статистика на сайте", url="https://vfsstats.by/"
                    )],
                    [InlineKeyboardButton(text="➡️ Перейти в группу", url=GROUP_LINK)],
                ]
            ),
        )
    except Exception:
        pass
    await callback.answer("Добро пожаловать! 🎉")
    log.info("капча пройдена, заявка одобрена: user=%s", user_id)


@router.callback_query(F.data == "go:report")
async def go_report(callback: CallbackQuery, state) -> None:
    """Кнопка «Заполнить анкету» (например, из /mine при отсутствии анкеты)."""
    from aiogram.exceptions import TelegramForbiddenError

    from src.report_flow import _entry_gate, ask_city

    await state.clear()
    try:
        if await _entry_gate(callback.message, state, user_id=callback.from_user.id):
            await callback.answer()
            return
        await ask_city(callback.message, state, greet=False)
        await callback.answer()
    except TelegramForbiddenError:
        # диалог с ботом ещё не открыт — попросим пользователя сделать первый шаг
        await callback.answer(
            "Отправьте боту команду /start — и анкета откроется.", show_alert=True
        )


@router.message(F.chat.id == CHAT_ID, F.pinned_message)
async def delete_pin_service_message(message: Message) -> None:
    """Удаляет сервисное «закреплено сообщение» от бота — оно только шумит в чате."""
    me = await message.bot.me()
    if message.from_user and message.from_user.id == me.id:
        try:
            await message.delete()
        except Exception:
            pass
