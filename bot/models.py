"""
SQLAlchemy-модели базы данных.
"""
from __future__ import annotations
import enum
from datetime import datetime
from typing import Any
from sqlalchemy import (
    JSON, BigInteger, Boolean, DateTime, Enum, ForeignKey,
    Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ViolationCategory(str, enum.Enum):
    INSULT = "insult"
    FAMILY_INSULT = "family_insult"
    SPAM = "spam"
    CONFLICT = "conflict"
    LEAK = "leak"
    ADULT = "adult"
    VIOLENCE = "violence"
    STICKER_ABUSE = "sticker_abuse"
    POLL_ABUSE = "poll_abuse"
    THREAT = "threat"
    ADVERTISEMENT = "advertisement"
    NONE = "none"


class RecommendedAction(str, enum.Enum):
    NONE = "none"; WARNING = "warning"; MUTE = "mute"; KICK = "kick"; BAN = "ban"


class PunishmentType(str, enum.Enum):
    WARNING = "warning"; MUTE = "mute"; KICK = "kick"; BAN = "ban"


class AdminRole(str, enum.Enum):
    OWNER = "owner"; ADMIN = "admin"


class LogEventType(str, enum.Enum):
    VIOLATION = "violation"; AI_DECISION = "ai_decision"; WARNING = "warning"
    MUTE = "mute"; KICK = "kick"; BAN = "ban"; ADMIN_ACTION = "admin_action"
    SETTINGS_CHANGE = "settings_change"; EMERGENCY = "emergency"; SYSTEM = "system"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="Без названия")
    owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    admins: Mapped[list[GroupAdmin]] = relationship(back_populates="group", cascade="all, delete-orphan")
    settings: Mapped[GroupSettings | None] = relationship(back_populates="group", uselist=False, cascade="all, delete-orphan")


class GroupAdmin(Base):
    __tablename__ = "group_admins"
    __table_args__ = (UniqueConstraint("group_id", "telegram_user_id", name="uq_group_admin"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    role: Mapped[AdminRole] = mapped_column(Enum(AdminRole), default=AdminRole.ADMIN, nullable=False)
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    group: Mapped[Group] = relationship(back_populates="admins")


class GroupSettings(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), unique=True, nullable=False)
    default_mute_duration: Mapped[int] = mapped_column(Integer, default=3600)
    default_kick_duration: Mapped[int] = mapped_column(Integer, default=86400)
    ai_sensitivity: Mapped[int] = mapped_column(Integer, default=3)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_provider: Mapped[str] = mapped_column(String(32), default="gemini")
    spam_message_limit: Mapped[int] = mapped_column(Integer, default=15)
    spam_window_seconds: Mapped[int] = mapped_column(Integer, default=60)
    banned_words: Mapped[list[str]] = mapped_column(JSON, default=list)
    exception_words: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled_rules: Mapped[dict[str, bool]] = mapped_column(JSON, default=dict)
    auto_ban_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    logging_mode: Mapped[str] = mapped_column(String(32), default="off")
    warning_pin_duration: Mapped[int] = mapped_column(Integer, default=86400)
    # Текст правил группы
    rules_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    group: Mapped[Group] = relationship(back_populates="settings")


class Violation(Base):
    __tablename__ = "violations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    category: Mapped[ViolationCategory] = mapped_column(Enum(ViolationCategory), nullable=False)
    severity: Mapped[int] = mapped_column(Integer, default=1)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    punishment_applied: Mapped[PunishmentType | None] = mapped_column(Enum(PunishmentType), nullable=True)
    ai_recommended_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Warning(Base):
    __tablename__ = "warnings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    violation_id: Mapped[int | None] = mapped_column(ForeignKey("violations.id", ondelete="SET NULL"), nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    next_punishment: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chat_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Mute(Base):
    __tablename__ = "mutes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    issued_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Kick(Base):
    __tablename__ = "kicks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    invite_link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    invite_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    issued_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Ban(Base):
    __tablename__ = "bans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    is_permanent: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    issued_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LogEntry(Base):
    __tablename__ = "logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[LogEventType] = mapped_column(Enum(LogEventType), nullable=False)
    actor_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    target_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AiDecision(Base):
    __tablename__ = "ai_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    violation: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[str] = mapped_column(String(64), default="none")
    severity: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    recommended_action: Mapped[str] = mapped_column(String(32), default="none")
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ChatMessageCache(Base):
    __tablename__ = "chat_message_cache"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DuelRecord(Base):
    __tablename__ = "duel_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    winner_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    winner_name: Mapped[str] = mapped_column(String(255), nullable=False)
    loser_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    loser_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_suicide: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserStartStatus(Base):
    __tablename__ = "user_start_statuses"
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    first_start_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

