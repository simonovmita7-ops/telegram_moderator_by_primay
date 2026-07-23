"""
Обработка сообщений в группах для модерации.
Команды: /addword, /delword, /addexc, /delexc
"""
from __future__ import annotations
import logging
from typing import Any
from telegram import Message, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes
from bot.database import get_db
from bot.services.permissions import PermissionService
from bot.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


def _extract_message_content(message: Message):
    is_poll = message.poll is not None
    poll_question = ""; poll_options = []; is_sticker = message.sticker is not None; is_gif = message.animation is not None
    if is_poll and message.poll:
        poll_question = message.poll.question
        poll_options = [o.text for o in message.poll.options]
    parts = []
    if message.text: parts.append(message.text)
    if message.caption: parts.append(message.caption)
    if is_poll: parts.append(f"[ОПРОС] {poll_question} | {', '.join(poll_options)}")
    if message.sticker: parts.append("[СТИКЕР]")
    if message.animation: parts.append("[GIF]")
    if message.photo: parts.append("[ФОТО]")
    if message.video: parts.append("[ВИДЕО]")
    if getattr(message, "video_note", None): parts.append("[КРУЖОК / ВИДЕОСООБЩЕНИЕ]")
    if getattr(message, "voice", None): parts.append("[ГОЛОСОВОЕ СООБЩЕНИЕ]")
    if getattr(message, "audio", None): parts.append("[АУДИОФАЙЛ]")
    if message.document: parts.append(f"[ДОКУМЕНТ: {message.document.file_name or ''}]")
    if message.entities:
        for ent in message.entities:
            if ent.type == "url" and message.text: parts.append(message.text[ent.offset:ent.offset + ent.length])
            elif ent.type == "text_link" and ent.url: parts.append(ent.url)
    text = " ".join(parts).strip() or "(медиа без текста)"
    return text, is_poll, poll_question, poll_options, is_sticker, is_gif


import asyncio

async def run_moderation_async(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, message, user) -> None:
    db = get_db(); perm = PermissionService(); moderation = context.bot_data["moderation_service"]
    try:
        async with db.session() as session:
            group = await perm.get_group_by_telegram_id(session, chat_id)
            if group is None or not group.is_active: return
            try:
                member = await context.bot.get_chat_member(chat_id, user.id)
                from telegram.constants import ChatMemberStatus
                if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER): return
            except Exception:
                pass
            text, is_poll, poll_q, poll_opts, is_sticker, is_gif = _extract_message_content(message)
            await moderation.process_message(
                update=update, context=context, session=session, group=group, text=text,
                message_id=message.message_id, user_id=user.id, username=user.username,
                is_poll=is_poll, poll_question=poll_q, poll_options=poll_opts,
                is_sticker=is_sticker, is_gif=is_gif, media_group_id=message.media_group_id)
    except Exception as e:
        logger.error("Ошибка в фоновой модерации: %s", e)


async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message; user = update.effective_user; chat = update.effective_chat
    if message is None or user is None or chat is None: return
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP): return
    if user.is_bot: return
    asyncio.create_task(run_moderation_async(update, context, chat.id, message, user))


async def addword_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None: return
    await update.effective_message.reply_text("В данный момент управление настройками осуществляется через Mini App")


async def delword_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None: return
    await update.effective_message.reply_text("В данный момент управление настройками осуществляется через Mini App")


async def addexc_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None: return
    await update.effective_message.reply_text("В данный момент управление настройками осуществляется через Mini App")


async def delexc_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None: return
    await update.effective_message.reply_text("В данный момент управление настройками осуществляется через Mini App")
