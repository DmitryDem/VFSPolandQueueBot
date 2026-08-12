"""Просмотр анкет через бота: /list — по городу/типу, /mine — своя, /near — люди рядом."""
from datetime import datetime, timedelta

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
    from src.report_flow import topic_id

    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"lvisa:{city}:{key}")]
        for key, label in VISA_TYPES.items()
        if topic_id(city, key)
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


# ---------- /queue: очередь города в порядке постановки ----------

QUEUE_PAGE = 15


def _queue_status(row) -> str:
    if row["outcome"]:
        return OUTCOME_LABELS[row["outcome"]].split()[0]  # ✅ / ❌
    if row["passport_date"]:
        return "🛂"
    if row["submit_date"]:
        return "📄"
    if row["letter_date"]:
        return f"✉️ {fmt(row['letter_date'])}"
    return "⏳"


def _fmt_queue_row(row, pos: int) -> str:
    suspect = "⚠️" if row["suspect"] else ""
    when = datetime.strptime(row["queue_date"], "%Y-%m-%d").strftime("%d.%m.%y")
    if row["queue_time"]:
        when += f" {row['queue_time']}"
    if row["message_id"]:
        when = f'<a href="{post_link(row["message_id"])}">{when}</a>'
    return f"{pos}. {suspect}{when} · {_queue_status(row)} · {user_label(row['username'], 'аноним')}"


def _queue_city_kb() -> InlineKeyboardMarkup:
    rows, row = [], []
    for city in CITIES:
        row.append(InlineKeyboardButton(text=city, callback_data=f"qcity:{city}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _queue_visa_kb(city: str) -> InlineKeyboardMarkup:
    from src.report_flow import topic_id

    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"qvisa:{city}:{key}")]
        for key, label in VISA_TYPES.items()
        if topic_id(city, key)
    ]
    rows.append([InlineKeyboardButton(text="🔙 Другой город", callback_data="qback")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_queue(message: Message, city: str, visa: str, offset: int, edit: bool) -> None:
    rows = db.reports_by_city_visa(city, visa, offset, QUEUE_PAGE)
    total = db.count_reports(city, visa)
    label = VISA_TYPES[visa]
    if total == 0:
        text = f"📜 <b>{city} — {label}</b>\nОчередь по постановке\n\nАнкет пока нет."
    else:
        lines = [f"📜 <b>{city} — {label}</b> · очередь по постановке · анкет: {total}", ""]
        lines += [_fmt_queue_row(r, offset + i + 1) for i, r in enumerate(rows)]
        lines.append("")
        lines.append("<i>№ по дате постановки · статус (✉️ письмо, 📄 подача, "
                     "🛂 паспорт, ✅/❌ результат, ⏳ ждёт); дата — ссылка на публикацию</i>")
        text = "\n".join(lines)

    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton(
            text="◀️ Назад", callback_data=f"qpage:{city}:{visa}:{max(0, offset - QUEUE_PAGE)}"))
    if offset + QUEUE_PAGE < total:
        nav.append(InlineKeyboardButton(
            text=f"▶️ Ещё ({total - offset - QUEUE_PAGE})",
            callback_data=f"qpage:{city}:{visa}:{offset + QUEUE_PAGE}"))
    buttons = ([nav] if nav else []) + [
        [InlineKeyboardButton(text="🔙 Другой тип", callback_data=f"qcity:{city}"),
         InlineKeyboardButton(text="🏙 Другой город", callback_data="qback")]
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if edit:
        await message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    else:
        await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


def _resolve_city(arg: str | None) -> str | None:
    if not arg:
        return None
    arg = arg.strip().lower()
    return next((c for c in CITIES if c.lower() == arg), None)


async def _ask_queue_visa(message: Message, city: str, edit: bool) -> None:
    text = f"Город: <b>{city}</b>\n\nКакой тип визы показать (очередь по постановке)?"
    if edit:
        await message.edit_text(text, reply_markup=_queue_visa_kb(city))
    else:
        await message.answer(text, reply_markup=_queue_visa_kb(city))


@router.message(Command("queue"), F.chat.type == "private")
async def cmd_queue(message: Message, command: CommandObject) -> None:
    city = _resolve_city(command.args)
    if city:
        await _ask_queue_visa(message, city, edit=False)
    else:
        hint = "Не узнал город. " if command.args else ""
        await message.answer(
            f"{hint}Очередь какого города показать (по порядку постановки)?",
            reply_markup=_queue_city_kb(),
        )


@router.callback_query(F.data == "qback")
async def queue_back(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Очередь какого города показать (по порядку постановки)?",
        reply_markup=_queue_city_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("qcity:"))
async def queue_pick_city(callback: CallbackQuery) -> None:
    city = callback.data.split(":", 1)[1]
    if city not in CITIES:
        await callback.answer("Неизвестный город", show_alert=True)
        return
    await _ask_queue_visa(callback.message, city, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("qvisa:"))
async def queue_pick_visa(callback: CallbackQuery) -> None:
    _, city, visa = callback.data.split(":", 2)
    if city not in CITIES or visa not in VISA_TYPES:
        await callback.answer("Неизвестная комбинация", show_alert=True)
        return
    await _render_queue(callback.message, city, visa, 0, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("qpage:"))
async def queue_page(callback: CallbackQuery) -> None:
    _, city, visa, offset = callback.data.split(":", 3)
    await _render_queue(callback.message, city, visa, int(offset), edit=True)
    await callback.answer()


# ---------- /near: люди рядом ----------

NEAR_WINDOWS = (3, 7, 14)   # окно ±дней, расширяется, пока соседей мало
NEAR_MIN = 5                # сколько соседей считаем достаточным
NEAR_SHOW = 12              # максимум строк в выдаче


def _near_status(r) -> str:
    if r["outcome"]:
        return OUTCOME_LABELS[r["outcome"]].split()[0] + (
            " виза" if r["outcome"] == "APPROVED" else " отказ"
        )
    if r["passport_date"]:
        return f"🛂 паспорт {fmt(r['passport_date'])}"
    if r["submit_date"]:
        return f"📄 подал(а) {fmt(r['submit_date'])}"
    if r["letter_date"]:
        return f"✉️ письмо {fmt(r['letter_date'])}"
    return "⏳ ждёт"


def _pos_key(r) -> tuple:
    return (r["queue_date"], r["queue_time"] or "99")


async def _render_near(message: Message, own) -> None:
    qd = datetime.strptime(own["queue_date"], "%Y-%m-%d").date()
    rows, window = [], NEAR_WINDOWS[-1]
    for w in NEAR_WINDOWS:
        rows = db.reports_near(
            own["city"], own["visa_type"],
            (qd - timedelta(days=w)).isoformat(), (qd + timedelta(days=w)).isoformat(),
        )
        window = w
        if sum(1 for r in rows if r["id"] != own["id"]) >= NEAR_MIN:
            break

    # свою (вдруг сомнительную) анкету гарантированно включаем
    if not any(r["id"] == own["id"] for r in rows):
        rows = sorted(list(rows) + [own], key=_pos_key)

    # окно показа вокруг своей позиции
    idx = next(i for i, r in enumerate(rows) if r["id"] == own["id"])
    start = max(0, min(idx - NEAR_SHOW // 2, len(rows) - NEAR_SHOW))
    shown = rows[start:start + NEAR_SHOW]

    when_own = fmt(own["queue_date"]) + (f" в {own['queue_time']}" if own["queue_time"] else "")
    lines = [
        f"👥 <b>Люди рядом</b> — {own['city']}, {VISA_TYPES[own['visa_type']]}",
        f"ваша постановка: <b>{when_own}</b>, окно ±{window} дн.",
        "",
    ]
    for r in shown:
        when = datetime.strptime(r["queue_date"], "%Y-%m-%d").strftime("%d.%m")
        if r["queue_time"]:
            when += f" {r['queue_time']}"
        if r["message_id"]:
            when = f'<a href="{post_link(r["message_id"])}">{when}</a>'
        if r["id"] == own["id"]:
            lines.append(f"<b>▶ {when} ← вы ({_near_status(r)})</b>")
        else:
            lines.append(f"{when} → {_near_status(r)}")
    if len(rows) > len(shown):
        lines.append(f"<i>…показаны {len(shown)} из {len(rows)} ближайших</i>")

    others = [r for r in rows if r["id"] != own["id"]]
    with_letter = [r for r in others if r["letter_date"]]
    lines.append("")
    if others:
        summary = f"Из {len(others)} соседей письмо у <b>{len(with_letter)}</b>"
        if with_letter:
            waits = sorted(
                (datetime.strptime(r["letter_date"], "%Y-%m-%d")
                 - datetime.strptime(r["queue_date"], "%Y-%m-%d")).days
                for r in with_letter
            )
            rng = f"{waits[0]}" if waits[0] == waits[-1] else f"{waits[0]}–{waits[-1]}"
            summary += f" (ожидание у них: {rng} дн.)"
        lines.append(summary)
        earlier_waiting = sum(
            1 for r in others if _pos_key(r) < _pos_key(own) and not r["letter_date"]
        )
        if earlier_waiting and not own["letter_date"]:
            lines.append(
                f"⚠️ <i>{earlier_waiting} вставших раньше вас без письма — возможно, "
                "они просто не обновили анкету.</i>"
            )
    else:
        lines.append("Соседей по датам пока нет — вы первопроходец в этом окне.")
    await message.answer("\n".join(lines), disable_web_page_preview=True)


def _near_choice_kb(rows) -> InlineKeyboardMarkup:
    kb = []
    for r in rows:
        lbl = f"{r['label']} · " if r["label"] else ""
        kb.append([InlineKeyboardButton(
            text=f"{lbl}{r['city']}, {VISA_TYPES[r['visa_type']].split('(')[0].strip()}",
            callback_data=f"nearr:{r['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=kb)


async def _near_entry(message: Message, user_id: int) -> None:
    from src.report_flow import MULTI_REPORTS

    rows = db.reports_by_user(user_id) if MULTI_REPORTS else (
        [db.find_latest(user_id)] if db.find_latest(user_id) else []
    )
    rows = [r for r in rows if r]
    if not rows:
        await message.answer(
            "«Люди рядом» работает от вашей анкеты, а её пока нет. Заполните — займёт минуту.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Заполнить анкету", callback_data="go:report")]
            ]),
        )
        return
    if len(rows) == 1:
        await _render_near(message, rows[0])
        return
    await message.answer(
        "У вас несколько анкет. Для какой показать людей рядом?",
        reply_markup=_near_choice_kb(rows),
    )


@router.message(Command("near"), F.chat.type == "private")
async def cmd_near(message: Message) -> None:
    await _near_entry(message, message.from_user.id)


@router.callback_query(F.data == "near")
async def near_button(callback: CallbackQuery) -> None:
    await _near_entry(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("nearr:"))
async def near_report_pick(callback: CallbackQuery) -> None:
    rid = int(callback.data.split(":", 1)[1])
    row = db.get_report(rid)
    if row is None or row["user_id"] != callback.from_user.id:
        await callback.answer("Анкета не найдена", show_alert=True)
        return
    await _render_near(callback.message, row)
    await callback.answer()


# ---------- /mine ----------

@router.message(Command("mine"), F.chat.type == "private")
async def cmd_mine(message: Message) -> None:
    await _show_mine(message, message.from_user.id)


@router.message(CommandStart(deep_link=True, magic=F.args == "menu_mine"))
async def mine_deeplink(message: Message, command: CommandObject, state: FSMContext) -> None:
    await state.clear()
    await _show_mine(message, message.from_user.id)


def _mine_list_kb(rows) -> InlineKeyboardMarkup:
    from src.report_flow import MAX_REPORTS

    kb = []
    for r in rows:
        lbl = f"{r['label']} · " if r["label"] else ""
        kb.append([InlineKeyboardButton(
            text=f"{lbl}{r['city']}, {VISA_TYPES[r['visa_type']].split('(')[0].strip()}",
            callback_data=f"mineview:{r['id']}",
        )])
    if len(rows) < MAX_REPORTS:
        kb.append([InlineKeyboardButton(text="➕ Добавить ещё анкету", callback_data="add:new")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


async def _show_mine(message: Message, user_id: int, edit: bool = False) -> None:
    from src.report_flow import MULTI_REPORTS

    if MULTI_REPORTS:
        rows = db.reports_by_user(user_id)
        if len(rows) > 1:
            lines = [f"👤 <b>Ваши анкеты ({len(rows)})</b>", ""]
            for r in rows:
                lbl = f"{r['label']} · " if r["label"] else ""
                st = "⏳ ждёт" if not r["letter_date"] else f"✉️ {fmt(r['letter_date'])}"
                lines.append(f"• {lbl}{r['city']}, {VISA_TYPES[r['visa_type']]} — {st}")
            lines.append("")
            lines.append("Выберите анкету:")
            fn = message.edit_text if edit else message.answer
            await fn("\n".join(lines), reply_markup=_mine_list_kb(rows))
            return

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
    await _report_detail(message, row, edit)


async def _report_detail(message: Message, row, edit: bool = False) -> None:
    """Карточка одной анкеты с действиями (в т.ч. удаление)."""
    when = fmt(row["queue_date"]) + (f" в {row['queue_time']}" if row["queue_time"] else "")
    created = datetime.fromisoformat(row["created_at"]).strftime("%d.%m.%Y")
    slots = None
    if row["slots"]:
        import json as _json

        slots = _json.loads(row["slots"])
    label_line = f"👥 Заявитель: <b>{row['label']}</b>\n" if row["label"] else ""
    lines = [
        f"👤 <b>Анкета</b> (от {created})",
        "",
        f"{label_line}🏙 {row['city']} · 📄 {VISA_TYPES[row['visa_type']]}",
        f"⏳ В очереди: <b>{when}</b>",
        *([f"🔢 Номер очереди: <b>PLB {row['queue_num']}…</b>"] if row["queue_num"] else []),
        f"📬 Письмо: <b>{fmt(row['letter_date']) if row['letter_date'] else 'ещё не пришло'}</b>",
        f"📆 Даты записи: <b>{fmt_slots(slots)}</b>",
        f"📄 Подача: <b>{fmt(row['submit_date'])}</b>",
        f"🛂 Паспорт: <b>{fmt(row['passport_date'])}</b>",
        f"Результат: <b>{OUTCOME_LABELS.get(row['outcome'], '—')}</b>",
        f"🎫 Срок визы: <b>{fmt_duration(row['visa_days'])}</b>",
    ]
    rid = row["id"]
    buttons = [
        [InlineKeyboardButton(text="✏️ Дополнить / исправить", callback_data=f"pick:{rid}")],
        [InlineKeyboardButton(text="🗑 Удалить анкету", callback_data=f"del:{rid}")],
        [InlineKeyboardButton(text="👥 Люди рядом", callback_data=f"nearr:{rid}"),
         InlineKeyboardButton(text=f"📄 Анкеты: {row['city']}",
                              callback_data=f"lvisa:{row['city']}:{row['visa_type']}")],
    ]
    if row["message_id"]:
        buttons.insert(0, [InlineKeyboardButton(
            text="👀 Открыть публикацию", url=post_link(row["message_id"]))])
    fn = message.edit_text if edit else message.answer
    await fn("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("mineview:"))
async def mine_view(callback: CallbackQuery) -> None:
    rid = int(callback.data.split(":", 1)[1])
    row = db.get_report(rid)
    if row is None or row["user_id"] != callback.from_user.id:
        await callback.answer("Анкета не найдена", show_alert=True)
        return
    await _report_detail(callback.message, row, edit=True)
    await callback.answer()


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


# ---------- удаление своей анкеты ----------

@router.callback_query(F.data.startswith("del:"))
async def del_confirm(callback: CallbackQuery) -> None:
    rid = int(callback.data.split(":", 1)[1])
    row = db.get_report(rid)
    if row is None or row["user_id"] != callback.from_user.id:
        await callback.answer("Анкета не найдена", show_alert=True)
        return
    lbl = f"«{row['label']}» " if row["label"] else ""
    await callback.message.edit_text(
        f"🗑 Удалить анкету {lbl}({row['city']}, {VISA_TYPES[row['visa_type']]})?\n"
        "Запись и её публикация в теме будут удалены безвозвратно.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delok:{rid}")],
            [InlineKeyboardButton(text="↩️ Отмена", callback_data=f"mineview:{rid}")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delok:"))
async def del_do(callback: CallbackQuery) -> None:
    from src import stats
    from src.report_flow import CHAT_ID

    rid = int(callback.data.split(":", 1)[1])
    row = db.get_report(rid)
    if row is None or row["user_id"] != callback.from_user.id:
        await callback.answer("Анкета не найдена", show_alert=True)
        return
    if row["message_id"]:
        try:
            await callback.bot.delete_message(CHAT_ID, row["message_id"])
        except Exception:
            pass
    db.delete_report(rid)
    stats.note_write(row["city"], row["visa_type"])
    await callback.message.edit_text(
        "🗑 Анкета удалена. Освободился слот — при желании можно подать новую: /report"
    )
    await callback.answer("Удалено")
