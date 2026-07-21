"""
События группы: добавление бота, новые участники.
"""

from __future__ import annotations

import logging
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import ContextTypes

from bot.database import get_db
from bot.models import LogEventType
from bot.services.logging_service import LoggingService
from bot.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


async def check_rules_delayed(bot, db, settings_svc, chat_id, chat_title) -> None:
    # Ожидание 15 минут
    await asyncio.sleep(900)
    try:
        async with db.session() as session:
            from bot.services.permissions import PermissionService
            perm = PermissionService()
            group = await perm.get_group_by_telegram_id(session, chat_id)
            if not group or not group.is_active:
                return
            gs = await settings_svc.get_or_create(session, group.id)
            has_rules = gs.rules_text is not None and len(gs.rules_text.strip()) > 0

        if not has_rules:
            await bot.send_message(
                chat_id,
                "⚠️ В настройках не добавлены правила."
            )
        else:
            await bot.send_message(
                chat_id,
                "✅ Правила подключены."
            )
    except Exception as e:
        logger.warning(f"Ошибка отложенной проверки правил для группы {chat_title}: {e}")


async def my_chat_member_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Обработка добавления/удаления бота из группы.
    При добавлении администратором — назначаем owner_id.
    """
    if update.my_chat_member is None:
        return

    chat_member = update.my_chat_member
    chat = chat_member.chat
    user = chat_member.from_user

    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    new_status = chat_member.new_chat_member.status
    old_status = chat_member.old_chat_member.status

    db = get_db()
    settings_svc = SettingsService()
    log_svc: LoggingService = context.bot_data["logging_service"]

    # Бота добавили в группу
    if old_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED) and new_status in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
    ):
        owner_id = None
        try:
            member = await context.bot.get_chat_member(chat.id, user.id)
            if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
                owner_id = user.id
        except Exception as exc:
            logger.warning("Не удалось проверить админа: %s", exc)

        async with db.session() as session:
            group = await settings_svc.register_group(
                session,
                telegram_id=chat.id,
                title=chat.title or "Группа",
                owner_id=owner_id,
            )
            await log_svc.log(
                session,
                LogEventType.SYSTEM,
                f"Бот добавлен в группу «{chat.title}»",
                group_id=group.id,
                actor_telegram_id=user.id,
            )

        # Запуск отложенной проверки правил (15 минут) в фоне
        asyncio.create_task(check_rules_delayed(context.bot, db, settings_svc, chat.id, chat.title))

        # Уведомляем добавившего в ЛС
        if owner_id:
            try:
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ Добавить правила", callback_data=f"gs:{chat.id}:rules_txt_set")]
                ])
                await context.bot.send_message(
                    user.id,
                    f"✅ Бот подключён к группе «{chat.title}».\n"
                    f"Вы назначены владельцем.\n"
                    f"Пожалуйста, добавьте правила для группы:",
                    reply_markup=kb,
                )
            except Exception:
                pass
        else:
            try:
                await context.bot.send_message(
                    user.id,
                    f"⚠️ Бот добавлен в «{chat.title}», но вы не администратор.\n"
                    f"Управление доступно только администраторам группы.",
                )
            except Exception:
                pass

    # Бота удалили
    elif new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
        async with db.session() as session:
            from bot.services.permissions import PermissionService
            perm = PermissionService()
            group = await perm.get_group_by_telegram_id(session, chat.id)
            if group:
                group.is_active = False
                await log_svc.log(
                    session,
                    LogEventType.SYSTEM,
                    f"Бот удалён из группы «{chat.title}»",
                    group_id=group.id,
                )
