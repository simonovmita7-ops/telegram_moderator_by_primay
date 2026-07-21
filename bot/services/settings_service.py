"""
Сервис настроек группы: создание дефолтов, чтение, обновление.
"""
from __future__ import annotations
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from bot.models import Group, GroupSettings

DEFAULT_ENABLED_RULES: dict[str, bool] = {
    "insult": True, "family_insult": True, "spam": True, "conflict": True,
    "leak": True, "adult": True, "violence": True, "sticker_abuse": True,
    "poll_abuse": True, "threat": True, "advertisement": True,
}

WARNING_PIN_OPTIONS: dict[str, int] = {
    "1 час": 3600, "3 часа": 10800, "6 часов": 21600,
    "12 часов": 43200, "24 часа": 86400,
}


class SettingsService:
    """CRUD для настроек группы."""

    async def get_or_create(self, session: AsyncSession, group_db_id: int) -> GroupSettings:
        result = await session.execute(
            select(GroupSettings).where(GroupSettings.group_id == group_db_id)
        )
        settings = result.scalar_one_or_none()
        if settings is None:
            settings = GroupSettings(
                group_id=group_db_id,
                enabled_rules=dict(DEFAULT_ENABLED_RULES),
                banned_words=[], exception_words=[],
            )
            session.add(settings)
            await session.flush()
        return settings

    async def update_field(self, session, group_db_id, field, value):
        settings = await self.get_or_create(session, group_db_id)
        if not hasattr(settings, field):
            raise ValueError(f"Неизвестное поле настроек: {field}")
        setattr(settings, field, value)
        await session.flush()
        return settings

    async def toggle_rule(self, session, group_db_id, rule):
        settings = await self.get_or_create(session, group_db_id)
        rules = dict(settings.enabled_rules or DEFAULT_ENABLED_RULES)
        rules[rule] = not rules.get(rule, True)
        settings.enabled_rules = rules
        await session.flush()
        return rules[rule]

    async def add_banned_word(self, session, group_db_id, word):
        settings = await self.get_or_create(session, group_db_id)
        words = list(settings.banned_words or [])
        word_lower = word.strip().lower()
        if word_lower and word_lower not in words:
            words.append(word_lower)
        settings.banned_words = words
        await session.flush()
        return words

    async def remove_banned_word(self, session, group_db_id, word):
        settings = await self.get_or_create(session, group_db_id)
        words = [w for w in (settings.banned_words or []) if w != word.strip().lower()]
        settings.banned_words = words
        await session.flush()
        return words

    async def add_exception_word(self, session, group_db_id, word):
        settings = await self.get_or_create(session, group_db_id)
        words = list(settings.exception_words or [])
        word_lower = word.strip().lower()
        if word_lower and word_lower not in words:
            words.append(word_lower)
        settings.exception_words = words
        await session.flush()
        return words

    async def remove_exception_word(self, session, group_db_id, word):
        settings = await self.get_or_create(session, group_db_id)
        words = [w for w in (settings.exception_words or []) if w != word.strip().lower()]
        settings.exception_words = words
        await session.flush()
        return words

    async def set_custom_rules_text(self, session, group_db_id, rules_text):
        settings = await self.get_or_create(session, group_db_id)
        settings.rules_text = rules_text.strip() if rules_text else None
        await session.flush()
        return settings

    async def register_group(self, session, telegram_id, title, owner_id):
        result = await session.execute(select(Group).where(Group.telegram_id == telegram_id))
        group = result.scalar_one_or_none()
        if group is None:
            group = Group(telegram_id=telegram_id, title=title, owner_id=owner_id)
            session.add(group)
            await session.flush()
            await self.get_or_create(session, group.id)
        else:
            group.title = title
            group.is_active = True
            if owner_id and group.owner_id is None:
                group.owner_id = owner_id
            await session.flush()
        return group
