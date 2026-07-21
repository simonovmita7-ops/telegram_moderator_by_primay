"""
Сервис наказаний: определение санкции по категории и истории нарушений.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import PunishmentType, Violation, ViolationCategory


@dataclass(frozen=True, slots=True)
class PunishmentDecision:
    """Решение о наказании."""

    punishment_type: PunishmentType
    duration_seconds: int | None  # None для default duration / warning
    reason: str
    next_on_repeat: str
    delete_message: bool = True
    instant: bool = False  # мгновенный кик без эскалации


# Длительности наказаний в секундах
ONE_HOUR = 3600
THREE_HOURS = 10800
ONE_DAY = 86400
TWO_DAYS = 172800
THREE_DAYS = 259200


class PunishmentService:
    """Определяет наказание по правилам и считает повторные нарушения."""

    async def count_category_violations(
        self,
        session: AsyncSession,
        group_db_id: int,
        user_telegram_id: int,
        category: ViolationCategory,
    ) -> int:
        """Количество предыдущих нарушений данной категории."""
        result = await session.execute(
            select(func.count(Violation.id)).where(
                Violation.group_id == group_db_id,
                Violation.user_telegram_id == user_telegram_id,
                Violation.category == category,
            )
        )
        return int(result.scalar_one())

    async def decide(
        self,
        session: AsyncSession,
        group_db_id: int,
        user_telegram_id: int,
        category: str,
        severity: int,
        ai_action: str,
        auto_ban_enabled: bool = True,
    ) -> PunishmentDecision | None:
        """
        Определить наказание по категории и номеру нарушения.
        """
        try:
            cat = ViolationCategory(category)
        except ValueError:
            cat = ViolationCategory.NONE

        if cat == ViolationCategory.NONE:
            return None

        count = await self.count_category_violations(
            session, group_db_id, user_telegram_id, cat
        )
        offense_num = count + 1  # текущее — следующее по счёту

        # Угрозы и тяжёлые нарушения — мгновенный кик
        if cat in (ViolationCategory.THREAT, ViolationCategory.VIOLENCE):
            return PunishmentDecision(
                punishment_type=PunishmentType.KICK,
                duration_seconds=None,
                reason=f"Тяжёлое нарушение: {cat.value}",
                next_on_repeat="—",
                instant=True,
            )

        if severity >= 5 and auto_ban_enabled:
            return PunishmentDecision(
                punishment_type=PunishmentType.KICK,
                duration_seconds=None,
                reason=f"Критическая severity={severity}",
                next_on_repeat="—",
                instant=True,
            )

        return self._normal_decision(cat, offense_num, ai_action)

    def _normal_decision(
        self, cat: ViolationCategory, offense_num: int, ai_action: str
    ) -> PunishmentDecision:
        """Стандартные правила наказаний из ТЗ."""

        if cat == ViolationCategory.FAMILY_INSULT:
            if offense_num == 1:
                return PunishmentDecision(
                    PunishmentType.KICK, ONE_DAY,
                    "Оскорбление семьи", "Повтор → кик 3 дня",
                )
            return PunishmentDecision(
                PunishmentType.KICK, THREE_DAYS,
                "Повторное оскорбление семьи", "Повтор → кик",
            )

        if cat == ViolationCategory.SPAM:
            if offense_num == 1:
                return PunishmentDecision(
                    PunishmentType.WARNING, None,
                    "Спам", "Повтор → мут 3 часа",
                )
            if offense_num == 2:
                return PunishmentDecision(
                    PunishmentType.MUTE, THREE_HOURS,
                    "Повторный спам", "Следующее → кик 3 часа",
                )
            return PunishmentDecision(
                PunishmentType.KICK, THREE_HOURS,
                "Систематический спам", "Следующее → кик",
            )

        if cat == ViolationCategory.ADULT:
            if offense_num == 1:
                return PunishmentDecision(
                    PunishmentType.WARNING, None,
                    "18+ контент", "Повтор → кик 2 дня",
                )
            return PunishmentDecision(
                PunishmentType.KICK, TWO_DAYS,
                "Повторный 18+ контент", "Следующее → кик",
            )

        if cat == ViolationCategory.STICKER_ABUSE:
            if offense_num == 1:
                return PunishmentDecision(
                    PunishmentType.WARNING, None,
                    "Медиа без согласия", "Продолжение → кик 1 день",
                )
            return PunishmentDecision(
                PunishmentType.KICK, ONE_DAY,
                "Медиа без согласия после предупреждения", "Следующее → кик",
            )

        if cat == ViolationCategory.CONFLICT:
            if offense_num == 1:
                return PunishmentDecision(
                    PunishmentType.WARNING, None,
                    "Провокация конфликта", "Повтор → мут 1 день",
                )
            return PunishmentDecision(
                PunishmentType.MUTE, ONE_DAY,
                "Повторная провокация", "Следующее → кик",
            )

        if cat == ViolationCategory.LEAK:
            return PunishmentDecision(
                PunishmentType.KICK, THREE_DAYS,
                "Слив переписки", "Повтор → кик",
            )

        if cat == ViolationCategory.POLL_ABUSE:
            if offense_num == 1:
                return PunishmentDecision(
                    PunishmentType.MUTE, ONE_DAY,
                    "Провокационный опрос", "Повтор → кик 2 дня",
                )
            return PunishmentDecision(
                PunishmentType.KICK, TWO_DAYS,
                "Повторное нарушение через опрос", "Следующее → кик",
            )

        # insult, advertisement, и прочие — по рекомендации ИИ с дефолтом
        action_map = {
            "warning": PunishmentType.WARNING,
            "mute": PunishmentType.MUTE,
            "kick": PunishmentType.KICK,
            "ban": PunishmentType.KICK,
        }
        ptype = action_map.get(ai_action, PunishmentType.WARNING)

        durations = {
            PunishmentType.MUTE: ONE_DAY,
            PunishmentType.KICK: ONE_DAY,
            PunishmentType.WARNING: None,
        }
        return PunishmentDecision(
            punishment_type=ptype,
            duration_seconds=durations.get(ptype),
            reason=f"Нарушение: {cat.value}",
            next_on_repeat="Эскалация по правилам",
        )

    @staticmethod
    def expires_at(duration_seconds: int | None) -> datetime | None:
        if duration_seconds is None:
            return None
        return datetime.utcnow() + timedelta(seconds=duration_seconds)
