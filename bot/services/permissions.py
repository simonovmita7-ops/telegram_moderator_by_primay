"""
Сервис проверки прав доступа к управлению группой.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.constants import ChatMemberStatus

from bot.models import AdminRole, Group, GroupAdmin


@dataclass(frozen=True, slots=True)
class AccessResult:
    """Результат проверки доступа."""

    allowed: bool
    is_owner: bool
    is_bot_admin: bool
    is_telegram_admin: bool
    reason: str = ""


class PermissionService:
    """Проверка прав владельца, назначенных админов и Telegram-админов."""

    async def get_group_by_telegram_id(
        self, session: AsyncSession, telegram_id: int
    ) -> Group | None:
        result = await session.execute(select(Group).where(Group.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def is_bot_admin(
        self, session: AsyncSession, group_db_id: int, user_telegram_id: int
    ) -> tuple[bool, bool]:
        """
        Проверить, является ли пользователь админом бота.
        Возвращает (is_admin, is_owner).
        """
        group = await session.get(Group, group_db_id)
        if group is None:
            return False, False

        if group.owner_id == user_telegram_id:
            return True, True

        result = await session.execute(
            select(GroupAdmin).where(
                GroupAdmin.group_id == group_db_id,
                GroupAdmin.telegram_user_id == user_telegram_id,
            )
        )
        admin = result.scalar_one_or_none()
        if admin is not None:
            return True, admin.role == AdminRole.OWNER

        return False, False

    async def check_panel_access(
        self,
        session: AsyncSession,
        bot: Bot,
        group_telegram_id: int,
        user_telegram_id: int,
    ) -> AccessResult:
        """
        Полная проверка доступа к панели группы:
        1. Группа зарегистрирована в боте
        2. Пользователь состоит в группе
        3. Пользователь — Telegram-админ или владелец/админ бота
        """
        group = await self.get_group_by_telegram_id(session, group_telegram_id)
        if group is None:
            return AccessResult(False, False, False, False, "Группа не найдена в боте")

        # Проверяем членство и статус в Telegram
        try:
            member = await bot.get_chat_member(group_telegram_id, user_telegram_id)
        except Exception:
            return AccessResult(False, False, False, False, "Не удалось проверить членство")

        if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            return AccessResult(False, False, False, False, "Вы не состоите в группе")

        is_tg_admin = member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

        is_bot_admin, is_owner = await self.is_bot_admin(session, group.id, user_telegram_id)

        # Владелец бота или назначенный админ
        if is_bot_admin:
            return AccessResult(True, is_owner, True, is_tg_admin, "")

        # Telegram-админ при первом добавлении может стать владельцем
        if is_tg_admin and group.owner_id is None:
            group.owner_id = user_telegram_id
            await session.flush()
            return AccessResult(True, True, True, True, "")

        if is_tg_admin and group.owner_id == user_telegram_id:
            return AccessResult(True, True, True, True, "")

        return AccessResult(
            False, False, False, is_tg_admin, "Нет прав управления этой группой"
        )

    async def get_manageable_groups(
        self, session: AsyncSession, user_telegram_id: int
    ) -> list[Group]:
        """Список групп, которыми пользователь может управлять."""
        # Группы, где пользователь — owner
        owned = await session.execute(
            select(Group).where(Group.owner_id == user_telegram_id, Group.is_active.is_(True))
        )
        groups = list(owned.scalars().all())

        # Группы, где назначен админом
        admin_rows = await session.execute(
            select(Group)
            .join(GroupAdmin, GroupAdmin.group_id == Group.id)
            .where(GroupAdmin.telegram_user_id == user_telegram_id, Group.is_active.is_(True))
        )
        for g in admin_rows.scalars().all():
            if g not in groups:
                groups.append(g)

        return groups

    async def can_change_critical_settings(
        self, session: AsyncSession, group_db_id: int, user_telegram_id: int
    ) -> bool:
        """Только владелец может менять критические настройки."""
        _, is_owner = await self.is_bot_admin(session, group_db_id, user_telegram_id)
        return is_owner

    async def add_admin(
        self,
        session: AsyncSession,
        group_db_id: int,
        admin_telegram_id: int,
        added_by: int,
    ) -> GroupAdmin:
        """Добавить администратора группы."""
        admin = GroupAdmin(
            group_id=group_db_id,
            telegram_user_id=admin_telegram_id,
            role=AdminRole.ADMIN,
            added_by=added_by,
        )
        session.add(admin)
        await session.flush()
        return admin

    async def remove_admin(
        self, session: AsyncSession, group_db_id: int, admin_telegram_id: int
    ) -> bool:
        result = await session.execute(
            select(GroupAdmin).where(
                GroupAdmin.group_id == group_db_id,
                GroupAdmin.telegram_user_id == admin_telegram_id,
            )
        )
        admin = result.scalar_one_or_none()
        if admin is None:
            return False
        await session.delete(admin)
        return True

    async def transfer_ownership(
        self, session: AsyncSession, group_db_id: int, new_owner_id: int
    ) -> None:
        group = await session.get(Group, group_db_id)
        if group is None:
            raise ValueError("Группа не найдена")
        old_owner = group.owner_id
        group.owner_id = new_owner_id

        # Убираем нового владельца из таблицы admins, если был
        await self.remove_admin(session, group_db_id, new_owner_id)

        # Старый владелец становится обычным админом
        if old_owner and old_owner != new_owner_id:
            await self.add_admin(session, group_db_id, old_owner, new_owner_id)
