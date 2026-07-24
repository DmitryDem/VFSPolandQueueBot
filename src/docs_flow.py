"""Справочник «Документы и цены» (/docs).

Пока доступен только владельцу (контент на вычитке); после проверки
достаточно убрать проверку _owner_only, чтобы открыть всем.
Контент — config/faq.json (правится без изменения кода).
"""
import json
import os
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

router = Router()

FAQ_PATH = Path(__file__).resolve().parent.parent / "config" / "faq.json"

MENU = [
    ("D_OTHER", "📄 Нац. виза D — документы"),
    ("D_WORK", "📄 D (работа)"),
    ("D_DRIVER", "📄 D (водители)"),
    ("C_OTHER", "📄 Шенген C"),
    ("PHOTO", "📷 Требования к фото"),
    ("FEES", "💰 Сборы"),
    ("SERVICES", "🧾 Доп. услуги"),
    ("TERMS", "⏱ Сроки и порядок"),
]


def _faq() -> dict:
    return json.loads(FAQ_PATH.read_text("utf-8"))


def _owner_only(user_id: int) -> bool:
    admin = os.environ.get("ADMIN_CHAT_ID")
    return bool(admin) and user_id == int(admin)


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


def _section_kb(source_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Официальная страница VFS", url=source_url)],
        [InlineKeyboardButton(text="⬅️ К разделам", callback_data="docs:menu")],
    ])


@router.message(Command("docs"), F.chat.type == "private")
async def cmd_docs(message: Message) -> None:
    if not _owner_only(message.from_user.id):
        return  # пока не публично
    await message.answer(
        "📋 <b>Документы и цены — справочник</b>\n"
        "Выберите раздел:",
        reply_markup=_menu_kb(),
    )


@router.callback_query(F.data == "docs:menu")
async def docs_menu(callback: CallbackQuery) -> None:
    if not _owner_only(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.edit_text(
        "📋 <b>Документы и цены — справочник</b>\nВыберите раздел:",
        reply_markup=_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("docs:"))
async def docs_section(callback: CallbackQuery) -> None:
    if not _owner_only(callback.from_user.id):
        await callback.answer()
        return
    key = callback.data.split(":", 1)[1]
    faq = _faq()
    section = faq["sections"].get(key)
    if not section:
        await callback.answer("Раздел не найден", show_alert=True)
        return
    lines = [f"<b>{section['title']}</b>", ""]
    lines += [f"• {item}" for item in section["items"]]
    lines.append("")
    verified = faq.get("verified_date")
    lines.append(
        f"<i>{faq['disclaimer']}"
        + (f" Сверено с сайтом VFS: {verified}." if verified else " ⚠️ Контент на вычитке.")
        + "</i>"
    )
    await callback.message.edit_text(
        "\n".join(lines), reply_markup=_section_kb(faq["source_url"]),
        disable_web_page_preview=True,
    )
    await callback.answer()
