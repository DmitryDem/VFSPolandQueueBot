"""Админ-инструменты (личка администратора).

/stale — найти «мёртвые» анкеты: без письма, позади фронта своего города×визы, автор вышел
из чата. На каждую — карточка с кнопками «Удалить» / «Оставить». Удаление повторяет ручной
флоу зачисток: пост в теме удаляется (или, если старше 48 ч, заменяется заглушкой без кнопок),
запись в ленте приглашений снимается, строка удаляется из БД, кеш статистики сбрасывается.
"""
import asyncio
import logging
from datetime import date, datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src import db, stats
from src.report_flow import CHAT_ID, VISA_TYPES, _admin_id, _retire_invite, fmt, post_link, user_label

log = logging.getLogger("admin")
router = Router()
router.message.filter(F.chat.type == "private")

TOMBSTONE = "⚠️ Анкета неактуальна — удалена."


def _is_admin(user_id: int) -> bool:
    admin = _admin_id()
    return bool(admin) and user_id == admin


def _d(iso: str) -> date:
    return datetime.strptime(iso[:10], "%Y-%m-%d").date()


def _card(r, today: date) -> tuple[str, InlineKeyboardMarkup]:
    q, f = _d(r["queue_date"]), _d(r["front"])
    when = fmt(r["queue_date"]) + (f" в {r['queue_time']}" if r["queue_time"] else "")
    text = (
        f"🏙 {r['city']} · {VISA_TYPES.get(r['visa_type'], r['visa_type'])}\n"
        f"👤 {user_label(r['username'], 'без ника')} (id {r['user_id']}) · анкета #{r['id']}\n"
        f"⏳ Постановка {when} · PLB {r['queue_num'] or '—'}\n"
        f"📍 Фронт {fmt(r['front'])} → отстал на <b>{(f - q).days} дн.</b> · ждёт {(today - q).days} дн.\n"
        "❌ Автор вышел из чата"
    )
    rows = [[
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"stale:del:{r['id']}"),
        InlineKeyboardButton(text="✔️ Оставить", callback_data=f"stale:skip:{r['id']}"),
    ]]
    if r["message_id"]:
        rows.append([InlineKeyboardButton(text="👀 Пост анкеты", url=post_link(r["message_id"]))])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("stale"))
async def cmd_stale(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    rows = db.pending_behind_front()
    if not rows:
        await message.answer("Позади фронта без письма никого нет.")
        return
    status = await message.answer(
        f"Позади фронта без письма: <b>{len(rows)}</b>. Проверяю, кто вышел из чата…"
    )
    left = []
    for r in rows:
        try:
            member = await message.bot.get_chat_member(CHAT_ID, r["user_id"])
            st = member.status
        except TelegramBadRequest:
            st = "unknown"
        if st in ("left", "kicked"):
            left.append(r)
        await asyncio.sleep(0.1)
    if not left:
        await status.edit_text(
            f"Позади фронта {len(rows)} анкет, но все авторы в чате — удалять нечего."
        )
        return
    await status.edit_text(
        f"Позади фронта <b>{len(rows)}</b> анкет; авторы вышли из чата — <b>{len(left)}</b>. "
        "Карточки ниже, решение по каждой 👇"
    )
    today = date.today()
    for r in sorted(left, key=lambda x: (_d(x["queue_date"]) - _d(x["front"])).days):
        text, kb = _card(r, today)
        await message.answer(text, reply_markup=kb)
        await asyncio.sleep(0.15)


@router.callback_query(F.data.startswith("stale:"))
async def stale_action(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Кнопка только для администратора.", show_alert=True)
        return
    _, action, rid = callback.data.split(":", 2)
    rid = int(rid)
    base = callback.message.html_text
    if action == "skip":
        await callback.message.edit_text(base + "\n\n<b>Решение:</b> ✔️ оставлена")
        await callback.answer()
        return
    row = db.get_report(rid)
    if row is None:
        await callback.message.edit_text(base + "\n\n<i>анкета уже удалена</i>")
        await callback.answer()
        return
    if row["letter_date"]:
        await callback.message.edit_text(base + "\n\n<b>⛔ У анкеты появилось письмо — не удаляю.</b>")
        await callback.answer()
        return
    how = "поста не было"
    if row["message_id"]:
        try:
            await callback.bot.delete_message(CHAT_ID, row["message_id"])
            how = "пост удалён"
        except TelegramBadRequest:
            try:  # старше 48 ч — Telegram не даёт удалить, ставим заглушку без кнопок
                await callback.bot.edit_message_text(
                    chat_id=CHAT_ID, message_id=row["message_id"], text=TOMBSTONE,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[]),
                )
                how = "пост заменён заглушкой"
            except TelegramBadRequest as e:
                how = f"пост не изменён ({e.message})"
    await _retire_invite(callback.bot, row)
    db.delete_report(rid)
    stats.note_write(row["city"], row["visa_type"])
    log.info("admin /stale: удалена анкета %s (%s/%s), %s", rid, row["city"], row["visa_type"], how)
    await callback.message.edit_text(base + f"\n\n<b>Решение:</b> 🗑 удалена ({how})")
    await callback.answer("Удалено")
