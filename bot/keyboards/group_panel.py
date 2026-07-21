"""
Клавиатуры панели управления группой.
"""
from __future__ import annotations
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from bot.services.settings_service import WARNING_PIN_OPTIONS


def group_panel_keyboard(group_telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Настройки", callback_data=f"gp:{group_telegram_id}:settings")],
        [InlineKeyboardButton("👥 Нарушители", callback_data=f"gp:{group_telegram_id}:violators"),
         InlineKeyboardButton("📜 История", callback_data=f"gp:{group_telegram_id}:history")],
        [InlineKeyboardButton("🔇 Муты", callback_data=f"gp:{group_telegram_id}:mutes"),
         InlineKeyboardButton("🚪 Кики", callback_data=f"gp:{group_telegram_id}:kicks")],
        [InlineKeyboardButton("🧠 ИИ-модерация", callback_data=f"gp:{group_telegram_id}:ai"),
         InlineKeyboardButton("📊 Статистика", callback_data=f"gp:{group_telegram_id}:gstats")],
        [InlineKeyboardButton("👮 Администраторы", callback_data=f"gp:{group_telegram_id}:admins")],
        [InlineKeyboardButton("◀️ Мои группы", callback_data="menu:groups")],
    ])


def settings_keyboard(group_telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱ Время мутов", callback_data=f"gs:{group_telegram_id}:mute_dur")],
        [InlineKeyboardButton("⏱ Время киков", callback_data=f"gs:{group_telegram_id}:kick_dur")],
        [InlineKeyboardButton("📨 Лимит спама", callback_data=f"gs:{group_telegram_id}:spam_limit")],
        [InlineKeyboardButton("🚫 Запрещённые слова", callback_data=f"gs:{group_telegram_id}:banned_words")],
        [InlineKeyboardButton("✅ Слова-исключения", callback_data=f"gs:{group_telegram_id}:exception_words")],
        [InlineKeyboardButton("📋 Правила вкл/выкл", callback_data=f"gs:{group_telegram_id}:rules")],
        [InlineKeyboardButton("⛔ Автобан", callback_data=f"gs:{group_telegram_id}:autoban")],
        [InlineKeyboardButton("📝 Режим логирования", callback_data=f"gs:{group_telegram_id}:logmode")],
        [InlineKeyboardButton("📌 Время закрепления", callback_data=f"gs:{group_telegram_id}:pin_dur")],
        [InlineKeyboardButton("◀️ Панель группы", callback_data=f"group:{group_telegram_id}")],
    ])


def warning_pin_keyboard(group_telegram_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"gs:{group_telegram_id}:pin:{seconds}")]
        for label, seconds in WARNING_PIN_OPTIONS.items()
    ]
    rows.append([InlineKeyboardButton("◀️ Настройки", callback_data=f"gp:{group_telegram_id}:settings")])
    return InlineKeyboardMarkup(rows)


def ai_settings_keyboard(group_telegram_id: int, ai_enabled: bool) -> InlineKeyboardMarkup:
    toggle = "✅ ИИ включён" if ai_enabled else "❌ ИИ выключен"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle, callback_data=f"gs:{group_telegram_id}:ai_toggle")],
        [InlineKeyboardButton("◀️ Панель группы", callback_data=f"group:{group_telegram_id}")],
    ])


def admins_keyboard(group_telegram_id: int, is_owner: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("📋 Список админов", callback_data=f"ga:{group_telegram_id}:list")]]
    if is_owner:
        rows.append([
            InlineKeyboardButton("➕ Добавить", callback_data=f"ga:{group_telegram_id}:add"),
            InlineKeyboardButton("➖ Удалить", callback_data=f"ga:{group_telegram_id}:remove"),
        ])
        rows.append([InlineKeyboardButton("👑 Передать владение", callback_data=f"ga:{group_telegram_id}:transfer")])
    rows.append([InlineKeyboardButton("◀️ Панель группы", callback_data=f"group:{group_telegram_id}")])
    return InlineKeyboardMarkup(rows)


def rules_toggle_keyboard(group_telegram_id: int, enabled_rules: dict, has_custom_rules: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for rule, enabled in sorted(enabled_rules.items()):
        icon = "✅" if enabled else "❌"
        rows.append([InlineKeyboardButton(
            f"{icon} {rule}", callback_data=f"gs:{group_telegram_id}:rule:{rule}")])
    
    label = "✏️ Изменить текст правил" if not has_custom_rules else "✏️ Изменить текст правил (установлен кастомный)"
    rows.append([InlineKeyboardButton(label, callback_data=f"gs:{group_telegram_id}:rules_txt_set")])
    if has_custom_rules:
        rows.append([InlineKeyboardButton("🗑 Сбросить текст к дефолту", callback_data=f"gs:{group_telegram_id}:rules_txt_clear")])
        
    rows.append([InlineKeyboardButton("◀️ Настройки", callback_data=f"gp:{group_telegram_id}:settings")])
    return InlineKeyboardMarkup(rows)
