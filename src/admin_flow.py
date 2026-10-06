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
from aiogram.filters import Command, CommandObject, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src import db, stats
from src.report_flow import (CHAT_ID, VISA_TYPES, _retire_invite, _update_invite, admin_ids, build_post_text_from_row,
                             fmt, post_kb, post_link, row_author, row_to_data, user_label)

log = logging.getLogger("admin")
router = Router()
router.message.filter(F.chat.type == "private")

TOMBSTONE = "⚠️ Анкета неактуальна — удалена."


def _is_admin(user_id: int) -> bool:
    return user_id in admin_ids()


def _d(iso: str) -> date:
    return datetime.strptime(iso[:10], "%Y-%m-%d").date()


ONLINE_WORDS = ("online", "онлайн", "chat", "чат", "в", "вчате", "here")
MONTH_DAYS = 30


def _parse_stale_args(args: str | None) -> tuple[bool, int]:
    """(online, months): `/stale` → (False, 0); `/stale online` → (True, 1); `/stale online 2` → (True, 2);
    `/stale 2` → (False, 2) — вышедшие, отставшие ≥ 2 мес."""
    online, months = False, 0
    for tok in (args or "").lower().replace(",", " ").split():
        if tok in ONLINE_WORDS:
            online = True
        elif tok.isdigit():
            months = int(tok)
    if online and months == 0:
        months = 1
    return online, months


def _card(r, today: date, in_chat: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    q, f = _d(r["queue_date"]), _d(r["front"])
    when = fmt(r["queue_date"]) + (f" в {r['queue_time']}" if r["queue_time"] else "")
    text = (
        f"🏙 {r['city']} · {VISA_TYPES.get(r['visa_type'], r['visa_type'])}\n"
        f"👤 {user_label(r['username'], 'без ника')} (id {r['user_id']}) · анкета #{r['id']}\n"
        f"⏳ Постановка {when} · PLB {r['queue_num'] or '—'}\n"
        f"📍 Фронт {fmt(r['front'])} → отстал на <b>{(f - q).days} дн.</b> · ждёт {(today - q).days} дн.\n"
        + ("✅ Автор в чате" if in_chat else "❌ Автор вышел из чата")
    )
    rows = [[
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"stale:del:{r['id']}"),
        InlineKeyboardButton(text="✔️ Оставить", callback_data=f"stale:skip:{r['id']}"),
    ]]
    if r["message_id"]:
        rows.append([InlineKeyboardButton(text="👀 Пост анкеты", url=post_link(r["message_id"]))])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("stale"))
async def cmd_stale(message: Message, command: CommandObject) -> None:
    """/stale — позади фронта + автор вышел из чата (как раньше).
    /stale online [N] — позади фронта на ≥ N месяцев (по умолчанию 1) + автор ЕЩЁ В ЧАТЕ.
    /stale N — вышедшие, отставшие на ≥ N месяцев."""
    if not _is_admin(message.from_user.id):
        return
    online, months = _parse_stale_args(command.args)
    min_lag = months * MONTH_DAYS
    rows = db.pending_behind_front()
    if min_lag:
        rows = [r for r in rows if (_d(r["front"]) - _d(r["queue_date"])).days >= min_lag]
    who = "автор в чате" if online else "автор вышел из чата"
    lag_txt = f" на ≥ {months} мес." if months else ""
    if not rows:
        await message.answer(f"Позади фронта{lag_txt} без письма никого нет.")
        return
    status = await message.answer(
        f"Позади фронта{lag_txt} без письма: <b>{len(rows)}</b>. Проверяю членство в чате…"
    )
    picked = []
    for r in rows:
        try:
            member = await message.bot.get_chat_member(CHAT_ID, r["user_id"])
            st = member.status
        except TelegramBadRequest:
            st = "unknown"
        is_left = st in ("left", "kicked")
        keep = (not is_left and st != "unknown") if online else is_left
        if keep:
            picked.append(r)
        await asyncio.sleep(0.1)
    if not picked:
        await status.edit_text(
            f"Позади фронта{lag_txt} {len(rows)} анкет, но с условием «{who}» — ни одной."
        )
        return
    await status.edit_text(
        f"Позади фронта{lag_txt} <b>{len(rows)}</b> анкет; {who} — <b>{len(picked)}</b>. "
        "Карточки ниже, решение по каждой 👇"
    )
    today = date.today()
    for r in sorted(picked, key=lambda x: (_d(x["queue_date"]) - _d(x["front"])).days):
        text, kb = _card(r, today, in_chat=online)
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
    how = await _delete_anketa(callback.bot, row, "stale")
    await callback.message.edit_text(base + f"\n\n<b>Решение:</b> 🗑 удалена ({how})")
    await callback.answer("Удалено")


async def _delete_anketa(bot, row, source: str) -> str:
    """Удаление анкеты админом: пост в теме (delete или заглушка, если старше 48 ч),
    запись в ленте приглашений, строка БД, кеш статистики. Возвращает, что стало с постом."""
    how = "поста не было"
    if row["message_id"]:
        try:
            await bot.delete_message(CHAT_ID, row["message_id"])
            how = "пост удалён"
        except TelegramBadRequest:
            try:  # старше 48 ч — Telegram не даёт удалить, ставим заглушку без кнопок
                await bot.edit_message_text(
                    chat_id=CHAT_ID, message_id=row["message_id"], text=TOMBSTONE,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[]),
                )
                how = "пост заменён заглушкой"
            except TelegramBadRequest as e:
                how = f"пост не изменён ({e.message})"
    await _retire_invite(bot, row)
    db.delete_report(row["id"])
    stats.note_write(row["city"], row["visa_type"])
    log.info("admin /%s: удалена анкета %s (%s/%s), %s", source, row["id"], row["city"], row["visa_type"], how)
    return how


# ---------- /who: кто автор анкеты (в т.ч. анонимной) ----------

def _who_card(r) -> str:
    """Карточка анкеты для админа: реальный ник и id всегда, плюс как она подписана публично."""
    when = fmt(r["queue_date"]) + (f" в {r['queue_time']}" if r["queue_time"] else "")
    letter = fmt(r["letter_date"]) if r["letter_date"] else "ещё нет"
    flags = []
    if r["anon"]:
        flags.append("🙈 ник скрыт")
    if r["suspect"]:
        flags.append("⚠️ сомнительная: " + SUSPECT_LABELS.get(r["suspect_reason"] or "short", "иное"))
    created = r["created_at"][:10]
    lines = [
        f"<b>Анкета #{r['id']}</b> · {r['city']} · {VISA_TYPES.get(r['visa_type'], r['visa_type'])}",
        f"👤 Автор: <b>{user_label(r['username'], 'без ника')}</b> · id <code>{r['user_id']}</code>",
        f"🏷 Публичная подпись: {row_author(r)}" + (f" · {', '.join(flags)}" if flags else ""),
        f"⏳ Постановка {when} · PLB {r['queue_num'] or '—'} · 📬 письмо: {letter}",
        f"🗓 создана {created}" + (f", правка {r['updated_at'][:10]}" if r["updated_at"] else ""),
    ]
    if r["message_id"]:
        lines.append(f'<a href="{post_link(r["message_id"])}">👀 пост анкеты</a>')
    return "\n".join(lines)


SUSPECT_LABELS = {"jump": "мимо очереди", "short": "короткий срок", "admin": "иное (админ)"}


def _who_kb(r) -> InlineKeyboardMarkup:
    """Пометить сомнительной с причиной / снять пометку — в любой момент из карточки /who."""
    rid = r["id"]
    if r["suspect"]:
        rows = [[InlineKeyboardButton(text="✅ Снять пометку «сомнительная»", callback_data=f"whos:{rid}:clear")]]
    else:
        rows = [
            [InlineKeyboardButton(text="⚠️ Сомнительная: мимо очереди", callback_data=f"whos:{rid}:jump")],
            [InlineKeyboardButton(text="⚠️ Сомнительная: короткий срок", callback_data=f"whos:{rid}:short")],
            [InlineKeyboardButton(text="⚠️ Сомнительная: иное", callback_data=f"whos:{rid}:admin")],
        ]
    rows.append([InlineKeyboardButton(text="🗑 Удалить анкету", callback_data=f"whodel:{rid}:ask")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("whodel:"))
async def who_delete(callback: CallbackQuery) -> None:
    """Удаление из карточки /who: сначала подтверждение, затем тот же флоу, что в /stale."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Кнопка только для администратора.", show_alert=True)
        return
    _, rid, step = callback.data.split(":", 2)
    rid = int(rid)
    row = db.get_report(rid)
    if row is None:
        await callback.message.edit_text(_strip_tail(callback.message.html_text) + "\n\n<i>анкета уже удалена</i>")
        await callback.answer()
        return
    card = _who_card(row)
    if step == "ask":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить безвозвратно", callback_data=f"whodel:{rid}:yes")],
            [InlineKeyboardButton(text="↩️ Отмена", callback_data=f"whodel:{rid}:no")],
        ])
        letter = " У анкеты есть письмо — оно уйдёт из статистики." if row["letter_date"] else ""
        await callback.message.edit_text(
            card + f"\n\n<b>Удалить анкету #{rid}?</b> Пост в теме и запись в ленте тоже будут убраны.{letter}",
            reply_markup=kb, disable_web_page_preview=True,
        )
    elif step == "no":
        await callback.message.edit_text(card, reply_markup=_who_kb(row), disable_web_page_preview=True)
    else:
        how = await _delete_anketa(callback.bot, row, "who")
        await callback.message.edit_text(card + f"\n\n<b>🗑 Удалена</b> · {how}", disable_web_page_preview=True)
    await callback.answer()


def _strip_tail(html: str) -> str:
    """Карточка без приписок-решений (всё после пустой строки-разделителя)."""
    return html.split("\n\n")[0]


async def _redraw_public(bot, row) -> str:
    """Перерисовать пост анкеты в теме и запись в ленте приглашений по текущей строке БД."""
    how = "поста нет"
    if row["message_id"]:
        text, city, visa = build_post_text_from_row(row)
        me = await bot.me()
        try:
            await bot.edit_message_text(chat_id=CHAT_ID, message_id=row["message_id"], text=text,
                                        reply_markup=post_kb(me.username, city, visa))
            how = "пост обновлён"
        except TelegramBadRequest as e:
            how = "пост без изменений" if "not modified" in e.message else f"пост не изменён ({e.message})"
    if row["invite_msg_id"] and row["letter_date"]:
        await _update_invite(bot, row["invite_msg_id"], row_to_data(row), row["username"], "без ника",
                             row["message_id"])
        how += ", лента обновлена"
    return how


@router.callback_query(F.data.startswith("whos:"))
async def who_suspect(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Кнопка только для администратора.", show_alert=True)
        return
    _, rid, action = callback.data.split(":", 2)
    rid = int(rid)
    row = db.get_report(rid)
    if row is None:
        await callback.message.edit_text(callback.message.html_text + "\n\n<i>анкета уже удалена</i>")
        await callback.answer()
        return
    if action == "clear":
        db.set_suspect(rid, 0)
        verdict = "✅ пометка снята"
    else:
        db.set_suspect(rid, 1, action)
        verdict = f"⚠️ помечена: {SUSPECT_LABELS.get(action, action)}"
    row = db.get_report(rid)
    how = await _redraw_public(callback.bot, row)
    stats.note_write(row["city"], row["visa_type"])
    log.info("admin /who: анкета %s — %s (%s)", rid, verdict, how)
    await callback.message.edit_text(_who_card(row) + f"\n\n<b>{verdict}</b> · {how}",
                                     reply_markup=_who_kb(row), disable_web_page_preview=True)
    await callback.answer("Готово")


@router.message(Command("who"))
async def cmd_who(message: Message, command: CommandObject) -> None:
    """Админ: /who 1497 — автор анкеты по номеру; /who @nick — все анкеты пользователя."""
    if not _is_admin(message.from_user.id):
        return
    arg = (command.args or "").strip()
    if not arg:
        await message.answer("Использование: <code>/who 1497</code> (номер анкеты) или <code>/who @nick</code>")
        return
    if arg.lstrip("#").isdigit():
        row = db.get_report(int(arg.lstrip("#")))
        if row is None:
            await message.answer(f"Анкеты #{arg.lstrip('#')} нет (удалена?).")
            return
        rows = [row]
    else:
        rows = db.reports_by_username(arg)
        if not rows:
            await message.answer(f"Анкет с ником {arg} не нашёл. Ник хранится на момент последней правки анкеты.")
            return
    for r in rows[:10]:
        await message.answer(_who_card(r), reply_markup=_who_kb(r), disable_web_page_preview=True)
    if len(rows) > 10:
        await message.answer(f"…и ещё {len(rows) - 10}.")
