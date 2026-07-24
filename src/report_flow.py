"""Диалог-анкета сбора статистики очереди VFS (aiogram FSM) с публикацией в темы группы."""
import json
import logging
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src import db, stats

router = Router()
router.message.filter(F.chat.type == "private")

TOPICS = json.loads(
    (Path(__file__).resolve().parent.parent / "config" / "topics.json").read_text("utf-8")
)
CHAT_ID = TOPICS["chat_id"]
CITIES = list(TOPICS["cities"].keys())

VISA_TYPES = {
    "D_OTHER": "Национальная D (Other)",
    "D_DRIVER": "Национальная D (Driver)",
    "D_WORK": "Национальная D (Work)",
    "D_KARTA": "Национальная D (Карта поляка)",
    "C_OTHER": "Шенген C (Other)",
}

# необязательное уточнение категории для D (Other)
SUBCATS = {"KARTA": "Карта поляка", "STUDY": "Ученическая"}

REPORT_COOLDOWN_DAYS = 14

DATE_RE = re.compile(r"^\s*(\d{1,2})[.](\d{1,2})[.](\d{4})\s*$")
PERIOD_RE = re.compile(
    r"^\s*(\d{1,2}[.]\d{1,2}[.]\d{4})\s*[-–—]\s*(\d{1,2}[.]\d{1,2}[.]\d{4})\s*$"
)

# приватная супергруппа: -100XXXXXXXXXX -> t.me/c/XXXXXXXXXX/...
CHAT_LINK_ID = str(CHAT_ID).removeprefix("-100")

BACK = "⬅️ Назад"


class Report(StatesGroup):
    city = State()
    visa_type = State()
    subcategory = State()
    queue_date = State()
    queue_time = State()
    letter_date = State()
    slots = State()
    submit_date = State()
    passport_date = State()
    outcome = State()
    visa_duration = State()
    confirm = State()


OUTCOME_LABELS = {"APPROVED": "✅ Виза получена", "REFUSED": "❌ В визе отказано"}

DURATION_RE = re.compile(
    r"^\s*(\d+)\s*(дн\w*|д|мес\w*|м|год\w*|лет|г)?\s*\.?\s*$", re.IGNORECASE
)


def parse_duration(text: str) -> int | None:
    """Срок визы -> дни. Понимает: «90», «90 дней», «6 месяцев», «1 год», «полгода»."""
    t = text.strip().lower()
    if t in ("год", "1 год", "годовая"):
        return 365
    if t == "полгода":
        return 180
    m = DURATION_RE.match(t)
    if not m:
        return None
    n, unit = int(m.group(1)), (m.group(2) or "д")
    if unit.startswith(("мес", "м")) and unit != "м.":
        days = n * 30
    elif unit.startswith(("год", "лет", "г")):
        days = n * 365
    else:
        days = n
    return days if 1 <= days <= 3650 else None


def fmt_duration(days: int | None) -> str:
    if not days:
        return "—"
    if days % 365 == 0:
        y = days // 365
        word = "год" if y == 1 else ("года" if 2 <= y <= 4 else "лет")
        return f"{y} {word}"
    if days % 30 == 0:
        m = days // 30
        word = "месяц" if m == 1 else ("месяца" if 2 <= m <= 4 else "месяцев")
        return f"{m} {word}"
    return f"{days} дн."


TIME_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*$")


def parse_time(text: str) -> str | None:
    m = TIME_RE.match(text)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if hh > 23 or mm > 59:
        return None
    return f"{hh:02d}:{mm:02d}"


def parse_date(text: str) -> date | None:
    m = DATE_RE.match(text)
    if not m:
        return None
    day, month, year = map(int, m.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def fmt(iso: str | None) -> str:
    if not iso:
        return "—"
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d.%m.%Y")


def parse_slots(text: str) -> list[list[str]] | None:
    """Список дат/интервалов через запятую -> [["от","до"], ...] (ISO), по возрастанию."""
    tokens = [t.strip() for t in re.split(r"[,;]", text) if t.strip()]
    if not tokens:
        return None
    pairs: list[list[str]] = []
    for token in tokens:
        m = PERIOD_RE.match(token)
        if m:
            d1, d2 = parse_date(m.group(1)), parse_date(m.group(2))
        else:
            d1 = d2 = parse_date(token)
        if d1 is None or d2 is None:
            return None
        if d2 < d1:
            d1, d2 = d2, d1
        pairs.append([d1.isoformat(), d2.isoformat()])
    pairs.sort(key=lambda p: p[0])
    return pairs


def fmt_slots(slots: list[list[str]] | None) -> str:
    if not slots:
        return "—"
    parts = []
    for start, end in slots:
        parts.append(fmt(start) if start == end else f"{fmt(start)} – {fmt(end)}")
    return ", ".join(parts)


def post_link(message_id: int) -> str:
    return f"https://t.me/c/{CHAT_LINK_ID}/{message_id}"


def post_kb(bot_username: str, city: str, visa_type: str) -> InlineKeyboardMarkup:
    """Кнопки под публикацией в теме: видны у каждого сообщения, а не только в закрепе."""
    idx = CITIES.index(city)
    base = f"https://t.me/{bot_username}?start="
    return _kb(
        [
            InlineKeyboardButton(text="📝 Анкета", url=f"{base}r_{idx}_{visa_type}"),
            InlineKeyboardButton(text="📊 Статистика", url=f"{base}s_{idx}_{visa_type}"),
            InlineKeyboardButton(text="🔮 Прогноз", url=f"{base}m_{idx}_{visa_type}"),
        ]
    )


def topic_id(city: str, visa_type: str) -> int | None:
    return TOPICS["cities"][city].get(visa_type)


def _kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


def back_btn(target: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=BACK, callback_data=f"back:{target}")


def city_kb() -> InlineKeyboardMarkup:
    rows, row = [], []
    for city in CITIES:
        row.append(InlineKeyboardButton(text=city, callback_data=f"city:{city}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def visa_kb(city: str) -> InlineKeyboardMarkup:
    # показываем только те категории, у которых есть тема в этом городе
    # (напр. D Карта поляка — только Гродно и Лида)
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"visa:{key}")]
        for key, label in VISA_TYPES.items()
        if topic_id(city, key)
    ]
    rows.append([back_btn("city")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subcat_kb(city: str, current: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    if current:
        rows.append(keep_btn("subcat", SUBCATS[current]))
    # «Карта поляка» как уточнение — только там, где нет отдельной темы (кроме Гродно/Лида)
    if not topic_id(city, "D_KARTA"):
        rows.append([InlineKeyboardButton(text="Карта поляка", callback_data="subcat:KARTA")])
    rows.append([InlineKeyboardButton(text="Ученическая", callback_data="subcat:STUDY")])
    rows.append([InlineKeyboardButton(text="➡️ Без уточнения", callback_data="subcat:none")])
    rows.append([back_btn("visa")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_kb() -> InlineKeyboardMarkup:
    return _kb(
        [
            InlineKeyboardButton(text="✅ Всё верно", callback_data="confirm:yes"),
            InlineKeyboardButton(text="🔄 Заполнить заново", callback_data="confirm:restart"),
        ],
        [back_btn("last")],
    )


def edit_offer_kb() -> InlineKeyboardMarkup:
    return _kb(
        [InlineKeyboardButton(text="✏️ Дополнить / исправить анкету", callback_data="edit:start")],
        [InlineKeyboardButton(text="❌ Ничего не менять", callback_data="edit:cancel")],
    )


def new_or_edit_kb() -> InlineKeyboardMarkup:
    return _kb(
        [InlineKeyboardButton(text="📝 Подать новую анкету", callback_data="new:start")],
        [InlineKeyboardButton(text="✏️ Дополнить предыдущую", callback_data="edit:start")],
        [InlineKeyboardButton(text="❌ Ничего не менять", callback_data="edit:cancel")],
    )


def keep_btn(step: str, label: str) -> list[InlineKeyboardButton]:
    """Кнопка «Оставить текущее значение» — появляется при дополнении анкеты."""
    return [InlineKeyboardButton(text=f"➡️ Оставить: {label}", callback_data=f"keep:{step}")]


def user_label(username: str | None, first_name: str) -> str:
    return f"@{username}" if username else first_name


SUSPECT_NOTE = (
    "⚠️ <i>Отмечено как сомнительное: срок ожидания аномально короткий. "
    "В статистике и прогнозах не учитывается.</i>"
)


def build_post_text(
    d: dict, username: str | None, first_name: str, edited: bool, suspect: bool = False
) -> str:
    """Текст публикации в теме города."""
    lines = [f"👤 {user_label(username, first_name)}"]
    if d.get("subcategory"):
        lines.append(f"🔖 Категория: <b>{SUBCATS[d['subcategory']]}</b>")
    when = fmt(d["queue_date"])
    if d.get("queue_time"):
        when += f" в {d['queue_time']}"
    lines.append(f"⏳ Встал(а) в очередь: <b>{when}</b>")
    if d.get("letter_date"):
        waited = (
            datetime.strptime(d["letter_date"], "%Y-%m-%d").date()
            - datetime.strptime(d["queue_date"], "%Y-%m-%d").date()
        ).days
        lines.append(f"📬 Письмо-приглашение: <b>{fmt(d['letter_date'])}</b> (ожидание {waited} дн.)")
    else:
        lines.append("📬 Письмо-приглашение: <b>ещё не пришло</b>")
    if d.get("slots"):
        lines.append(f"📆 Доступные даты записи: <b>{fmt_slots(d['slots'])}</b>")
    if d.get("submit_date"):
        lines.append(f"📄 Документы поданы: <b>{fmt(d['submit_date'])}</b>")
    if d.get("passport_date"):
        lines.append(f"🛂 Паспорт получен: <b>{fmt(d['passport_date'])}</b>")
    if d.get("outcome"):
        lines.append(f"<b>{OUTCOME_LABELS[d['outcome']]}</b>")
    if d.get("outcome") == "APPROVED" and d.get("visa_days"):
        lines.append(f"🎫 Виза на <b>{fmt_duration(d['visa_days'])}</b>")
    if suspect:
        lines.append(f"\n{SUSPECT_NOTE}")
    if edited:
        lines.append("\n✏️ <i>обновлено</i>")
    return "\n".join(lines)


def build_post_text_from_row(row) -> tuple[str, str, str]:
    """(текст публикации, city, visa_type) из строки БД — для перерисовки модерацией."""
    data = {
        "city": row["city"],
        "visa_type": row["visa_type"],
        "subcategory": row["subcategory"],
        "queue_date": row["queue_date"],
        "queue_time": row["queue_time"],
        "letter_date": row["letter_date"],
        "slots": json.loads(row["slots"]) if row["slots"] else None,
        "submit_date": row["submit_date"],
        "passport_date": row["passport_date"],
        "outcome": row["outcome"],
        "visa_days": row["visa_days"],
    }
    text = build_post_text(
        data, row["username"], "аноним", edited=False, suspect=bool(row["suspect"])
    )
    return text, row["city"], row["visa_type"]


# ---------- шаги анкеты (используются и при движении вперёд, и по кнопке «Назад») ----------

async def _render(message: Message, text: str, kb: InlineKeyboardMarkup | None, edit: bool) -> None:
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


async def ask_city(message: Message, state: FSMContext, edit: bool = False, greet: bool = False) -> None:
    data = await state.get_data()
    await state.set_state(Report.city)
    intro = (
        "Привет! Я собираю статистику очереди на польскую визу (VFS Global, Беларусь), "
        "чтобы прогнозировать сроки ожидания.\n\n"
        if greet
        else ""
    )
    kb = city_kb()
    if data.get("city"):
        kb.inline_keyboard.append(keep_btn("city", data["city"]))
    await _render(message, intro + "В каком городе вы становились в очередь?", kb, edit)


async def ask_visa(message: Message, state: FSMContext, edit: bool = False) -> None:
    data = await state.get_data()
    await state.set_state(Report.visa_type)
    kb = visa_kb(data["city"])
    if data.get("visa_type") and topic_id(data["city"], data["visa_type"]):
        kb.inline_keyboard.insert(-1, keep_btn("visa", VISA_TYPES[data["visa_type"]]))
    await _render(message, f"Город: <b>{data['city']}</b>\n\nКакой тип визы?", kb, edit)


async def ask_subcategory(message: Message, state: FSMContext, edit: bool = False) -> None:
    data = await state.get_data()
    await state.set_state(Report.subcategory)
    await _render(
        message,
        f"Город: <b>{data['city']}</b>, тип: <b>{VISA_TYPES['D_OTHER']}</b>\n\n"
        "Уточните категорию (необязательно):",
        subcat_kb(data["city"], data.get("subcategory")),
        edit,
    )


async def ask_queue_date(message: Message, state: FSMContext, edit: bool = False) -> None:
    data = await state.get_data()
    await state.set_state(Report.queue_date)
    rows = []
    if data.get("queue_date"):
        rows.append(keep_btn("queue", fmt(data["queue_date"])))
    rows.append([back_btn("subcat" if data.get("visa_type") == "D_OTHER" else "visa")])
    await _render(
        message,
        f"Город: <b>{data['city']}</b>\n"
        f"Тип визы: <b>{VISA_TYPES[data['visa_type']]}</b>\n\n"
        "Когда вы встали в очередь VFS?\nВведите дату в формате <b>ДД.ММ.ГГГГ</b>, например 15.03.2026",
        _kb(*rows),
        edit,
    )


async def ask_queue_time(message: Message, state: FSMContext, edit: bool = False) -> None:
    data = await state.get_data()
    await state.set_state(Report.queue_time)
    rows = []
    if data.get("queue_time"):
        rows.append(keep_btn("time", data["queue_time"]))
    rows.append([InlineKeyboardButton(text="🤷 Не помню / пропустить", callback_data="time:none")])
    rows.append([back_btn("queue")])
    await _render(
        message,
        f"Во сколько вы встали в очередь {fmt(data['queue_date'])}?\n"
        "Введите время в формате <b>ЧЧ:ММ</b>, например 09:15.\n"
        "Это помогает понять позицию внутри дня, когда очередь долго стоит на одной дате.",
        _kb(*rows),
        edit,
    )


async def ask_letter_date(message: Message, state: FSMContext, edit: bool = False) -> None:
    data = await state.get_data()
    await state.set_state(Report.letter_date)
    rows = []
    if data.get("letter_date"):
        rows.append(keep_btn("letter", fmt(data["letter_date"])))
    rows.append([InlineKeyboardButton(text="📭 Письмо ещё не пришло", callback_data="letter:none")])
    rows.append([back_btn("time")])
    await _render(
        message,
        "Когда на почту пришло письмо с приглашением записаться в визовый центр?\n"
        "Введите дату (ДД.ММ.ГГГГ) или нажмите кнопку, если письма ещё нет.",
        _kb(*rows),
        edit,
    )


async def ask_slots(message: Message, state: FSMContext, edit: bool = False) -> None:
    data = await state.get_data()
    await state.set_state(Report.slots)
    rows = []
    if data.get("slots"):
        rows.append(keep_btn("slots", fmt_slots(data["slots"])))
    rows.append([InlineKeyboardButton(text="🤷 Не помню / пропустить", callback_data="slots:none")])
    rows.append([back_btn("letter")])
    await _render(
        message,
        "Какие даты записи в визовый центр были доступны?\n"
        "Можно указать несколько дат и периодов через запятую:\n"
        "• одна дата: <b>01.09.2026</b>\n"
        "• период: <b>01.09.2026-15.09.2026</b>\n"
        "• вместе: <b>01.09.2026, 05.09.2026, 10.09.2026-15.09.2026</b>",
        _kb(*rows),
        edit,
    )


async def ask_submit_date(message: Message, state: FSMContext, edit: bool = False) -> None:
    data = await state.get_data()
    await state.set_state(Report.submit_date)
    rows = []
    if data.get("submit_date"):
        rows.append(keep_btn("submit", fmt(data["submit_date"])))
    rows.append([InlineKeyboardButton(text="📄 Ещё не подавал(а)", callback_data="submit:none")])
    rows.append([back_btn("slots")])
    await _render(
        message,
        "Когда вы подали документы в визовый центр?\n"
        "Введите дату (ДД.ММ.ГГГГ) или нажмите кнопку, если подача ещё впереди.",
        _kb(*rows),
        edit,
    )


async def ask_passport_date(message: Message, state: FSMContext, edit: bool = False) -> None:
    data = await state.get_data()
    await state.set_state(Report.passport_date)
    rows = []
    if data.get("passport_date"):
        rows.append(keep_btn("passport", fmt(data["passport_date"])))
    rows.append([InlineKeyboardButton(text="⏳ Паспорт ещё не вернули", callback_data="passport:none")])
    rows.append([back_btn("submit")])
    await _render(
        message,
        "Когда вы получили паспорт обратно?\n"
        "Введите дату (ДД.ММ.ГГГГ) или нажмите кнопку, если паспорт ещё в визовом центре.",
        _kb(*rows),
        edit,
    )


async def ask_outcome(message: Message, state: FSMContext, edit: bool = False) -> None:
    data = await state.get_data()
    await state.set_state(Report.outcome)
    rows = []
    if data.get("outcome"):
        rows.append(keep_btn("outcome", OUTCOME_LABELS[data["outcome"]]))
    rows.append([InlineKeyboardButton(text="✅ Виза получена", callback_data="outcome:APPROVED")])
    rows.append([InlineKeyboardButton(text="❌ В визе отказано", callback_data="outcome:REFUSED")])
    rows.append([back_btn("passport")])
    await _render(message, "Какой результат?", _kb(*rows), edit)


async def ask_visa_duration(message: Message, state: FSMContext, edit: bool = False) -> None:
    data = await state.get_data()
    await state.set_state(Report.visa_duration)
    rows = []
    if data.get("visa_days"):
        rows.append(keep_btn("duration", fmt_duration(data["visa_days"])))
    rows.append([
        InlineKeyboardButton(text="90 дней", callback_data="dur:90"),
        InlineKeyboardButton(text="6 месяцев", callback_data="dur:180"),
    ])
    rows.append([
        InlineKeyboardButton(text="1 год", callback_data="dur:365"),
        InlineKeyboardButton(text="2 года", callback_data="dur:730"),
    ])
    rows.append([InlineKeyboardButton(text="🤷 Пропустить", callback_data="dur:none")])
    rows.append([back_btn("outcome")])
    await _render(
        message,
        "🎫 На какой срок выдана виза? (необязательно)\n"
        "Выберите вариант или введите свой: <b>45 дней</b>, <b>18 месяцев</b>, <b>1 год</b>",
        _kb(*rows),
        edit,
    )


# ---------- команды ----------

PAYLOAD_RE = re.compile(r"^r_(\d+)_([A-Z_]+)$")


def make_payload(city: str, visa_type: str) -> str:
    return f"r_{CITIES.index(city)}_{visa_type}"


def parse_payload(payload: str) -> tuple[str, str] | None:
    """Deep-link из темы группы -> (город, тип визы)."""
    m = PAYLOAD_RE.match(payload or "")
    if not m:
        return None
    idx, visa = int(m.group(1)), m.group(2)
    if idx >= len(CITIES) or visa not in VISA_TYPES:
        return None
    return CITIES[idx], visa


async def _entry_gate(
    message: Message,
    state: FSMContext,
    prefill: tuple[str, str] | None = None,
    user_id: int | None = None,
) -> bool:
    """True = у пользователя уже есть анкета, ему предложен выбор действий.

    До REPORT_COOLDOWN_DAYS дней — только исправление текущей анкеты,
    после — выбор: подать новую или исправить предыдущую.
    `user_id` передаётся, когда вход не из сообщения пользователя (кнопка):
    message тогда принадлежит боту и message.from_user — не тот человек.
    """
    latest = db.find_latest(user_id or message.from_user.id)
    if not latest:
        return False
    await state.update_data(editing_id=latest["id"])
    if prefill:
        await state.update_data(pending_city=prefill[0], pending_visa=prefill[1])
    created = datetime.fromisoformat(latest["created_at"])
    age_days = (datetime.now(timezone.utc) - created).days
    header = (
        "Ваша последняя анкета от "
        f"<b>{created.strftime('%d.%m.%Y')}</b> "
        f"({latest['city']}, {VISA_TYPES[latest['visa_type']]}).\n"
    )
    if age_days < REPORT_COOLDOWN_DAYS:
        await message.answer(
            header
            + "Пришло письмо, подали документы или получили паспорт? Дополните анкету — "
            "новые данные попадут в статистику. Ошиблись в датах — там же можно исправить.\n"
            f"(Полностью новая анкета — раз в {REPORT_COOLDOWN_DAYS} дней.)",
            reply_markup=edit_offer_kb(),
        )
    else:
        await message.answer(
            header + "Что хотите сделать?",
            reply_markup=new_or_edit_kb(),
        )
    return True


@router.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: Message, command: CommandObject, state: FSMContext) -> None:
    await state.clear()
    parsed = parse_payload(command.args)
    if parsed is None:
        await cmd_start(message, state)
        return
    db.log_event(message.from_user.id, "start")
    if await _entry_gate(message, state, prefill=parsed):
        return
    city, visa = parsed
    # город и тип подставлены из темы — для воронки эти шаги пройдены
    db.log_event(message.from_user.id, "city")
    db.log_event(message.from_user.id, "visa")
    await state.update_data(city=city, visa_type=visa)
    await ask_queue_date(message, state)


@router.message(CommandStart())
@router.message(Command("report"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    db.log_event(message.from_user.id, "start")
    if await _entry_gate(message, state):
        return
    await ask_city(message, state, greet=True)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Анкета отменена. Начать заново — /report")


# ---------- редактирование ----------

@router.callback_query(F.data == "edit:cancel")
async def edit_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Хорошо, данные остаются без изменений. Если что — /report")
    await callback.answer()


@router.callback_query(F.data == "new:start")
async def new_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Новая анкета после истечения 14 дней (предыдущая остаётся в истории)."""
    data = await state.get_data()
    await state.clear()
    city, visa = data.get("pending_city"), data.get("pending_visa")
    if city and visa:
        # переход из темы группы: город и тип визы уже известны
        await state.update_data(city=city, visa_type=visa)
        await ask_queue_date(callback.message, state, edit=True)
    else:
        await ask_city(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(F.data == "edit:start")
async def edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("editing_id"):
        await callback.answer("Сессия устарела, отправьте /report", show_alert=True)
        return
    row = db.get_report(data["editing_id"])
    if row is None:
        await callback.answer("Анкета не найдена, отправьте /report", show_alert=True)
        return
    db.log_event(callback.from_user.id, "edit_start")
    # предзагружаем текущие данные: на каждом шаге появится кнопка «Оставить»
    await state.update_data(
        city=row["city"],
        visa_type=row["visa_type"],
        subcategory=row["subcategory"],
        queue_date=row["queue_date"],
        queue_time=row["queue_time"],
        letter_date=row["letter_date"],
        slots=json.loads(row["slots"]) if row["slots"] else None,
        submit_date=row["submit_date"],
        passport_date=row["passport_date"],
        outcome=row["outcome"],
        visa_days=row["visa_days"],
    )
    await callback.message.edit_text(
        "Дополним анкету. На каждом шаге можно нажать «➡️ Оставить», чтобы не вводить "
        "заново то, что не изменилось, — и дойти до места, где появились новые данные."
    )
    await ask_city(callback.message, state)
    await callback.answer()


# ---------- /funnel: воронка анкеты (только владелец) ----------

FUNNEL_STEPS = [
    ("start", "Вход в анкету"),
    ("city", "Выбрали город"),
    ("visa", "Выбрали тип визы"),
    ("queue_date", "Ввели дату постановки"),
    ("letter", "Прошли шаг письма"),
    ("saved_new", "✅ Сохранили новую анкету"),
]


@router.message(Command("funnel"))
async def cmd_funnel(message: Message, command: CommandObject) -> None:
    admin = _admin_id()
    if not admin or message.from_user.id != admin:
        await message.answer("Команда доступна только владельцу группы.")
        return
    try:
        days = max(1, min(90, int(command.args))) if command.args else 7
    except ValueError:
        days = 7
    counts = db.funnel_counts(days)
    start = counts.get("start", 0)
    lines = [f"🔬 <b>Воронка анкеты за {days} дн.</b> (уникальные пользователи)", ""]
    if start == 0:
        lines.append("Событий пока нет — телеметрия копится с 24.07.2026.")
    else:
        for event, label in FUNNEL_STEPS:
            n = counts.get(event, 0)
            pct = f"{100 * n // start}%" if start else "—"
            lines.append(f"<code>{n:>4} · {pct:>4}</code>  {label}")
        lines.append("")
        lines.append(
            f"✏️ Дополнение анкет: начали {counts.get('edit_start', 0)}, "
            f"сохранили {counts.get('saved_edit', 0)}"
        )
        drop = [
            (FUNNEL_STEPS[i][1], counts.get(FUNNEL_STEPS[i][0], 0) - counts.get(FUNNEL_STEPS[i + 1][0], 0))
            for i in range(len(FUNNEL_STEPS) - 1)
        ]
        worst = max(drop, key=lambda x: x[1])
        if worst[1] > 0:
            lines.append(f"📉 Наибольшая потеря: после шага «{worst[0]}» (−{worst[1]})")
    await message.answer("\n".join(lines))


# ---------- кнопка «Оставить» (пропуск шага с сохранением значения) ----------

@router.callback_query(F.data.startswith("keep:"))
async def keep_value(callback: CallbackQuery, state: FSMContext) -> None:
    step = callback.data.split(":", 1)[1]
    data = await state.get_data()
    # «Оставить тип D (Other)» ведёт к шагу уточнения категории, иначе — к дате
    if step == "visa" and data.get("visa_type"):
        if data["visa_type"] == "D_OTHER":
            await ask_subcategory(callback.message, state, edit=True)
        else:
            await ask_queue_date(callback.message, state, edit=True)
        await callback.answer()
        return
    if step == "subcat":
        await ask_queue_date(callback.message, state, edit=True)
        await callback.answer()
        return
    forward = {
        "city": ("city", ask_visa),
        "queue": ("queue_date", ask_queue_time),
        "time": ("queue_time", ask_letter_date),
        "letter": ("letter_date", ask_slots),
        "slots": ("slots", ask_submit_date),
        "submit": ("submit_date", ask_passport_date),
        "passport": ("passport_date", ask_outcome),
    }
    if step == "outcome" and data.get("outcome"):
        if data["outcome"] == "APPROVED":
            await ask_visa_duration(callback.message, state, edit=True)
        else:
            await state.update_data(last_step="outcome")
            await state.set_state(Report.confirm)
            await show_summary(callback.message, state, edit=True)
        await callback.answer()
        return
    if step == "duration":
        await state.update_data(last_step="duration")
        await state.set_state(Report.confirm)
        await show_summary(callback.message, state, edit=True)
        await callback.answer()
        return
    if step in forward and data.get(forward[step][0]):
        funnel_event = {"city": "city", "visa": "visa", "queue": "queue_date", "letter": "letter"}.get(step)
        if funnel_event:
            db.log_event(callback.from_user.id, funnel_event)
        await forward[step][1](callback.message, state, edit=True)
        await callback.answer()
        return
    await callback.answer("Сессия устарела, отправьте /report", show_alert=True)


# ---------- кнопка «Назад» ----------

@router.callback_query(F.data.startswith("back:"))
async def go_back(callback: CallbackQuery, state: FSMContext) -> None:
    target = callback.data.split(":", 1)[1]
    data = await state.get_data()
    if target == "city":
        await ask_city(callback.message, state, edit=True)
    elif target == "visa" and data.get("city"):
        await ask_visa(callback.message, state, edit=True)
    elif target == "subcat" and data.get("visa_type") == "D_OTHER":
        await ask_subcategory(callback.message, state, edit=True)
    elif target == "queue" and data.get("visa_type"):
        await ask_queue_date(callback.message, state, edit=True)
    elif target == "time" and data.get("queue_date"):
        await ask_queue_time(callback.message, state, edit=True)
    elif target == "letter" and data.get("queue_date"):
        await ask_letter_date(callback.message, state, edit=True)
    elif target == "slots" and data.get("letter_date"):
        await ask_slots(callback.message, state, edit=True)
    elif target == "submit" and data.get("letter_date"):
        await ask_submit_date(callback.message, state, edit=True)
    elif target == "passport" and data.get("submit_date"):
        await ask_passport_date(callback.message, state, edit=True)
    elif target == "outcome" and data.get("passport_date"):
        await ask_outcome(callback.message, state, edit=True)
    elif target == "last" and data.get("queue_date"):
        # с экрана подтверждения — на последний пройденный шаг
        step = data.get("last_step")
        back_map = {
            "letter": ask_letter_date,
            "submit": ask_submit_date,
            "passport": ask_passport_date,
            "outcome": ask_outcome,
            "duration": ask_visa_duration,
        }
        await back_map.get(step, ask_letter_date)(callback.message, state, edit=True)
    else:
        await callback.answer("Сессия устарела, отправьте /report", show_alert=True)
        return
    await callback.answer()


# ---------- шаги вперёд ----------

@router.callback_query(Report.city, F.data.startswith("city:"))
async def pick_city(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(city=callback.data.split(":", 1)[1])
    db.log_event(callback.from_user.id, "city")
    await ask_visa(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(Report.visa_type, F.data.startswith("visa:"))
async def pick_visa(callback: CallbackQuery, state: FSMContext) -> None:
    visa = callback.data.split(":", 1)[1]
    await state.update_data(visa_type=visa)
    db.log_event(callback.from_user.id, "visa")
    if visa == "D_OTHER":
        await ask_subcategory(callback.message, state, edit=True)
    else:
        await state.update_data(subcategory=None)
        await ask_queue_date(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(Report.subcategory, F.data.startswith("subcat:"))
async def pick_subcategory(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    sub = value if value in SUBCATS else None
    await state.update_data(subcategory=sub)
    await ask_queue_date(callback.message, state, edit=True)
    await callback.answer()


@router.message(Report.queue_date, F.text)
async def input_queue_date(message: Message, state: FSMContext) -> None:
    d = parse_date(message.text)
    if d is None:
        await message.answer("Не понял дату. Формат: ДД.ММ.ГГГГ, например 15.03.2026")
        return
    if d > date.today():
        await message.answer("Дата постановки в очередь не может быть в будущем. Проверьте и введите ещё раз.")
        return
    await state.update_data(queue_date=d.isoformat())
    db.log_event(message.from_user.id, "queue_date")
    await ask_queue_time(message, state)


@router.callback_query(Report.queue_time, F.data == "time:none")
async def queue_time_none(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(queue_time=None)
    await ask_letter_date(callback.message, state, edit=True)
    await callback.answer()


@router.message(Report.queue_time, F.text)
async def input_queue_time(message: Message, state: FSMContext) -> None:
    t = parse_time(message.text)
    if t is None:
        await message.answer("Не понял время. Формат: ЧЧ:ММ, например 09:15 — или нажмите «пропустить».")
        return
    await state.update_data(queue_time=t)
    await ask_letter_date(message, state)


@router.callback_query(Report.letter_date, F.data == "letter:none")
async def letter_none(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(
        letter_date=None, slots=None, submit_date=None, passport_date=None,
        outcome=None, last_step="letter", suspect_wait=False,
    )
    db.log_event(callback.from_user.id, "letter")
    await state.set_state(Report.confirm)
    await show_summary(callback.message, state, edit=True)
    await callback.answer()


@router.message(Report.letter_date, F.text)
async def input_letter_date(message: Message, state: FSMContext) -> None:
    d = parse_date(message.text)
    if d is None:
        await message.answer("Не понял дату. Формат: ДД.ММ.ГГГГ, или нажмите кнопку «Письмо ещё не пришло».")
        return
    data = await state.get_data()
    if d.isoformat() < data["queue_date"]:
        await message.answer("Дата письма раньше даты постановки в очередь — так не бывает. Проверьте и введите ещё раз.")
        return
    suspicious, wait, med = stats.wait_suspicion(
        data["city"], data["visa_type"], data["queue_date"], d.isoformat()
    )
    if suspicious:
        await state.update_data(pending_letter=d.isoformat())
        await message.answer(
            f"⚠️ По вашим датам ожидание письма — <b>{wait} дн.</b>, при типичных "
            f"для этого города ~{med} дн. Чаще всего так выходит из-за опечатки "
            "в месяце или годе.\n\nПроверьте даты постановки в очередь и письма.",
            reply_markup=_kb(
                [InlineKeyboardButton(text="✏️ Исправить даты", callback_data="swait:fix")],
                [InlineKeyboardButton(text="✅ Да, всё верно", callback_data="swait:ok")],
            ),
        )
        return
    await state.update_data(letter_date=d.isoformat(), suspect_wait=False)
    db.log_event(message.from_user.id, "letter")
    await ask_slots(message, state)


@router.callback_query(Report.letter_date, F.data == "swait:fix")
async def suspect_wait_fix(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(pending_letter=None)
    await ask_letter_date(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(Report.letter_date, F.data == "swait:ok")
async def suspect_wait_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("pending_letter"):
        await callback.answer("Сессия устарела, отправьте /report", show_alert=True)
        return
    await state.update_data(letter_date=data["pending_letter"], pending_letter=None, suspect_wait=True)
    db.log_event(callback.from_user.id, "letter")
    await ask_slots(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(Report.slots, F.data == "slots:none")
async def slots_none(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(slots=None)
    await ask_submit_date(callback.message, state, edit=True)
    await callback.answer()


@router.message(Report.slots, F.text)
async def input_slots(message: Message, state: FSMContext) -> None:
    slots = parse_slots(message.text)
    if slots is None:
        await message.answer(
            "Не понял. Примеры: <b>01.09.2026</b>, <b>01.09.2026-15.09.2026</b>, "
            "<b>01.09.2026, 10.09.2026-15.09.2026</b>"
        )
        return
    await state.update_data(slots=slots)
    await ask_submit_date(message, state)


@router.callback_query(Report.submit_date, F.data == "submit:none")
async def submit_none(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(submit_date=None, passport_date=None, outcome=None, last_step="submit")
    await state.set_state(Report.confirm)
    await show_summary(callback.message, state, edit=True)
    await callback.answer()


@router.message(Report.submit_date, F.text)
async def input_submit_date(message: Message, state: FSMContext) -> None:
    d = parse_date(message.text)
    if d is None:
        await message.answer("Не понял дату. Формат: ДД.ММ.ГГГГ, или кнопка «Ещё не подавал(а)».")
        return
    data = await state.get_data()
    if d > date.today():
        await message.answer("Дата подачи в будущем — укажите фактическую дату или нажмите «Ещё не подавал(а)».")
        return
    if data.get("letter_date") and d.isoformat() < data["letter_date"]:
        await message.answer("Подача раньше письма-приглашения — так не бывает. Проверьте дату.")
        return
    await state.update_data(submit_date=d.isoformat())
    await ask_passport_date(message, state)


@router.callback_query(Report.passport_date, F.data == "passport:none")
async def passport_none(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(passport_date=None, outcome=None, last_step="passport")
    await state.set_state(Report.confirm)
    await show_summary(callback.message, state, edit=True)
    await callback.answer()


@router.message(Report.passport_date, F.text)
async def input_passport_date(message: Message, state: FSMContext) -> None:
    d = parse_date(message.text)
    if d is None:
        await message.answer("Не понял дату. Формат: ДД.ММ.ГГГГ, или кнопка «Паспорт ещё не вернули».")
        return
    data = await state.get_data()
    if d > date.today():
        await message.answer("Дата получения паспорта в будущем — проверьте и введите ещё раз.")
        return
    if data.get("submit_date") and d.isoformat() < data["submit_date"]:
        await message.answer("Паспорт вернули раньше подачи — так не бывает. Проверьте дату.")
        return
    await state.update_data(passport_date=d.isoformat())
    await ask_outcome(message, state)


@router.callback_query(Report.outcome, F.data.startswith("outcome:"))
async def pick_outcome(callback: CallbackQuery, state: FSMContext) -> None:
    outcome = callback.data.split(":", 1)[1]
    if outcome not in OUTCOME_LABELS:
        await callback.answer("Неизвестный вариант", show_alert=True)
        return
    if outcome == "APPROVED":
        await state.update_data(outcome=outcome)
        await ask_visa_duration(callback.message, state, edit=True)
    else:
        await state.update_data(outcome=outcome, visa_days=None, last_step="outcome")
        await state.set_state(Report.confirm)
        await show_summary(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(Report.visa_duration, F.data.startswith("dur:"))
async def pick_duration(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    days = None if value == "none" else int(value)
    await state.update_data(visa_days=days, last_step="duration")
    await state.set_state(Report.confirm)
    await show_summary(callback.message, state, edit=True)
    await callback.answer()


@router.message(Report.visa_duration, F.text)
async def input_duration(message: Message, state: FSMContext) -> None:
    days = parse_duration(message.text)
    if days is None:
        await message.answer(
            "Не понял срок. Примеры: <b>90 дней</b>, <b>6 месяцев</b>, <b>1 год</b> — "
            "или нажмите «Пропустить»."
        )
        return
    await state.update_data(visa_days=days, last_step="duration")
    await state.set_state(Report.confirm)
    await show_summary(message, state)


async def show_summary(message: Message, state: FSMContext, edit: bool = False) -> None:
    data = await state.get_data()
    when = fmt(data["queue_date"])
    if data.get("queue_time"):
        when += f" в {data['queue_time']}"
    subcat_line = (
        f"🔖 Категория: <b>{SUBCATS[data['subcategory']]}</b>\n"
        if data.get("subcategory") else ""
    )
    text = (
        "Проверьте данные:\n\n"
        f"🏙 Город: <b>{data['city']}</b>\n"
        f"📄 Тип визы: <b>{VISA_TYPES[data['visa_type']]}</b>\n"
        f"{subcat_line}"
        f"⏳ Встал(а) в очередь: <b>{when}</b>\n"
        f"📬 Письмо-приглашение: <b>{fmt(data.get('letter_date'))}</b>\n"
        f"📆 Доступные даты записи: <b>{fmt_slots(data.get('slots'))}</b>\n"
        f"📄 Подача документов: <b>{fmt(data.get('submit_date'))}</b>\n"
        f"🛂 Паспорт получен: <b>{fmt(data.get('passport_date'))}</b>\n"
        f"Результат: <b>{OUTCOME_LABELS.get(data.get('outcome'), '—')}</b>\n"
        f"🎫 Срок визы: <b>{fmt_duration(data.get('visa_days'))}</b>"
    )
    await _render(message, text, confirm_kb(), edit)


@router.callback_query(Report.confirm, F.data == "confirm:restart")
async def confirm_restart(callback: CallbackQuery, state: FSMContext) -> None:
    editing_id = (await state.get_data()).get("editing_id")
    await state.clear()
    if editing_id:
        await state.update_data(editing_id=editing_id)
    await ask_city(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(Report.confirm, F.data == "confirm:yes")
async def confirm_yes(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    user = callback.from_user

    if data.get("editing_id"):
        await _apply_edit(callback, data, data["editing_id"])
        await state.clear()
        await callback.answer()
        return

    suspect = 1 if data.get("suspect_wait") else 0
    report_id = db.save_report(
        user_id=user.id,
        username=user.username,
        city=data["city"],
        visa_type=data["visa_type"],
        queue_date=data["queue_date"],
        queue_time=data.get("queue_time"),
        letter_date=data.get("letter_date"),
        slots=json.dumps(data["slots"]) if data.get("slots") else None,
        submit_date=data.get("submit_date"),
        passport_date=data.get("passport_date"),
        outcome=data.get("outcome"),
        suspect=suspect,
        visa_days=data.get("visa_days"),
        subcategory=data.get("subcategory"),
    )
    db.log_event(user.id, "saved_new")
    if suspect:
        await _notify_admin_suspect(callback.bot, report_id, data, user)
    tid = topic_id(data["city"], data["visa_type"])
    buttons = []
    if tid:
        me = await callback.bot.me()
        posted = await callback.bot.send_message(
            chat_id=CHAT_ID,
            message_thread_id=tid,
            text=build_post_text(
                data, user.username, user.first_name, edited=False, suspect=bool(suspect)
            ),
            reply_markup=post_kb(me.username, data["city"], data["visa_type"]),
        )
        db.set_message_id(report_id, posted.message_id)
        buttons.append(
            [InlineKeyboardButton(text="👀 Посмотреть публикацию", url=post_link(posted.message_id))]
        )
    buttons.append(
        [InlineKeyboardButton(
            text="🔮 Мой прогноз", callback_data=f"mgo:{data['city']}:{data['visa_type']}"
        )]
    )
    total = len(db.reports_for(data["city"], data["visa_type"]))
    when = fmt(data["queue_date"])
    if data.get("queue_time"):
        when += f" в {data['queue_time']}"
    day_n = (date.today() - datetime.strptime(data["queue_date"], "%Y-%m-%d").date()).days + 1
    letter = fmt(data["letter_date"]) if data.get("letter_date") else "ещё не пришло"
    await callback.message.edit_text(
        "✅ <b>Анкета засчитана — спасибо!</b>\n\n"
        f"🏙 {data['city']} · 📄 {VISA_TYPES[data['visa_type']]}\n"
        f"⏳ В очереди: <b>{when}</b> ({day_n}-й день)\n"
        f"📬 Письмо: <b>{letter}</b>\n"
        f"📆 Даты записи: <b>{fmt_slots(data.get('slots'))}</b>\n\n"
        f"Ваш вклад в статистику: по {data['city']} теперь <b>{total}</b> анкет — "
        "точность прогнозов растёт.\n"
        "Пришло письмо, подали документы, получили паспорт? Дополните анкету "
        "в любой момент: /report",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await _post_save_hooks(callback.bot, data["city"], data["visa_type"], data.get("letter_date"))
    await state.clear()
    await callback.answer()


def _admin_id() -> int | None:
    admin = os.environ.get("ADMIN_CHAT_ID")
    return int(admin) if admin else None


async def _notify_admin_suspect(bot, report_id: int, data: dict, user) -> None:
    """Карточка сомнительной анкеты админу: удалить / оставить / доверять."""
    admin = _admin_id()
    if not admin:
        return
    wait = (
        datetime.strptime(data["letter_date"], "%Y-%m-%d")
        - datetime.strptime(data["queue_date"], "%Y-%m-%d")
    ).days
    try:
        await bot.send_message(
            chat_id=admin,
            text=(
                "⚠️ <b>Сомнительная анкета</b> (пользователь подтвердил аномальные даты; "
                "в статистике не учитывается)\n\n"
                f"🏙 {data['city']} · {VISA_TYPES[data['visa_type']]}\n"
                f"👤 {user_label(user.username, user.first_name)} (id {user.id})\n"
                f"⏳ Очередь: {fmt(data['queue_date'])} → 📬 письмо: {fmt(data['letter_date'])} "
                f"= <b>{wait} дн.</b>"
            ),
            reply_markup=_kb(
                [
                    InlineKeyboardButton(text="🗑 Удалить", callback_data=f"adm:del:{report_id}"),
                    InlineKeyboardButton(text="👌 Оставить", callback_data=f"adm:keep:{report_id}"),
                ],
                [InlineKeyboardButton(text="✅ Доверять (в статистику)", callback_data=f"adm:trust:{report_id}")],
            ),
        )
    except Exception:
        logging.getLogger("moderation").exception("не удалось отправить карточку админу")


@router.callback_query(F.data.startswith("adm:"))
async def admin_decision(callback: CallbackQuery) -> None:
    admin = _admin_id()
    if not admin or callback.from_user.id != admin:
        await callback.answer("Кнопка только для администратора.", show_alert=True)
        return
    _, action, report_id = callback.data.split(":", 2)
    row = db.get_report(int(report_id))
    if row is None:
        await callback.message.edit_text(callback.message.html_text + "\n\n<i>анкета уже удалена</i>")
        await callback.answer()
        return
    if action == "del":
        if row["message_id"]:
            try:
                await callback.bot.delete_message(CHAT_ID, row["message_id"])
            except TelegramBadRequest:
                pass
        db.delete_report(row["id"])
        verdict = "🗑 анкета удалена (и из базы, и из темы)"
    else:
        if action == "trust":
            db.set_suspect(row["id"], 0)
            verdict = "✅ анкета включена в статистику, приписка снята"
        else:
            db.set_suspect(row["id"], 1)
            verdict = "👌 оставлена как сомнительная (вне статистики), приписка в публикации"
        # перерисовываем публикацию: приписка появляется/исчезает
        row = db.get_report(int(report_id))
        if row["message_id"]:
            text, city, visa = build_post_text_from_row(row)
            me = await callback.bot.me()
            try:
                await callback.bot.edit_message_text(
                    chat_id=CHAT_ID, message_id=row["message_id"], text=text,
                    reply_markup=post_kb(me.username, city, visa),
                )
            except TelegramBadRequest:
                pass
    stats.note_write(row["city"], row["visa_type"])
    await callback.message.edit_text(callback.message.html_text + f"\n\n<b>Решение:</b> {verdict}")
    await callback.answer("Готово")


async def _post_save_hooks(bot, city: str, visa_type: str, letter_iso: str | None) -> None:
    """После сохранения анкеты: учёт записи для кеша статистики + алерт о всплеске."""
    stats.note_write(city, visa_type)
    if not letter_iso or db.alert_sent(city, visa_type, letter_iso):
        return
    spike = stats.check_spike(city, visa_type, letter_iso)
    if not spike:
        return
    tid = topic_id(city, visa_type)
    if not tid:
        return
    db.mark_alert(city, visa_type, letter_iso)
    ld = datetime.strptime(letter_iso, "%Y-%m-%d").strftime("%d.%m.%Y")
    me = await bot.me()
    await bot.send_message(
        chat_id=CHAT_ID,
        message_thread_id=tid,
        text=(
            f"📈 <b>Очередь двинулась!</b>\n"
            f"За <b>{ld}</b> по анкетам уже <b>{spike}</b> приглашений в визовый центр "
            f"({city}, {VISA_TYPES[visa_type]}). Ждёте письмо с близкой датой постановки — "
            "проверяйте почту!"
        ),
        reply_markup=post_kb(me.username, city, visa_type),
    )


async def _apply_edit(callback: CallbackQuery, data: dict, editing_id: int) -> None:
    """Обновляет отчёт и сообщение бота в теме (или переносит его в другую тему)."""
    user = callback.from_user
    old = db.get_report(editing_id)
    if data.get("suspect_wait"):
        suspect = 1
    elif data.get("letter_date") == old["letter_date"] and data["queue_date"] == old["queue_date"]:
        suspect = old["suspect"] or 0  # даты не менялись — статус сохраняем
    else:
        suspect = 0
    db.update_report(
        report_id=editing_id,
        queue_date=data["queue_date"],
        queue_time=data.get("queue_time"),
        letter_date=data.get("letter_date"),
        slots=json.dumps(data["slots"]) if data.get("slots") else None,
        submit_date=data.get("submit_date"),
        passport_date=data.get("passport_date"),
        outcome=data.get("outcome"),
        suspect=suspect,
        username=user.username,
        visa_days=data.get("visa_days"),
        subcategory=data.get("subcategory"),
    )
    if suspect and not (old["suspect"] or 0):
        await _notify_admin_suspect(callback.bot, editing_id, data, user)
    new_text = build_post_text(
        data, user.username, user.first_name, edited=True, suspect=bool(suspect)
    )
    moved = old["city"] != data["city"] or old["visa_type"] != data["visa_type"]
    if moved:
        db.update_city_type(editing_id, data["city"], data["visa_type"])
    tid = topic_id(data["city"], data["visa_type"])

    me = await callback.bot.me()
    kb_post = post_kb(me.username, data["city"], data["visa_type"])
    final_message_id = old["message_id"]
    if moved or not old["message_id"]:
        if old["message_id"]:
            try:
                await callback.bot.delete_message(CHAT_ID, old["message_id"])
            except TelegramBadRequest:
                pass
        final_message_id = None
        if tid:
            posted = await callback.bot.send_message(
                chat_id=CHAT_ID, message_thread_id=tid, text=new_text, reply_markup=kb_post
            )
            db.set_message_id(editing_id, posted.message_id)
            final_message_id = posted.message_id
    else:
        try:
            await callback.bot.edit_message_text(
                chat_id=CHAT_ID, message_id=old["message_id"], text=new_text,
                reply_markup=kb_post,
            )
        except TelegramBadRequest:
            pass  # текст не изменился — не страшно

    kb = None
    if final_message_id:
        kb = _kb(
            [InlineKeyboardButton(text="👀 Посмотреть публикацию", url=post_link(final_message_id))]
        )
    db.log_event(user.id, "saved_edit")
    await callback.message.edit_text(
        "✅ Анкета обновлена, публикация в группе изменена.\n\nЕсли что-то ещё — /report",
        reply_markup=kb,
    )
    if moved:
        stats.note_write(old["city"], old["visa_type"])
    await _post_save_hooks(callback.bot, data["city"], data["visa_type"], data.get("letter_date"))
