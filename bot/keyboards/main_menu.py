from __future__ import annotations
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Mini App", web_app=WebAppInfo(url="https://telegram-moderator-by-primay.vercel.app/"))],
        [InlineKeyboardButton("📋 Мои группы", callback_data="menu:groups")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="menu:settings")],
        [InlineKeyboardButton("📊 Статистика", callback_data="menu:stats")],
        [InlineKeyboardButton("📜 Логи", callback_data="menu:logs")],
        [InlineKeyboardButton("❓ Помощь", callback_data="menu:help")],
    ])


def back_to_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Главное меню", callback_data="menu:main")]])


def groups_list_keyboard(groups: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(title[:40], callback_data=f"group:{tg_id}")] for tg_id, title in groups]
    rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)
