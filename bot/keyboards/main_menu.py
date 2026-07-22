from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton


def main_menu_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Mini App", web_app=WebAppInfo(url="https://telegram-moderator-by-primay.vercel.app/"))]],
        resize_keyboard=True,
        is_persistent=True
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Мои группы", callback_data="menu:groups")],
        [InlineKeyboardButton("📊 Статистика", callback_data="menu:stats")],
        [InlineKeyboardButton("📖 Инструкции", web_app=WebAppInfo(url="https://docs-style.vercel.app"))],
    ])


def back_to_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Главное меню", callback_data="menu:main")]])


def groups_list_keyboard(groups: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(title[:40], callback_data=f"group:{tg_id}")] for tg_id, title in groups]
    rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)
