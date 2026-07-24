"""Просмотр анкет через бота: /list — по городу и типу визы, /mine — своя анкета."""
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src import db
from src.report_flow import (
    CITIES,
    OUTCOME_LABELS,
    VISA_TYPES,
    fmt,
    fmt_duration,
    fmt_slots,
    post_link,
    user_label,
)

router = Router()
PAGE_SIZE = 10


def _city_kb() -> InlineKeyboardMarkup:
    rows, row = [], []
    for city in CITIES:
        row.append(InlineKeyboardButton(text=city, callback_data=f"lcity:{city}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _visa_kb(city: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"lvisa:{city}:{key}")]
        for key, label in VISA_TYPES.items()
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="lback")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _fmt_row(row) -> str:
    """Одна строка списка: даты + автор, дата постановки — ссылка на публикацию."""
    suspect = "⚠️ " if row["suspect"] else ""
    when = suspect + fmt(row["queue_date"])
    if row["message_id"]:
        when = f'<a href="{post_link(row["message_id"])}">{when}</a>'
    if row["outcome"]:
        status = OUTCOME_LABELS[row["outcome"]].split()[0]  # ✅ / ❌
    elif row["passport_date"]:
        status = "🛂"
    elif row["submit_date"]:
        status = "📄"
    elif row["letter_date"]:
        status = f"✉️ {fmt(row['letter_date'])}"
    else:
        status = "⏳ ждёт"
    return f"{when} → {status} · {user_label(row['username'], 'аноним')}"


async def _render_list(message: Message, city: str, visa: str, offset: int, edit: bool) -> None:
    rows = db.reports_page(city, visa, offset, PAGE_SIZE)
    total = db.count_reports(city, visa)
    label = VISA_TYPES[visa]
    if total == 0:
        text = (
            f"📄 <b>{city} — {label}</b>\n\nАнкет пока нет. "
            "Станьте первым — кнопка ниже!"
        )
    else:
        lines = [f"📄 <b>{city} — {label}</b> · анкет: {total}", ""]
        lines += [_fmt_row(r) for r in rows]
        lines.append("")
        lines.append("<i>постановка → статус (✉️ письмо, 📄 подача, 🛂 паспорт, ✅/❌ результат);"
                     " дата — ссылка на публикацию</i>")
        text = "\n".join(lines)

    buttons = []
    if offset + PAGE_SIZE < total:
        buttons.append([InlineKeyboardButton(
            text=f"▶️ Ещё ({total - offset - PAGE_SIZE})",
            callback_data=f"lpage:{city}:{visa}:{offset + PAGE_SIZE}",
        )])
    buttons.append([
        InlineKeyboardButton(text="📊 Статистика", callback_data=f"svisa:{city}:{visa}"),
        InlineKeyboardButton(text="🔙 Другой город", callback_data="lback"),
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if edit:
        await message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    else:
        await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


# ---------- /list ----------

@router.message(Command("list"), F.chat.type == "private")
async def cmd_list(message: Message) -> None:
    await message.answer("Анкеты какого города показать?", reply_markup=_city_kb())


@router.message(CommandStart(deep_link=True, magic=F.args == "menu_list"))
async def list_deeplink(message: Message, command: CommandObject, state: FSMContext) -> None:
    await state.clear()
    await cmd_list(message)


@router.callback_query(F.data == "lback")
async def list_back(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Анкеты какого города показать?", reply_markup=_city_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("lcity:"))
async def list_pick_city(callback: CallbackQuery) -> None:
    city = callback.data.split(":", 1)[1]
    if city not in CITIES:
        await callback.answer("Неизвестный город", show_alert=True)
        return
    await callback.message.edit_text(
        f"Город: <b>{city}</b>\n\nКакой тип визы?", reply_markup=_visa_kb(city)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lvisa:"))
async def list_pick_visa(callback: CallbackQuery) -> None:
    _, city, visa = callback.data.split(":", 2)
    if city not in CITIES or visa not in VISA_TYPES:
        await callback.answer("Неизвестная комбинация", show_alert=True)
        return
    await _render_list(callback.message, city, visa, 0, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("lpage:"))
async def list_page(callback: CallbackQuery) -> None:
    _, city, visa, offset = callback.data.split(":", 3)
    await _render_list(callback.message, city, visa, int(offset), edit=True)
    await callback.answer()


# ---------- /mine ----------

@router.message(Command("mine"), F.chat.type == "private")
async def cmd_mine(message: Message) -> None:
    await _show_mine(message, message.from_user.id)


@router.message(CommandStart(deep_link=True, magic=F.args == "menu_mine"))
async def mine_deeplink(message: Message, command: CommandObject, state: FSMContext) -> None:
    await state.clear()
    await _show_mine(message, message.from_user.id)


async def _show_mine(message: Message, user_id: int) -> None:
    row = db.find_latest(user_id)
    if row is None:
        await message.answer(
            "У вас пока нет анкеты. Заполните — это займёт минуту, а прогнозы группы "
            "станут точнее.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Заполнить анкету", callback_data="go:report")]
            ]),
        )
        return
    when = fmt(row["queue_date"]) + (f" в {row['queue_time']}" if row["queue_time"] else "")
    created = datetime.fromisoformat(row["created_at"]).strftime("%d.%m.%Y")
    slots = None
    if row["slots"]:
        import json as _json

        slots = _json.loads(row["slots"])
    lines = [
        f"👤 <b>Ваша анкета</b> (от {created})",
        "",
        f"🏙 {row['city']} · 📄 {VISA_TYPES[row['visa_type']]}",
        f"⏳ В очереди: <b>{when}</b>",
        f"📬 Письмо: <b>{fmt(row['letter_date']) if row['letter_date'] else 'ещё не пришло'}</b>",
        f"📆 Даты записи: <b>{fmt_slots(slots)}</b>",
        f"📄 Подача: <b>{fmt(row['submit_date'])}</b>",
        f"🛂 Паспорт: <b>{fmt(row['passport_date'])}</b>",
        f"Результат: <b>{OUTCOME_LABELS.get(row['outcome'], '—')}</b>",
        f"🎫 Срок визы: <b>{fmt_duration(row['visa_days'])}</b>",
    ]
    buttons = []
    if row["message_id"]:
        buttons.append([InlineKeyboardButton(
            text="👀 Открыть публикацию", url=post_link(row["message_id"])
        )])
    buttons.append([InlineKeyboardButton(text="✏️ Дополнить / исправить", callback_data="mine:edit")])
    buttons.append([InlineKeyboardButton(
        text=f"📄 Анкеты: {row['city']}", callback_data=f"lvisa:{row['city']}:{row['visa_type']}"
    )])
    await message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data == "mine:edit")
async def mine_edit(callback: CallbackQuery, state: FSMContext) -> None:
    from src.report_flow import edit_start

    row = db.find_latest(callback.from_user.id)
    if row is None:
        await callback.answer("Анкеты нет — заполните новую: /report", show_alert=True)
        return
    await state.clear()
    await state.update_data(editing_id=row["id"])
    await edit_start(callback, state)
