"""
Основной сервис модерации: анализ сообщений, применение наказаний.
Работает строго по правила.txt, без встроенной чувствительности.
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Any
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import ChatPermissions, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from bot.ai_moderator import AiModerator, AiModerationResult
from bot.config import Settings
from bot.models import (
    AiDecision, Ban, ChatMessageCache, Group, Kick, LogEventType,
    Mute, PunishmentType, Violation, ViolationCategory, Warning,
)
from bot.services.logging_service import LoggingService
from bot.services.punishment import PunishmentDecision, PunishmentService
from bot.services.settings_service import SettingsService
from bot.services.spam_detector import SpamDetector

logger = logging.getLogger(__name__)


class ModerationService:
    def __init__(self, settings, ai, punishment, settings_service,
                 logging_service, spam_detector, rules_loader=None):
        self._settings = settings
        self._ai = ai
        self._punishment = punishment
        self._settings_service = settings_service
        self._logging = logging_service
        self._spam = spam_detector
        self._rules_loader = rules_loader  # RulesLoader instance

    def get_rules_text(self, gs=None) -> str:
        """Получить актуальный текст правил. Если у группы есть кастомные правила, вернуть их, иначе вернуть глобальные."""
        if gs and gs.rules_text:
            return gs.rules_text
        if self._rules_loader:
            return self._rules_loader.get_rules()
        return ""

    async def cache_message(self, session, group_db_id, user_id, username, text, message_id, max_cache=50):
        entry = ChatMessageCache(
            group_id=group_db_id, user_telegram_id=user_id,
            username=username, text=text[:2000], message_id=message_id)
        session.add(entry)
        await session.flush()
        subq = (select(ChatMessageCache.id)
                .where(ChatMessageCache.group_id == group_db_id)
                .order_by(ChatMessageCache.created_at.desc()).offset(max_cache))
        old_ids = (await session.execute(subq)).scalars().all()
        if old_ids:
            await session.execute(delete(ChatMessageCache).where(ChatMessageCache.id.in_(old_ids)))

    async def get_context_messages(self, session, group_db_id, limit=20):
        result = await session.execute(
            select(ChatMessageCache).where(ChatMessageCache.group_id == group_db_id)
            .order_by(ChatMessageCache.created_at.desc()).limit(limit))
        rows = list(reversed(result.scalars().all()))
        return [f"@{r.username or r.user_telegram_id}: {r.text}" for r in rows]

    async def get_violation_history(self, session, group_db_id, user_id, limit=10):
        result = await session.execute(
            select(Violation).where(
                Violation.group_id == group_db_id,
                Violation.user_telegram_id == user_id)
            .order_by(Violation.created_at.desc()).limit(limit))
        return [f"{v.category.value} — {v.reason} ({v.created_at:%d.%m.%Y})"
                for v in result.scalars().all()]

    async def process_message(self, update, context, session, group, text,
                               message_id, user_id, username, is_poll=False,
                               poll_question="", poll_options=None,
                               is_sticker=False, is_gif=False,
                               media_group_id=None):
        gs = await self._settings_service.get_or_create(session, group.id)
        await self.cache_message(session, group.id, user_id, username, text, message_id)

        # Проверка запрещённых слов (немедленная реакция)
        banned_check = self._spam.check_banned_words(
            text, gs.banned_words or [], gs.exception_words or [])
        if banned_check.is_spam:
            decision = await self._punishment.decide(
                session, group.id, user_id, "spam", 3,
                "mute", gs.auto_ban_enabled)
            if decision:
                message = update.effective_message
                if message:
                    try:
                        await context.bot.delete_message(group.telegram_id, message_id)
                    except Exception:
                        pass
                await self._apply_punishment(
                    context.bot, session, group, gs, user_id, decision,
                    ViolationCategory.SPAM, banned_check.reason, message_id)
            return

        # Спам-детектор
        spam_check = self._spam.check(
            group.id, user_id, text,
            gs.spam_message_limit, gs.spam_window_seconds,
            is_sticker=is_sticker, is_gif=is_gif,
            media_group_id=media_group_id)
        if spam_check.is_spam:
            decision = await self._punishment.decide(
                session, group.id, user_id, "spam", 2,
                "mute", gs.auto_ban_enabled)
            if decision:
                message = update.effective_message
                if message:
                    try:
                        await context.bot.delete_message(group.telegram_id, message_id)
                    except Exception:
                        pass
                await self._apply_punishment(
                    context.bot, session, group, gs, user_id, decision,
                    ViolationCategory.SPAM, spam_check.reason, message_id)
            return

        # ИИ-модерация (если включена)
        if not gs.ai_enabled:
            return

        rules_text = self.get_rules_text(gs)
        context_msgs = await self.get_context_messages(session, group.id, self._settings.ai_context_messages)
        violation_history = await self.get_violation_history(session, group.id, user_id)

        ai_result = await self._ai.analyze(
            message_text=text,
            context_messages=context_msgs,
            violation_history=violation_history,
            rules_text=rules_text,
            banned_words=gs.banned_words or [],
            exception_words=gs.exception_words or [],
            is_poll=is_poll,
            poll_question=poll_question,
            poll_options=poll_options,
            provider=getattr(gs, "ai_provider", "gemini") or "gemini"
        )

        # Сохраняем решение ИИ
        ai_dec = AiDecision(
            group_id=group.id, user_telegram_id=user_id, message_id=message_id,
            message_text=text[:1000], violation=ai_result.violation,
            category=ai_result.category, severity=ai_result.severity,
            reason=ai_result.reason, recommended_action=ai_result.recommended_action,
            raw_response=ai_result.raw_response)
        session.add(ai_dec)

        if not ai_result.violation:
            return

        # Проверяем включено ли правило
        enabled_rules = gs.enabled_rules or {}
        if ai_result.category in enabled_rules and not enabled_rules[ai_result.category]:
            return

        decision = await self._punishment.decide(
            session, group.id, user_id, ai_result.category, ai_result.severity,
            ai_result.recommended_action, gs.auto_ban_enabled)

        if decision is None:
            return

        try:
            cat = ViolationCategory(ai_result.category)
        except ValueError:
            cat = ViolationCategory.NONE

        if decision.delete_message:
            try:
                await context.bot.delete_message(group.telegram_id, message_id)
            except Exception:
                pass

        await self._apply_punishment(
            context.bot, session, group, gs, user_id, decision, cat, ai_result.reason, message_id)

    async def _apply_punishment(self, bot, session, group, gs, user_id,
                                decision, category, reason, message_id=None):
        violation = Violation(
            group_id=group.id, user_telegram_id=user_id, message_id=message_id,
            category=category, severity=3, reason=reason,
            punishment_applied=decision.punishment_type)
        session.add(violation)
        await session.flush()

        issued_by = None
        if decision.punishment_type == PunishmentType.WARNING:
            await self._issue_warning(bot, session, group, gs, user_id, reason,
                                      decision.next_on_repeat, violation.id, issued_by)
        elif decision.punishment_type == PunishmentType.MUTE:
            await self._issue_mute(bot, session, group, gs, user_id, reason,
                                   decision.duration_seconds or gs.default_mute_duration, issued_by)
        elif decision.punishment_type == PunishmentType.KICK:
            await self._issue_kick(bot, session, group, gs, user_id, reason,
                                   decision.duration_seconds or gs.default_kick_duration, issued_by)
        elif decision.punishment_type == PunishmentType.BAN:
            await self._issue_ban(bot, session, group, gs, user_id, reason,
                                  decision.duration_seconds, issued_by)

    async def _issue_warning(self, bot, session, group, gs, user_id, reason,
                             next_punishment, violation_id, issued_by):
        chat_id = group.telegram_id
        text = (f"⚠️ <b>Предупреждение</b>\n"
                f"Пользователь ID {user_id}\n"
                f"Причина: {reason}\n"
                f"Следующее нарушение: {next_punishment}")
        try:
            msg = await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML)
            try:
                await bot.pin_chat_message(chat_id, msg.message_id, disable_notification=True)
            except Exception:
                pass
            expires = datetime.utcnow() + timedelta(seconds=gs.warning_pin_duration)
            warning = Warning(
                group_id=group.id, user_telegram_id=user_id, violation_id=violation_id,
                category="warning", reason=reason, next_punishment=next_punishment,
                chat_message_id=msg.message_id, expires_at=expires)
            session.add(warning)
        except Exception as exc:
            logger.error("Ошибка предупреждения: %s", exc)

    async def _issue_mute(self, bot, session, group, gs, user_id, reason, duration, issued_by):
        chat_id = group.telegram_id
        until = datetime.utcnow() + timedelta(seconds=duration)
        permissions = ChatPermissions(can_send_messages=False)
        try:
            await bot.restrict_chat_member(chat_id, user_id, permissions, until_date=until)
        except Exception as exc:
            logger.error("Ошибка мута: %s", exc); return
        mute = Mute(group_id=group.id, user_telegram_id=user_id, reason=reason,
                    duration_seconds=duration, expires_at=until, is_active=True, issued_by=issued_by)
        session.add(mute)
        try:
            await bot.send_message(chat_id,
                f"🔇 Пользователь ID {user_id} замучен на {duration // 3600}ч. Причина: {reason}")
        except Exception:
            pass

    async def _issue_kick(self, bot, session, group, gs, user_id, reason, duration, issued_by):
        chat_id = group.telegram_id
        until = datetime.utcnow() + timedelta(seconds=duration)
        try:
            await bot.ban_chat_member(chat_id, user_id, until_date=until)
        except Exception as exc:
            logger.error("Ошибка кика: %s", exc); return
        kick = Kick(group_id=group.id, user_telegram_id=user_id, reason=reason,
                    duration_seconds=duration, expires_at=until, is_active=True, issued_by=issued_by)
        session.add(kick)
        try:
            await bot.send_message(chat_id,
                f"🚪 Пользователь ID {user_id} исключён на {duration // 3600}ч. Причина: {reason}")
        except Exception:
            pass

    async def _issue_ban(self, bot, session, group, gs, user_id, reason, duration, issued_by):
        chat_id = group.telegram_id
        is_permanent = duration is None
        until = None if is_permanent else datetime.utcnow() + timedelta(seconds=duration)
        try:
            await bot.ban_chat_member(chat_id, user_id, until_date=until)
        except Exception as exc:
            logger.error("Ошибка бана: %s", exc); return
        ban = Ban(group_id=group.id, user_telegram_id=user_id, reason=reason,
                  is_permanent=is_permanent, expires_at=until, is_active=True, issued_by=issued_by)
        session.add(ban)
        ban_type = "навсегда" if is_permanent else f"на {duration // 3600}ч"
        try:
            await bot.send_message(chat_id,
                f"⛔ Пользователь ID {user_id} забанен {ban_type}. Причина: {reason}")
        except Exception:
            pass
