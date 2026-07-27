"""Команды /stats (сводка + график) и /my (персональный прогноз)."""
import os
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from src import db, stats
from src.report_flow import CITIES, VISA_TYPES, parse_date

router = Router()
router.message.filter(F.chat.type == "private")


def my_forecast_kb(city: str, visa: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔮 Посчитать мой прогноз", callback_data=f"mgo:{city}:{visa}")]
        ]
    )


async def _send_charts(message: Message, s, label: str) -> None:
    paths = stats.charts_for(s, label)
    if not paths:
        return
    try:
        if len(paths) == 1:
            await message.answer_photo(FSInputFile(paths[0]))
        else:
            media = [InputMediaPhoto(media=FSInputFile(p)) for p in paths]
            await message.answer_media_group(media)
    finally:
        for p in paths:
            os.unlink(p)


async def _send_stats(message: Message, city: str, visa: str) -> None:
    label = VISA_TYPES[visa]
    s = stats.collect_cached(city, visa)
    await message.answer(stats.build_text(s, label), reply_markup=my_forecast_kb(city, visa))
    await _send_charts(message, s, label)


@router.message(CommandStart(deep_link=True, magic=F.args == "menu_stats"))
async def stats_menu_deeplink(message: Message, command: CommandObject, state: FSMContext) -> None:
    await state.clear()
    await cmd_stats(message)


@router.message(CommandStart(deep_link=True, magic=F.args == "menu_my"))
async def my_menu_deeplink(message: Message, command: CommandObject, state: FSMContext) -> None:
    await state.clear()
    await cmd_my(message, state)


@router.message(CommandStart(deep_link=True, magic=F.args.startswith("s_")))
async def stats_deeplink(message: Message, command: CommandObject, state: FSMContext) -> None:
    """Кнопка «Статистика» из темы группы: сразу показать сводку по городу/категории."""
    await state.clear()
    parts = (command.args or "").split("_", 2)
    if len(parts) == 3 and parts[1].isdigit() and int(parts[1]) < len(CITIES) and parts[2] in VISA_TYPES:
        await _send_stats(message, CITIES[int(parts[1])], parts[2])
    else:
        await message.answer("Не понял ссылку. Статистика по городам — /stats")


class MyForecast(StatesGroup):
    queue_date = State()


def _city_kb(prefix: str) -> InlineKeyboardMarkup:
    rows, row = [], []
    for city in CITIES:
        row.append(InlineKeyboardButton(text=city, callback_data=f"{prefix}city:{city}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _visa_kb(prefix: str, city: str) -> InlineKeyboardMarkup:
    from src.report_flow import topic_id

    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"{prefix}visa:{city}:{key}")]
        for key, label in VISA_TYPES.items()
        if topic_id(city, key)
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{prefix}back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------- /stats ----------

@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    await message.answer("Статистика какого города вас интересует?", reply_markup=_city_kb("s"))


@router.callback_query(F.data == "sback")
async def stats_back(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Статистика какого города вас интересует?", reply_markup=_city_kb("s")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("scity:"))
async def stats_pick_city(callback: CallbackQuery) -> None:
    city = callback.data.split(":", 1)[1]
    if city not in CITIES:
        await callback.answer("Неизвестный город", show_alert=True)
        return
    await callback.message.edit_text(
        f"Город: <b>{city}</b>\n\nКакой тип визы?", reply_markup=_visa_kb("s", city)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("svisa:"))
async def stats_pick_visa(callback: CallbackQuery) -> None:
    _, city, visa = callback.data.split(":", 2)
    if city not in CITIES or visa not in VISA_TYPES:
        await callback.answer("Неизвестная комбинация", show_alert=True)
        return
    label = VISA_TYPES[visa]
    s = stats.collect_cached(city, visa)
    await callback.message.edit_text(stats.build_text(s, label), reply_markup=my_forecast_kb(city, visa))
    await _send_charts(callback.message, s, label)
    await callback.answer()


# перехват "s_"/"m_"-диплинков должен произойти раньше общего /start в report_flow:
# stats_router подключён в диспетчере первым (см. main.py)


async def _ask_my_date(message: Message, state: FSMContext, city: str, visa: str) -> None:
    await state.set_state(MyForecast.queue_date)
    await state.update_data(my_city=city, my_visa=visa)
    await message.answer(
        f"Город: <b>{city}</b>, тип визы: <b>{VISA_TYPES[visa]}</b>\n\n"
        "Когда вы встали в очередь? Введите дату в формате <b>ДД.ММ.ГГГГ</b>"
    )


def _report_choice_kb(rows, action: str) -> InlineKeyboardMarkup:
    """Список анкет пользователя для выбора (мульти-режим): action = 'myr' | 'nearr'."""
    kb = []
    for r in rows:
        lbl = f"{r['label']} · " if r["label"] else ""
        tail = "" if not r["letter_date"] else " ✉️"
        kb.append([InlineKeyboardButton(
            text=f"{lbl}{r['city']}, {VISA_TYPES[r['visa_type']].split('(')[0].strip()}{tail}",
            callback_data=f"{action}:{r['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=kb)


async def _forecast_entry(message: Message, state: FSMContext, user_id: int,
                          city: str | None = None, visa: str | None = None) -> None:
    """Вход в «Мой прогноз»: 0 анкет → ручной ввод; 1 → сразу; >1 (мульти) → выбор."""
    from src.report_flow import MULTI_REPORTS

    rows = db.reports_by_user(user_id) if MULTI_REPORTS else (
        [db.find_latest(user_id)] if db.find_latest(user_id) else []
    )
    rows = [r for r in rows if r]
    if not rows:
        if city and visa:
            await _ask_my_date(message, state, city, visa)
        else:
            await message.answer(
                "Персональный прогноз. В каком городе вы становились в очередь?",
                reply_markup=_city_kb("m"),
            )
        return
    if len(rows) == 1:
        await _forecast_from_report(message, rows[0])
        return
    await message.answer(
        "У вас несколько анкет. По какой посчитать прогноз?",
        reply_markup=_report_choice_kb(rows, "myr"),
    )


@router.callback_query(F.data.startswith("myr:"))
async def my_report_pick(callback: CallbackQuery) -> None:
    rid = int(callback.data.split(":", 1)[1])
    row = db.get_report(rid)
    if row is None or row["user_id"] != callback.from_user.id:
        await callback.answer("Анкета не найдена", show_alert=True)
        return
    await _forecast_from_report(callback.message, row)
    await callback.answer()


async def _my_prefilled(message: Message, state: FSMContext, user_id: int, city: str, visa: str) -> None:
    """Общий вход для кнопок «Мой прогноз» (из тем/под /stats)."""
    await _forecast_entry(message, state, user_id, city, visa)


@router.message(CommandStart(deep_link=True, magic=F.args.startswith("m_")))
async def my_deeplink(message: Message, command: CommandObject, state: FSMContext) -> None:
    """Кнопка «Мой прогноз» из темы группы: город и тип уже известны."""
    await state.clear()
    parts = (command.args or "").split("_", 2)
    if len(parts) == 3 and parts[1].isdigit() and int(parts[1]) < len(CITIES) and parts[2] in VISA_TYPES:
        await _my_prefilled(message, state, message.from_user.id, CITIES[int(parts[1])], parts[2])
    else:
        await message.answer("Не понял ссылку. Персональный прогноз — /my")


@router.callback_query(F.data.startswith("mgo:"))
async def my_from_stats(callback: CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Посчитать мой прогноз» под выдачей /stats."""
    _, city, visa = callback.data.split(":", 2)
    if city not in CITIES or visa not in VISA_TYPES:
        await callback.answer("Неизвестная комбинация", show_alert=True)
        return
    await state.clear()
    await _my_prefilled(callback.message, state, callback.from_user.id, city, visa)
    await callback.answer()


# ---------- /my ----------

def _manual_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Люди рядом", callback_data="near")],
            [InlineKeyboardButton(text="✍️ Посчитать для другой даты", callback_data="mmanual")],
        ]
    )


async def _forecast_from_report(message: Message, row) -> None:
    """Прогноз (или факт) по данным анкеты пользователя, без вопросов."""
    city, visa = row["city"], row["visa_type"]
    qd = datetime.strptime(row["queue_date"], "%Y-%m-%d").date()
    qt = row["queue_time"]
    when = qd.strftime("%d.%m.%Y") + (f" в {qt}" if qt else "")
    if row["letter_date"]:
        ld = datetime.strptime(row["letter_date"], "%Y-%m-%d").date()
        waited = (ld - qd).days
        await message.answer(
            f"📌 По вашей анкете ({city}, {VISA_TYPES[visa]}) письмо уже пришло 🎉\n"
            f"Встали в очередь: <b>{when}</b>\n"
            f"Письмо получено: <b>{ld.strftime('%d.%m.%Y')}</b>\n"
            f"Ожидание составило: <b>{waited} дн.</b>",
            reply_markup=_manual_kb(),
        )
        return
    s = stats.collect_cached(city, visa)
    text = (
        f"📌 Данные взяты из вашей анкеты: в очереди с <b>{when}</b>\n\n"
        + stats.build_personal_forecast(s, VISA_TYPES[visa], qd, queue_time=qt)
    )
    await message.answer(text, reply_markup=_manual_kb())


@router.message(Command("my"))
async def cmd_my(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _forecast_entry(message, state, message.from_user.id)


@router.callback_query(F.data == "mmanual")
async def my_manual(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(
        "Персональный прогноз. В каком городе вы становились в очередь?",
        reply_markup=_city_kb("m"),
    )
    await callback.answer()


@router.callback_query(F.data == "mback")
async def my_back(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "Персональный прогноз. В каком городе вы становились в очередь?",
        reply_markup=_city_kb("m"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mcity:"))
async def my_pick_city(callback: CallbackQuery) -> None:
    city = callback.data.split(":", 1)[1]
    if city not in CITIES:
        await callback.answer("Неизвестный город", show_alert=True)
        return
    await callback.message.edit_text(
        f"Город: <b>{city}</b>\n\nКакой тип визы?", reply_markup=_visa_kb("m", city)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mvisa:"))
async def my_pick_visa(callback: CallbackQuery, state: FSMContext) -> None:
    _, city, visa = callback.data.split(":", 2)
    if city not in CITIES or visa not in VISA_TYPES:
        await callback.answer("Неизвестная комбинация", show_alert=True)
        return
    await state.set_state(MyForecast.queue_date)
    await state.update_data(my_city=city, my_visa=visa)
    await callback.message.edit_text(
        f"Город: <b>{city}</b>, тип визы: <b>{VISA_TYPES[visa]}</b>\n\n"
        "Когда вы встали в очередь? Введите дату в формате <b>ДД.ММ.ГГГГ</b>"
    )
    await callback.answer()


@router.message(MyForecast.queue_date, F.text)
async def my_input_date(message: Message, state: FSMContext) -> None:
    from datetime import date

    d = parse_date(message.text)
    if d is None:
        await message.answer("Не понял дату. Формат: ДД.ММ.ГГГГ, например 15.03.2026")
        return
    if d > date.today():
        await message.answer("Дата в будущем — проверьте и введите ещё раз.")
        return
    data = await state.get_data()
    city, visa = data["my_city"], data["my_visa"]
    s = stats.collect_cached(city, visa)
    await message.answer(stats.build_personal_forecast(s, VISA_TYPES[visa], d))
    await state.clear()
