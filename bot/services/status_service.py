import logging
import os
from datetime import datetime, timezone, timedelta
from telegram import Bot
from telegram.error import BadRequest
from bot.config import Settings

logger = logging.getLogger(__name__)

# Дефолтный шаблон, если файл не создан
WELCOME_POST_TEMPLATE = (
    "👋 Добро пожаловать в официальный канал Group Controls!\n\n"
    "🤖 @GControlsBot — бот для удобного и эффективного управления Telegram-группами.\n\n"
    "Что публикуется в этом канале?\n\n"
    "• 🆕 Новости разработки;\n"
    "• 😐 Исправления ошибок;\n"
    "• 🤩 Анонсы новых функций;\n"
    "• 😎 Важные объявления.\n\n"
    "👍 Новые обновления планируются каждые 2–3 недели. Следите за каналом, чтобы первыми узнавать обо всех изменениях и новых возможностях Group Controls.\n\n"
    "🔥 Текущая версия: {version}\n"
    "✈️ Статус бота: {status}\n\n"
    "🚀 Ориентировочный релиз: ~08.26"
)

async def update_bot_status(bot: Bot, settings: Settings, is_online: bool) -> None:
    ch_id = settings.status_channel_id
    msg_id = settings.status_message_id
    
    if not ch_id or not msg_id:
        return
        
    # Московское время (UTC+3) без зависимости от pytz
    tz = timezone(timedelta(hours=3))
    now_str = datetime.now(tz).strftime("%H:%M:%S")
    
    if is_online:
        status_text = f"Активен 🟢 (обновлено в {now_str} MSK)"
    else:
        status_text = "Отключён 🔴"
        
    # Загружаем кастомный шаблон с кастомными эмодзи, если он был сохранен
    template_path = os.path.join("bot", "data", "welcome_template.txt")
    template = WELCOME_POST_TEMPLATE
    if os.path.exists(template_path):
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()
        except Exception as e:
            logger.error(f"Не удалось прочитать welcome_template.txt: {e}")
            
    text = template.format(version=settings.bot_version, status=status_text)
    
    try:
        await bot.edit_message_text(
            chat_id=ch_id,
            message_id=msg_id,
            text=text,
            parse_mode="HTML"
        )
        logger.info(f"Статус бота успешно обновлен на {status_text} в канале {ch_id}")
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.info("Статус бота в канале уже актуален (текст не изменился).")
        else:
            logger.error(f"Не удалось обновить статус бота в канале (BadRequest): {e}")
    except Exception as e:
        logger.warning(f"Временное предупреждение при обновлении статуса в канале: {e}")
