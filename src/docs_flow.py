"""Справочник «Документы и цены» (/docs) — доступен всем в личке с ботом.

Контент — config/faq.json (правится без изменения кода).
"""
import json
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

router = Router()
router.message.filter(F.chat.type == "private")

FAQ_PATH = Path(__file__).resolve().parent.parent / "config" / "faq.json"

MENU = [
    ("D_BASE", "📄 Нац. D — базовый пакет"),
    ("D_WORK", "📄 D (работа)"),
    ("D_DRIVER", "📄 D (водители)"),
    ("D_STUDENT", "📄 D (учёба)"),
    ("D_KARTA", "📄 D (Карта поляка)"),
    ("D_OTHER", "📄 D (иные цели)"),
    ("C_OTHER", "📄 Шенген C"),
    ("PHOTO", "📷 Требования к фото"),
    ("FEES", "💰 Сборы"),
    ("SERVICES", "🧾 Доп. услуги"),
    ("TERMS", "⏱ Сроки и порядок"),
]

TITLE = "📋 <b>Документы, сборы и порядок подачи</b>\nВыберите раздел:"


def _faq() -> dict:
    return json.loads(FAQ_PATH.read_text("utf-8"))


def _menu_kb() -> InlineKeyboardMarkup:
    rows, row = [], []
    for key, label in MENU:
        row.append(InlineKeyboardButton(text=label, callback_data=f"docs:{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _section_kb(faq: dict, key: str) -> InlineKeyboardMarkup:
    rows = []
    if key in ("FEES", "SERVICES") and faq.get("fee_url"):
        rows.append([InlineKeyboardButton(text="💱 Актуальные сборы (VFS)", url=faq["fee_url"])])
    rows.append([InlineKeyboardButton(text="🌐 Официальная страница VFS", url=faq["source_url"])])
    rows.append([InlineKeyboardButton(text="⬅️ К разделам", callback_data="docs:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("docs"))
async def cmd_docs(message: Message) -> None:
    await message.answer(TITLE, reply_markup=_menu_kb())


@router.message(CommandStart(deep_link=True, magic=F.args == "docs"))
async def docs_deeplink(message: Message, command: CommandObject, state: FSMContext) -> None:
    await state.clear()
    await message.answer(TITLE, reply_markup=_menu_kb())


@router.callback_query(F.data == "docs:menu")
async def docs_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(TITLE, reply_markup=_menu_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("docs:"))
async def docs_section(callback: CallbackQuery) -> None:
    key = callback.data.split(":", 1)[1]
    faq = _faq()
    section = faq["sections"].get(key)
    if not section:
        await callback.answer("Раздел не найден", show_alert=True)
        return
    lines = [f"<b>{section['title']}</b>", ""]
    lines += [f"• {item}" for item in section["items"]]
    await callback.message.edit_text(
        "\n".join(lines), reply_markup=_section_kb(faq, key),
        disable_web_page_preview=True,
    )
    await callback.answer()
