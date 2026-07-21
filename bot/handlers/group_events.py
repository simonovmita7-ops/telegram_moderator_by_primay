"""
События группы: добавление бота, новые участники.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import ContextTypes

from bot.database import get_db
from bot.models import LogEventType
from bot.services.logging_service import LoggingService
from bot.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


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

        # Уведомляем добавившего в ЛС
        if owner_id:
            try:
                await context.bot.send_message(
                    user.id,
                    f"✅ Бот подключён к группе «{chat.title}».\n"
                    f"Вы назначены владельцем.\n"
                    f"Откройте /start → Мои группы для настройки.",
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
