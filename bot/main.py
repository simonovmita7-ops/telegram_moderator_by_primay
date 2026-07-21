"""
Точка входа Telegram-бота модератора.
Запуск: python -m bot.main
"""
from __future__ import annotations
import logging, sys
from pathlib import Path
from telegram.ext import (
    Application, CallbackQueryHandler, ChatMemberHandler,
    CommandHandler, MessageHandler, filters,
)
import bot.database as db_module
from bot.ai_moderator import AiModerator
from bot.config import Settings, load_settings, BASE_DIR
from bot.database import Database
from bot.handlers.group_events import my_chat_member_handler
from bot.handlers.group_panel import admin_id_message, group_callback
from bot.handlers.moderation import (
    addword_command, delword_command, addexc_command, delexc_command, group_message_handler
)
from bot.handlers.start import menu_callback, start_command, rulesadd_command
from bot.scheduler.jobs import SchedulerService
from bot.services.logging_service import LoggingService
from bot.services.moderation import ModerationService
from bot.services.punishment import PunishmentService
from bot.services.rules_loader import RulesLoader
from bot.services.settings_service import SettingsService
from bot.services.spam_detector import SpamDetector


def setup_logging(log_level: str, log_file: Path) -> logging.Logger:
    # Очищаем лог-файл, если он существует
    try:
        if log_file.exists():
            log_file.write_text("", encoding="utf-8")
    except Exception:
        pass

    root = logging.getLogger()
    # Отключаем логирование INFO/DEBUG — выводим только предупреждения и ошибки
    root.setLevel(logging.WARNING)
    root.handlers.clear()
    
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    
    # Не добавляем RotatingFileHandler для отключения логирования в файл
    return logging.getLogger("bot")


def build_application(settings: Settings) -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()

    # Команды в ЛС
    app.add_handler(CommandHandler("start", start_command, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("rulesadd", rulesadd_command, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("RulesAdd", rulesadd_command, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("addword", addword_command, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("delword", delword_command, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("addexc", addexc_command, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("delexc", delexc_command, filters=filters.ChatType.PRIVATE))

    # Callback-кнопки
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(group_callback, pattern=r"^(group:|gp:|gs:|ga:)"))

    # Ввод текста в ЛС (для ввода ID, ссылок и т.д.)
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, admin_id_message))

    # События группы
    app.add_handler(ChatMemberHandler(
        my_chat_member_handler, chat_member_types=ChatMemberHandler.MY_CHAT_MEMBER))

    # Модерация сообщений в группах
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & ~filters.COMMAND, group_message_handler))

    return app


def main() -> None:
    settings = load_settings()
    logger = setup_logging(settings.log_level, settings.log_file)
    logger.warning("Запуск бота модератора (логирование отключено, режим WARNING)...")

    # Загружаем правила из файла (с авто-перезагрузкой при изменении)
    rules_path = BASE_DIR / "правила.txt"
    if not rules_path.exists():
        rules_path = BASE_DIR / "rules.txt"
    rules_loader = RulesLoader(rules_path)

    db_module.db = Database(settings)

    ai = AiModerator(settings)
    punishment = PunishmentService()
    settings_service = SettingsService()
    logging_service = LoggingService(logger)
    spam_detector = SpamDetector()
    moderation_service = ModerationService(
        settings=settings, ai=ai, punishment=punishment,
        settings_service=settings_service, logging_service=logging_service,
        spam_detector=spam_detector, rules_loader=rules_loader,
    )

    application = build_application(settings)
    application.bot_data["moderation_service"] = moderation_service
    application.bot_data["logging_service"] = logging_service
    application.bot_data["settings"] = settings
    application.bot_data["rules_loader"] = rules_loader

    scheduler = SchedulerService(application)

    async def post_init(app: Application) -> None:
        await db_module.db.init_db()
        
        # Очистка всех логов из таблицы logs в базе данных
        try:
            async with db_module.db.session() as session:
                from sqlalchemy import delete
                from bot.models import LogEntry
                await session.execute(delete(LogEntry))
            logger.warning("Таблица логов в базе данных очищена.")
        except Exception as e:
            logger.error("Не удалось очистить логи БД: %s", e)

        await scheduler.start()
        
        # Запуск веб-сервера Mini App
        from bot.web.server import run_server
        runner = await run_server(
            db=db_module.db,
            rules_loader=rules_loader,
            bot=app.bot,
            settings=settings
        )
        app.bot_data["web_runner"] = runner

    async def post_shutdown(app: Application) -> None:
        await scheduler.stop()
        await ai.close()
        
        # Остановка веб-сервера Mini App
        runner = app.bot_data.get("web_runner")
        if runner:
            await runner.cleanup()
            
        if db_module.db:
            await db_module.db.close()

    application.post_init = post_init
    application.post_shutdown = post_shutdown

    application.run_polling(
        allowed_updates=["message", "callback_query", "my_chat_member"],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
