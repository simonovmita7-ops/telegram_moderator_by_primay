"""
Обработчик /start и главного меню в ЛС.
"""
from __future__ import annotations
import logging
import re
from typing import Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot, WebAppInfo, MenuButtonWebApp
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from bot.database import get_db
from bot.keyboards.main_menu import back_to_main_keyboard, main_menu_keyboard, main_menu_reply_keyboard
from bot.services.permissions import PermissionService

logger = logging.getLogger(__name__)

START_WELCOME_TEXT = (
    "👋 <b>Telegram-бот модератор</b>\n\n"
    "Я автоматически модерирую группы по правилам, установленным через Mini App или команду /RulesAdd.\n\n"
    "Изучите инструкции перед использованием бота или перейдите в Главное меню."
)

def start_welcome_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Открыть инструкции", web_app=WebAppInfo(url="https://docs-style.vercel.app"))],
        [InlineKeyboardButton("⚙️ Главное меню", callback_data="menu:main")]
    ])

WELCOME_TEXT = (
    "👋 <b>Telegram-бот модератор</b>\n\n"
    "Я автоматически модерирую группы по правилам, установленным через <b>Mini App</b> или команду <code>/RulesAdd</code>.\n\n"
    "Добавьте меня в группу и назначьте администратором.\n\n"
    "Управление — только через это меню:"
)

HELP_TEXT = (
    "<b>❓ Помощь</b>\n\n"
    "<b>Как подключить:</b>\n"
    "1. Добавьте бота в группу\n"
    "2. Назначьте администратором\n"
    "3. Откройте «Мои группы» здесь\n\n"
    "<b>Команны в ЛС с ботом:</b>\n"
    "/RulesAdd — задать индивидуальные правила для группы\n"
    "/addword слово — добавить запрещённое слово\n"
    "/delword слово — удалить запрещённое слово\n"
    "/addexc слово — добавить слово-исключение\n"
    "/delexc слово — удалить слово-исключение\n\n"
    "<b>Правила:</b>\n"
    "Настройте индивидуальные правила через Mini App или команду <code>/RulesAdd</code>.\n\n"
    "<b>Наказания:</b>\n"
    "Предупреждения → муты → кики"
)


async def rulesadd_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None or update.effective_user is None: return
    user_id = update.effective_user.id
    db = get_db(); perm = PermissionService()
    async with db.session() as session:
        groups = await perm.get_manageable_groups(session, user_id)
    if not groups:
        await update.effective_message.reply_text(
            "📋 У вас пока нет групп. Добавьте бота в группу в качестве администратора."
        )
        return
    
    group_tuples = [(g.telegram_id, g.title) for g in groups]
    rows = [
        [InlineKeyboardButton(title[:40], callback_data=f"gs:{tg_id}:rules_txt_set")]
        for tg_id, title in group_tuples
    ]
    rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="menu:main")])
    await update.effective_message.reply_text(
        "📝 <b>Установка правил</b>\n\nВыберите группу для настройки правил:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows)
    )


def parse_channel_username_or_id(link: str) -> str | int | None:
    link = link.strip()
    if link.startswith("@"):
        return link
    if link.startswith("-100") and link[4:].isdigit():
        return int(link)
    if link.isdigit():
        return int(link)
    # URL parsing
    match = re.search(r'(?:t\.me|telegram\.me)/(?:\+|(?:joinchat/))', link)
    if match:
        return None
    match = re.search(r'(?:t\.me|telegram\.me|telegram\.dog)/([a-zA-Z0-9_]{5,})', link)
    if match:
        return f"@{match.group(1)}"
    return None


async def is_user_subscribed(bot: Bot, user_id: int, channel_link: str) -> bool:
    target = parse_channel_username_or_id(channel_link)
    if target is None:
        logger.warning(f"Не удалось извлечь имя канала из ссылки '{channel_link}'. Проверка пропускается.")
        return True
    try:
        member = await bot.get_chat_member(target, user_id)
        from telegram.constants import ChatMemberStatus
        return member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except BadRequest as e:
        logger.error(f"Ошибка проверки подписки в {target}: {e}")
        return True
    except Exception as e:
        logger.error(f"Неожиданная ошибка проверки подписки: {e}")
        return True


def subscription_check_keyboard(channel_link: str) -> InlineKeyboardMarkup:
    url = channel_link
    if channel_link.startswith("@"):
        url = f"https://t.me/{channel_link[1:]}"
    elif not (channel_link.startswith("http://") or channel_link.startswith("https://")):
        url = f"https://t.me/c/{channel_link.replace('-100', '')}" if channel_link.startswith("-100") else "https://t.me"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Подписаться на канал", url=url)],
        [InlineKeyboardButton("🔍 Проверить подписку", callback_data="menu:check_sub")]
    ])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None or update.effective_user is None: return
    user_id = update.effective_user.id
    settings = context.bot_data.get("settings")
    ch = settings.subscription_channel if settings else None

    if ch:
        subscribed = await is_user_subscribed(context.bot, user_id, ch)
        if not subscribed:
            await update.effective_message.reply_text(
                "📢 <b>Доступ ограничен</b>\n\nДля использования бота вам необходимо подписаться на наш канал.",
                parse_mode="HTML",
                reply_markup=subscription_check_keyboard(ch)
            )
            return

    db = get_db()
    async with db.session() as session:
        from bot.models import UserStartStatus
        status = await session.get(UserStartStatus, user_id)
        first_completed = status.first_start_completed if status else False

    # Нативно регистрируем кнопку Mini App у поля ввода (Chat Menu Button)
    try:
        await context.bot.set_chat_menu_button(
            chat_id=user_id,
            menu_button=MenuButtonWebApp(
                text="📱 Mini App",
                web_app=WebAppInfo(url="https://telegram-moderator-by-primay.vercel.app/")
            )
        )
    except Exception as e:
        logger.error(f"Не удалось установить кнопку меню: {e}")

    if first_completed:
        await update.effective_message.reply_text(
            WELCOME_TEXT, parse_mode="HTML", reply_markup=main_menu_keyboard()
        )
    else:
        await update.effective_message.reply_text(
            START_WELCOME_TEXT, parse_mode="HTML", reply_markup=start_welcome_keyboard()
        )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None: return
    data = query.data
    
    if data != "menu:check_sub":
        await query.answer()

    if data == "menu:main":
        user_id = query.from_user.id
        db = get_db()
        async with db.session() as session:
            from bot.models import UserStartStatus
            status = await session.get(UserStartStatus, user_id)
            if not status:
                status = UserStartStatus(user_telegram_id=user_id, first_start_completed=True)
                session.add(status)
            else:
                status.first_start_completed = True
            await session.commit()
            
        await query.edit_message_text(WELCOME_TEXT, parse_mode="HTML", reply_markup=main_menu_keyboard())
    elif data == "menu:help":
        await query.edit_message_text(HELP_TEXT, parse_mode="HTML", reply_markup=back_to_main_keyboard())
    elif data == "menu:check_sub":
        user_id = query.from_user.id
        settings = context.bot_data.get("settings")
        ch = settings.subscription_channel if settings else None
        if ch:
            subscribed = await is_user_subscribed(context.bot, user_id, ch)
            if not subscribed:
                await query.answer("❌ Вы всё ещё не подписаны на канал!", show_alert=True)
                return
        await query.answer("✅ Подписка подтверждена!")
        
        db = get_db()
        async with db.session() as session:
            from bot.models import UserStartStatus
            status = await session.get(UserStartStatus, user_id)
            first_completed = status.first_start_completed if status else False
            
        if first_completed:
            await query.edit_message_text(WELCOME_TEXT, parse_mode="HTML", reply_markup=main_menu_keyboard())
        else:
            await query.edit_message_text(START_WELCOME_TEXT, parse_mode="HTML", reply_markup=start_welcome_keyboard())
    elif data == "menu:settings":
        settings = context.bot_data.get("settings")
        ch = settings.subscription_channel if settings else None
        status = f"Текущий канал: <code>{ch}</code>" if ch else "Канал не задан"
        text = (
            "⚙️ <b>Глобальные настройки бота</b>\n\n"
            f"<b>Обязательная подписка:</b>\n{status}\n\n"
            "Канал подписки задается в файле <code>.env</code> (переменная <code>SUBSCRIPTION_CHANNEL</code>).\n"
            "Пользователи должны быть подписаны на этот канал, чтобы пользоваться ботом."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Главное меню", callback_data="menu:main")]
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    elif data == "menu:stats":
        await _show_global_stats(query, context)
    elif data == "menu:logs":
        await _show_global_logs(query, context)
    elif data == "menu:groups":
        from bot.handlers.group_panel import show_groups_list
        await show_groups_list(update, context)


async def _show_global_stats(query: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
    from sqlalchemy import func, select
    from bot.models import Ban, Group, Kick, Mute, Violation, Warning
    user_id = query.from_user.id
    db = get_db()
    async with db.session() as session:
        from bot.services.permissions import PermissionService
        perm = PermissionService()
        groups = await perm.get_manageable_groups(session, user_id)
        if not groups:
            await query.edit_message_text("📊 Нет групп для статистики.", reply_markup=back_to_main_keyboard()); return
        group_ids = [g.id for g in groups]
        violations = await session.scalar(select(func.count(Violation.id)).where(Violation.group_id.in_(group_ids)))
        warnings = await session.scalar(select(func.count(Warning.id)).where(Warning.group_id.in_(group_ids)))
        mutes = await session.scalar(select(func.count(Mute.id)).where(Mute.group_id.in_(group_ids)))
        kicks = await session.scalar(select(func.count(Kick.id)).where(Kick.group_id.in_(group_ids)))
        bans = await session.scalar(select(func.count(Ban.id)).where(Ban.group_id.in_(group_ids)))
    text = (f"📊 <b>Статистика</b> ({len(groups)} групп)\n\n"
            f"Нарушений: {violations or 0}\nПредупреждений: {warnings or 0}\n"
            f"Мутов: {mutes or 0}\nКиков: {kicks or 0}\nБанов: {bans or 0}")
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_to_main_keyboard())


async def _show_global_logs(query: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
    from sqlalchemy import select
    from bot.models import LogEntry
    user_id = query.from_user.id
    db = get_db()
    async with db.session() as session:
        from bot.services.permissions import PermissionService
        perm = PermissionService()
        groups = await perm.get_manageable_groups(session, user_id)
        if not groups:
            await query.edit_message_text("📜 Нет логов.", reply_markup=back_to_main_keyboard()); return
        group_ids = [g.id for g in groups]
        result = await session.execute(
            select(LogEntry).where(LogEntry.group_id.in_(group_ids))
            .order_by(LogEntry.created_at.desc()).limit(15))
        logs = result.scalars().all()
    lines = ["📜 <b>Последние логи</b>\n"]
    for log in logs:
        lines.append(f"• [{log.event_type.value}] {log.message[:60]} ({log.created_at:%d.%m %H:%M})")
    if len(lines) == 1: lines.append("(пусто)")
    await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=back_to_main_keyboard())
