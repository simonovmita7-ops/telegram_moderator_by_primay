"""
Планировщик фоновых задач: восстановление мутов, киков, предупреждений после перезапуска.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from telegram.ext import Application

from bot.database import get_db
from bot.models import Ban, Kick, Mute, Warning

logger = logging.getLogger(__name__)

# Интервал проверки истекающих наказаний (секунды)
CHECK_INTERVAL = 30


class SchedulerService:
    """Фоновый планировщик для автоматического снятия наказаний."""

    def __init__(self, application: Application) -> None:
        self._app = application
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._last_status_update: float | None = None

    async def start(self) -> None:
        """Запустить планировщик и восстановить просроченные задачи."""
        self._running = True
        await self._restore_on_startup()
        self._task = asyncio.create_task(self._loop(), name="scheduler_loop")
        logger.info("Планировщик запущен")

    async def stop(self) -> None:
        """Остановить планировщик."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Планировщик остановлен")

    async def _restore_on_startup(self) -> None:
        """
        После перезапуска выполнить все просроченные действия сразу
        и восстановить активные таймеры.
        """
        db = get_db()
        moderation = self._app.bot_data.get("moderation_service")
        if moderation is None:
            return

        bot = self._app.bot
        now = datetime.utcnow()

        async with db.session() as session:
            # Просроченные предупреждения
            warnings = await session.execute(
                select(Warning).where(
                    Warning.is_active.is_(True),
                    Warning.expires_at.isnot(None),
                    Warning.expires_at <= now,
                )
            )
            for w in warnings.scalars().all():
                await moderation.expire_warning(bot, session, w)
                logger.info("Восстановлено: снято предупреждение id=%s", w.id)

            # Активные предупреждения (ещё не истекли) — ничего не делаем, loop обработает

            # Просроченные муты
            mutes = await session.execute(
                select(Mute).where(
                    Mute.is_active.is_(True),
                    Mute.expires_at <= now,
                )
            )
            for m in mutes.scalars().all():
                await moderation.expire_mute(bot, session, m)
                logger.info("Восстановлено: снят мут id=%s", m.id)

            # Просроченные кики
            kicks = await session.execute(
                select(Kick).where(
                    Kick.is_active.is_(True),
                    Kick.expires_at <= now,
                )
            )
            for k in kicks.scalars().all():
                await moderation.expire_kick(bot, session, k)
                logger.info("Восстановлено: обработан кик id=%s", k.id)

            # Просроченные баны
            bans = await session.execute(
                select(Ban).where(
                    Ban.is_active.is_(True),
                    Ban.is_permanent.is_(False),
                    Ban.expires_at.isnot(None),
                    Ban.expires_at <= now,
                )
            )
            for b in bans.scalars().all():
                await moderation.expire_ban(bot, session, b)
                logger.info("Восстановлено: снят бан id=%s", b.id)

        logger.info("Восстановление задач после перезапуска завершено")

    async def _loop(self) -> None:
        """Периодически проверять истекающие наказания."""
        while self._running:
            try:
                await self._check_expired()
                
                # Периодическое обновление статуса (раз в 5 минут / 300 секунд)
                now_time = asyncio.get_event_loop().time()
                if self._last_status_update is None or now_time - self._last_status_update >= 300:
                    self._last_status_update = now_time
                    await self._update_status()
            except Exception as exc:
                logger.exception("Ошибка в планировщике: %s", exc)
            await asyncio.sleep(CHECK_INTERVAL)

    async def _update_status(self) -> None:
        try:
            settings = self._app.bot_data.get("settings")
            if settings:
                from bot.services.status_service import update_bot_status
                await update_bot_status(self._app.bot, settings, True)
        except Exception as e:
            logger.error("Ошибка при периодическом обновлении статуса бота: %s", e)

    async def _check_expired(self) -> None:
        """Проверить и обработать все истекшие наказания."""
        db = get_db()
        moderation = self._app.bot_data.get("moderation_service")
        if moderation is None:
            return

        bot = self._app.bot
        now = datetime.utcnow()

        async with db.session() as session:
            # Предупреждения
            result = await session.execute(
                select(Warning).where(
                    Warning.is_active.is_(True),
                    Warning.expires_at.isnot(None),
                    Warning.expires_at <= now,
                )
            )
            for w in result.scalars().all():
                await moderation.expire_warning(bot, session, w)

            # Муты
            result = await session.execute(
                select(Mute).where(
                    Mute.is_active.is_(True),
                    Mute.expires_at <= now,
                )
            )
            for m in result.scalars().all():
                await moderation.expire_mute(bot, session, m)

            # Кики
            result = await session.execute(
                select(Kick).where(
                    Kick.is_active.is_(True),
                    Kick.expires_at <= now,
                )
            )
            for k in result.scalars().all():
                await moderation.expire_kick(bot, session, k)

            # Баны
            result = await session.execute(
                select(Ban).where(
                    Ban.is_active.is_(True),
                    Ban.is_permanent.is_(False),
                    Ban.expires_at.isnot(None),
                    Ban.expires_at <= now,
                )
            )
            for b in result.scalars().all():
                await moderation.expire_ban(bot, session, b)
