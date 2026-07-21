"""
Панель управления группой (callback-обработчики).
Включает: настройки, запрещённые слова, исключения.
"""
from __future__ import annotations
import logging
from typing import Any
from sqlalchemy import func, select
from telegram import Update
from telegram.ext import ContextTypes
from bot.database import get_db
from bot.keyboards.group_panel import (
    admins_keyboard, ai_settings_keyboard, group_panel_keyboard,
    rules_toggle_keyboard, settings_keyboard, warning_pin_keyboard,
)
from bot.keyboards.main_menu import back_to_main_keyboard, groups_list_keyboard
from bot.models import Ban, GroupAdmin, Kick, LogEntry, LogEventType, Mute, Violation, Warning
from bot.services.logging_service import LoggingService
from bot.services.permissions import PermissionService
from bot.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


async def show_groups_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    message = update.effective_message
    user = update.effective_user
    if user is None: return
    db = get_db(); perm = PermissionService()
    async with db.session() as session:
        groups = await perm.get_manageable_groups(session, user.id)
    if not groups:
        text = "📋 У вас пока нет групп.\n\nДобавьте бота в группу как администратора."
        kb = back_to_main_keyboard()
        if query: await query.edit_message_text(text, reply_markup=kb)
        elif message: await message.reply_text(text, reply_markup=kb)
        return
    group_tuples = [(g.telegram_id, g.title) for g in groups]
    text = "📋 <b>Мои группы</b>\n\nВыберите группу для управления:"
    kb = groups_list_keyboard(group_tuples)
    if query:
        await query.answer()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    elif message:
        await message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.from_user is None: return
    await query.answer()
    data = query.data
    if data.startswith("group:"):
        await _open_group_panel(query, context, int(data.split(":")[1]))
    elif data.startswith("gp:"):
        parts = data.split(":")
        await _group_panel_action(query, context, int(parts[1]), parts[2])
    elif data.startswith("gs:"):
        await _settings_action(query, context, data)
    elif data.startswith("ga:"):
        await _admins_action(query, context, data)


async def _open_group_panel(query, context, group_tg_id):
    db = get_db(); perm = PermissionService()
    async with db.session() as session:
        access = await perm.check_panel_access(session, context.bot, group_tg_id, query.from_user.id)
        if not access.allowed:
            await query.edit_message_text(f"🚫 Доступ запрещён: {access.reason}", reply_markup=back_to_main_keyboard()); return
        group = await perm.get_group_by_telegram_id(session, group_tg_id)
        if group is None: return
        title = group.title
    text = (f"⚙️ <b>{title}</b>\n\nID: <code>{group_tg_id}</code>\n\nВыберите раздел:")
    await query.edit_message_text(text, parse_mode="HTML",
                                  reply_markup=group_panel_keyboard(group_tg_id))


async def _group_panel_action(query, context, group_tg_id, action):
    db = get_db(); perm = PermissionService()
    async with db.session() as session:
        access = await perm.check_panel_access(session, context.bot, group_tg_id, query.from_user.id)
        if not access.allowed:
            await query.edit_message_text(f"🚫 {access.reason}", reply_markup=back_to_main_keyboard()); return
        group = await perm.get_group_by_telegram_id(session, group_tg_id)
        if group is None: return
        gs_service = SettingsService()
        if action == "settings":
            await query.edit_message_text("⚙️ <b>Настройки группы</b>", parse_mode="HTML",
                                           reply_markup=settings_keyboard(group_tg_id))
        elif action == "violators":
            await _show_violators(query, session, group)
        elif action == "history":
            await _show_history(query, session, group)
        elif action == "mutes":
            await _show_punishments(query, session, group, Mute, "🔇 Активные муты")
        elif action == "kicks":
            await _show_punishments(query, session, group, Kick, "🚪 Активные кики")
        elif action == "bans":
            await _show_punishments(query, session, group, Ban, "⛔ Активные баны")
        elif action == "ai":
            gs = await gs_service.get_or_create(session, group.id)
            await query.edit_message_text("🧠 <b>ИИ-модерация</b>\n\nРаботает строго по правила.txt",
                parse_mode="HTML", reply_markup=ai_settings_keyboard(group_tg_id, gs.ai_enabled))
        elif action == "gstats":
            await _show_group_stats(query, session, group)
        elif action == "admins":
            await query.edit_message_text("👮 <b>Администраторы</b>", parse_mode="HTML",
                                          reply_markup=admins_keyboard(group_tg_id, access.is_owner))


async def _show_violators(query, session, group):
    result = await session.execute(
        select(Violation.user_telegram_id, func.count(Violation.id).label("cnt"))
        .where(Violation.group_id == group.id)
        .group_by(Violation.user_telegram_id).order_by(func.count(Violation.id).desc()).limit(10))
    rows = result.all()
    lines = ["👥 <b>Топ нарушителей</b>\n"]
    for row in rows:
        lines.append(f"• ID {row.user_telegram_id}: {row.cnt} нарушений")
    if len(lines) == 1: lines.append("(пусто)")
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=group_panel_keyboard(group.telegram_id))


async def _show_history(query, session, group):
    result = await session.execute(
        select(Violation).where(Violation.group_id == group.id)
        .order_by(Violation.created_at.desc()).limit(15))
    violations = result.scalars().all()
    lines = ["📜 <b>История нарушений</b>\n"]
    for v in violations:
        lines.append(f"• {v.created_at:%d.%m %H:%M} — ID{v.user_telegram_id} [{v.category.value}] {v.reason[:40]}")
    if len(lines) == 1: lines.append("(пусто)")
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=group_panel_keyboard(group.telegram_id))


async def _show_punishments(query, session, group, model, title):
    result = await session.execute(
        select(model).where(model.group_id == group.id, model.is_active.is_(True))
        .order_by(model.created_at.desc()).limit(15))
    items = result.scalars().all()
    lines = [f"<b>{title}</b>\n"]
    for item in items:
        exp = getattr(item, "expires_at", None)
        exp_str = exp.strftime("%d.%m %H:%M") if exp else "∞"
        lines.append(f"• ID {item.user_telegram_id}: {item.reason[:30]} до {exp_str}")
    if len(items) == 0: lines.append("(нет активных)")
    await query.edit_message_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=group_panel_keyboard(group.telegram_id))


async def _show_group_stats(query, session, group):
    v = await session.scalar(select(func.count(Violation.id)).where(Violation.group_id == group.id))
    w = await session.scalar(select(func.count(Warning.id)).where(Warning.group_id == group.id))
    m = await session.scalar(select(func.count(Mute.id)).where(Mute.group_id == group.id))
    text = (f"📊 <b>Статистика: {group.title}</b>\n\nНарушений: {v or 0}\n"
            f"Предупреждений: {w or 0}\nМутов: {m or 0}")
    await query.edit_message_text(text, parse_mode="HTML",
                                  reply_markup=group_panel_keyboard(group.telegram_id))


async def _settings_action(query, context, data):
    parts = data.split(":")
    group_tg_id = int(parts[1]); action = parts[2]
    db = get_db(); perm = PermissionService(); gs_service = SettingsService()
    async with db.session() as session:
        access = await perm.check_panel_access(session, context.bot, group_tg_id, query.from_user.id)
        if not access.allowed:
            await query.answer("Нет доступа", show_alert=True); return
        group = await perm.get_group_by_telegram_id(session, group_tg_id)
        if group is None: return
        gs = await gs_service.get_or_create(session, group.id)

        if action == "ai_toggle":
            gs.ai_enabled = not gs.ai_enabled
            await query.edit_message_text(f"🧠 ИИ: {'включён' if gs.ai_enabled else 'выключен'}\n\nРаботает по правила.txt",
                reply_markup=ai_settings_keyboard(group_tg_id, gs.ai_enabled))
        elif action == "spam_limit":
            gs.spam_message_limit = 10 if gs.spam_message_limit == 15 else 15
            await query.answer(f"Лимит спама: {gs.spam_message_limit}")
        elif action == "autoban":
            if not access.is_owner:
                await query.answer("Только владелец", show_alert=True); return
            gs.auto_ban_enabled = not gs.auto_ban_enabled
            await query.answer(f"Автобан: {'ON' if gs.auto_ban_enabled else 'OFF'}")
        elif action == "logmode":
            modes = ["full", "minimal", "off"]
            idx = modes.index(gs.logging_mode) if gs.logging_mode in modes else 0
            gs.logging_mode = modes[(idx + 1) % 3]
            await query.answer(f"Логи: {gs.logging_mode}")
        elif action == "pin_dur":
            await query.edit_message_text("📌 Время закрепления предупреждений:",
                reply_markup=warning_pin_keyboard(group_tg_id))
        elif action == "pin" and len(parts) > 3:
            gs.warning_pin_duration = int(parts[3])
            await query.answer(f"Закрепление: {gs.warning_pin_duration // 3600}ч")
        elif action == "rules":
            rules = gs.enabled_rules or {}
            has_custom = gs.rules_text is not None and len(gs.rules_text.strip()) > 0
            await query.edit_message_text("📋 Правила (нажмите для переключения):",
                reply_markup=rules_toggle_keyboard(group_tg_id, rules, has_custom))
        elif action == "rules_txt_set":
            context.user_data["awaiting_rules_text"] = group_tg_id
            await query.edit_message_text(
                "📝 <b>Установка индивидуальных правил для группы</b>\n\n"
                "Отправьте боту текст правил чата. Бот запишет эти правила специально для данной группы, и ИИ будет модерировать чат строго по ним.\n\n"
                "Для разметки вы можете использовать стандартную нумерацию, например:\n"
                "<code>1. Оскорбления\nЗапрещено оскорблять...\n2. Спам\nЗапрещено отправлять спам...</code>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data=f"gs:{group_tg_id}:rules")]]))
        elif action == "rules_txt_clear":
            gs.rules_text = None
            await session.flush()
            await query.answer("Текст правил сброшен к правилам по умолчанию (правила.txt)")
            gs = await gs_service.get_or_create(session, group.id)
            rules = gs.enabled_rules or {}
            await query.edit_message_text("📋 Правила (нажмите для переключения):",
                reply_markup=rules_toggle_keyboard(group_tg_id, rules, False))
        elif action == "rule" and len(parts) > 3:
            rule = parts[3]
            new_val = await gs_service.toggle_rule(session, group.id, rule)
            await query.answer(f"{rule}: {'ON' if new_val else 'OFF'}")
            gs = await gs_service.get_or_create(session, group.id)
            has_custom = gs.rules_text is not None and len(gs.rules_text.strip()) > 0
            await query.edit_message_text("📋 Правила:",
                reply_markup=rules_toggle_keyboard(group_tg_id, gs.enabled_rules or {}, has_custom))
        elif action == "banned_words":
            words = gs.banned_words or []
            words_text = "\n".join(f"• {w}" for w in words) if words else "(список пуст)"
            await query.edit_message_text(
                f"🚫 <b>Запрещённые слова</b> (немедленная реакция)\n\n{words_text}\n\n"
                f"Добавить: /addword слово\nУдалить: /delword слово",
                parse_mode="HTML", reply_markup=settings_keyboard(group_tg_id))
        elif action == "exception_words":
            words = gs.exception_words or []
            words_text = "\n".join(f"• {w}" for w in words) if words else "(список пуст)"
            await query.edit_message_text(
                f"✅ <b>Слова-исключения</b> (бот не реагирует)\n\n{words_text}\n\n"
                f"Добавить: /addexc слово\nУдалить: /delexc слово",
                parse_mode="HTML", reply_markup=settings_keyboard(group_tg_id))
        elif action in ("mute_dur", "kick_dur"):
            field = "default_mute_duration" if action == "mute_dur" else "default_kick_duration"
            current = getattr(gs, field)
            new_val = 3600 if current >= 86400 else current * 2
            setattr(gs, field, new_val)
            await query.answer(f"{'Мут' if 'mute' in action else 'Кик'}: {new_val // 3600}ч")


async def _admins_action(query, context, data):
    parts = data.split(":"); group_tg_id = int(parts[1]); action = parts[2]
    db = get_db(); perm = PermissionService()
    async with db.session() as session:
        access = await perm.check_panel_access(session, context.bot, group_tg_id, query.from_user.id)
        if not access.allowed:
            await query.answer("Нет доступа", show_alert=True); return
        group = await perm.get_group_by_telegram_id(session, group_tg_id)
        if group is None: return
        if action == "list":
            result = await session.execute(select(GroupAdmin).where(GroupAdmin.group_id == group.id))
            admins = result.scalars().all()
            lines = [f"👮 Админы группы «{group.title}»\n", f"👑 Владелец: {group.owner_id}"]
            for a in admins:
                lines.append(f"• {a.telegram_user_id} ({a.role.value})")
            await query.edit_message_text("\n".join(lines), reply_markup=admins_keyboard(group_tg_id, access.is_owner))
        elif action == "add":
            if not access.is_owner:
                await query.answer("Только владелец", show_alert=True); return
            context.user_data["awaiting_admin_add"] = group_tg_id
            await query.edit_message_text("➕ Отправьте Telegram ID нового администратора:",
                reply_markup=admins_keyboard(group_tg_id, True))
        elif action == "remove":
            if not access.is_owner:
                await query.answer("Только владелец", show_alert=True); return
            context.user_data["awaiting_admin_remove"] = group_tg_id
            await query.edit_message_text("➖ Отправьте Telegram ID администратора для удаления:",
                reply_markup=admins_keyboard(group_tg_id, True))
        elif action == "transfer":
            if not access.is_owner:
                await query.answer("Только владелец", show_alert=True); return
            context.user_data["awaiting_owner_transfer"] = group_tg_id
            await query.edit_message_text("👑 Отправьте Telegram ID нового владельца:",
                reply_markup=admins_keyboard(group_tg_id, True))


async def admin_id_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None or update.effective_user is None: return
    if not update.effective_message.text: return
    text = update.effective_message.text.strip()
    user_id = update.effective_user.id
    db = get_db(); perm = PermissionService(); gs_svc = SettingsService()

    # Ожидание текста правил для группы
    rules_group = context.user_data.pop("awaiting_rules_text", None)
    if rules_group:
        async with db.session() as session:
            group = await perm.get_group_by_telegram_id(session, rules_group)
            if group:
                await gs_svc.set_custom_rules_text(session, group.id, text)
                await update.effective_message.reply_text(
                    f"✅ Индивидуальные правила для группы «{group.title}» успешно сохранены.\n"
                    "Они вступают в силу немедленно."
                )
        return

    if not text.isdigit(): return
    target_id = int(text)
    for key, handler in [
        ("awaiting_admin_add", _do_add_admin),
        ("awaiting_admin_remove", _do_remove_admin),
        ("awaiting_owner_transfer", _do_transfer_owner),
    ]:
        group_tg_id = context.user_data.pop(key, None)
        if group_tg_id:
            await handler(update, context, group_tg_id, target_id, user_id)
            return


async def _do_add_admin(update, context, group_tg_id, target_id, user_id):
    db = get_db(); perm = PermissionService()
    async with db.session() as session:
        group = await perm.get_group_by_telegram_id(session, group_tg_id)
        if group and group.owner_id == user_id:
            await perm.add_admin(session, group.id, target_id, user_id)
            await update.effective_message.reply_text(f"✅ Админ {target_id} добавлен.")


async def _do_remove_admin(update, context, group_tg_id, target_id, user_id):
    db = get_db(); perm = PermissionService()
    async with db.session() as session:
        group = await perm.get_group_by_telegram_id(session, group_tg_id)
        if group and group.owner_id == user_id:
            ok = await perm.remove_admin(session, group.id, target_id)
            await update.effective_message.reply_text(f"✅ Удалён." if ok else "❌ Не найден.")


async def _do_transfer_owner(update, context, group_tg_id, target_id, user_id):
    db = get_db(); perm = PermissionService()
    async with db.session() as session:
        group = await perm.get_group_by_telegram_id(session, group_tg_id)
        if group and group.owner_id == user_id:
            await perm.transfer_ownership(session, group.id, target_id)
            await update.effective_message.reply_text(f"👑 Владение передано {target_id}.")
