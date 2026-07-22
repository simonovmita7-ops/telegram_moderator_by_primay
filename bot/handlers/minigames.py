"""
Обработчики мини-игр в группах.
Включает: /minigames, /rlt, /HardcoreRLT, а также систему Дуэлей.
"""
from __future__ import annotations
import asyncio
import re
import random
import logging
from sqlalchemy import select, func
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot.database import get_db
from bot.models import ChatMessageCache, Group

logger = logging.getLogger(__name__)

# Хранилище активных дуэлей в памяти
# key: message_id (ID сообщения с вызовом или игровой панели)
active_duels: dict[int, dict] = {}


async def minigames_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None or update.effective_chat is None or update.effective_user is None:
        return
    
    text = update.effective_message.text.strip()
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    # --- 1. Список игр ---
    if text.startswith("/minigames"):
        games_text = (
            "🎮 <b>Доступные мини-игры в группе:</b>\n\n"
            "🔫 <b>Русская рулетка (/rlt)</b>\n"
            "Испытайте свою удачу. Выберите количество патронов в барабане.\n"
            "<i>Запуск: любой участник может написать <code>/rlt</code></i>\n\n"
            "💀 <b>Хардкорная рулетка (/HardcoreRLT)</b>\n"
            "Бот выбирает случайного участника группы и исключает (кикает) его из чата.\n"
            "<i>Запуск: только администраторы / владелец могут написать <code>/HardcoreRLT</code></i>\n\n"
            "⚔️ <b>Дуэли (Дуэль @участник)</b>\n"
            "Вызовите соперника на дуэль. Оппонент принимает вызов, после чего начинается пошаговая перестрелка с тактическими действиями.\n"
            "<i>Запуск: напишите <code>Дуэль @участник</code> или <code>@участник дуэль</code></i>"
        )
        await update.effective_message.reply_text(games_text, parse_mode=ParseMode.HTML)
        return

    # --- 2. Обычная рулетка ---
    elif text.startswith("/rlt"):
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("1/6", callback_data=f"minigame:rlt:1:{user_id}"),
                InlineKeyboardButton("3/6", callback_data=f"minigame:rlt:3:{user_id}"),
                InlineKeyboardButton("5/6", callback_data=f"minigame:rlt:5:{user_id}")
            ]
        ])
        await update.effective_message.reply_text(
            "Ну что, смельчак, проверим твою удачу?\nНасколько ты уверен в себе?",
            reply_markup=kb
        )
        return

    # --- 3. Хардкорная рулетка ---
    elif text.startswith("/HardcoreRLT"):
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            is_admin = member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
        except Exception:
            is_admin = False
            
        if not is_admin:
            await update.effective_message.reply_text("Эту игру может запустить только админ или же владелец")
            return

        db = get_db()
        async with db.session() as session:
            group = await session.scalar(select(Group).where(Group.telegram_id == chat_id))
            if not group:
                await update.effective_message.reply_text("Ошибка: группа не зарегистрирована в базе данных бота.")
                return
            
            result = await session.execute(
                select(ChatMessageCache.user_telegram_id, ChatMessageCache.username)
                .where(ChatMessageCache.group_id == group.id)
                .distinct()
            )
            candidates = result.all()

        try:
            chat_admins = await context.bot.get_chat_administrators(chat_id)
            admin_ids = {admin.user.id for admin in chat_admins}
        except Exception as e:
            logger.warning(f"Не удалось получить список админов чата: {e}")
            admin_ids = set()

        bot_id = context.bot.id
        participants = []
        for c in candidates:
            c_id = c[0]
            if c_id not in admin_ids and c_id != bot_id:
                try:
                    chat_member = await context.bot.get_chat_member(chat_id, c_id)
                    name = chat_member.user.first_name or chat_member.user.username or f"ID {c_id}"
                    participants.append((c_id, name))
                except Exception:
                    name = c[1] or f"ID {c_id}"
                    participants.append((c_id, name))

        if not participants:
            await update.effective_message.reply_text(
                "Не найдено подходящих участников для рулетки (администраторы не могут быть исключены)."
            )
            return

        # Таймер перед запуском
        msg = await update.effective_message.reply_text("Запускаю хардкор рулетку через 3...")
        await asyncio.sleep(1.0)
        await msg.edit_text("Запускаю хардкор рулетку через 2...")
        await asyncio.sleep(1.0)
        await msg.edit_text("Запускаю хардкор рулетку через 1...")
        await asyncio.sleep(1.0)
        await msg.edit_text("Запускаю супер рулетку")

        final_victim_id, final_victim_name = random.choice(participants)
        
        steps = [random.choice(participants) for _ in range(14)]
        steps.append((final_victim_id, final_victim_name))

        for idx, p in enumerate(steps):
            delay = 0.1 * (idx + 1)
            await asyncio.sleep(delay)
            try:
                if idx == len(steps) - 1:
                    await msg.edit_text(
                        f"Чтож, тебе не повезло, <b>{final_victim_name}</b> 🔫",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await msg.edit_text(
                        f"Запускаю супер рулетку\n🎯 Выбор жертвы: <b>{p[1]}</b>",
                        parse_mode=ParseMode.HTML
                    )
            except BadRequest:
                pass

        try:
            await context.bot.ban_chat_member(chat_id, final_victim_id)
            await context.bot.unban_chat_member(chat_id, final_victim_id)
            await context.bot.send_message(
                chat_id, 
                f"🚪 <b>{final_victim_name}</b> был исключен из группы."
            )
        except Exception as e:
            logger.error(f"Не удалось кикнуть участника {final_victim_id} в хардкор рулетке: {e}")
            await context.bot.send_message(
                chat_id,
                f"⚠️ Не удалось исключить <b>{final_victim_name}</b> (возможно, у бота недостаточно прав)."
            )

    # --- 4. Принятие / Отказ дуэли текстом ---
    elif text.lower() in ("дуэль принять", "дуэль отказано"):
        reply = update.effective_message.reply_to_message
        if reply is None:
            return
        
        duel_id = reply.message_id
        if duel_id not in active_duels:
            return
        
        duel = active_duels[duel_id]
        if duel["status"] != "pending":
            return
        
        # Проверяем, что отвечает именно тот, кого вызвали
        is_target = False
        if duel["target_id"] and user_id == duel["target_id"]:
            is_target = True
        elif update.effective_user.username and update.effective_user.username.lower() == duel["target_username"].lower():
            is_target = True
            
        if not is_target:
            return

        if text.lower() == "дуэль принять":
            await _start_duel_game(update.effective_message, context, duel_id, user_id, user_name)
        else:
            await _decline_duel_game(update.effective_message, duel_id, user_name)

    # --- 5. Вызов на дуэль (Регулярные выражения) ---
    else:
        match_chall = re.search(r'(?i)^дуэль\s+@(\w+)', text)
        match_target = re.search(r'(?i)@(\w+)\s+дуэль', text)
        target_username = None
        
        if match_chall:
            target_username = match_chall.group(1)
        elif match_target:
            target_username = match_target.group(1)
            
        if target_username:
            # Исключаем вызов самого себя или бота
            if update.effective_user.username and target_username.lower() == update.effective_user.username.lower():
                await update.effective_message.reply_text("Вы не можете вызвать на дуэль самого себя! 🤠")
                return
            if target_username.lower() == context.bot.username.lower():
                await update.effective_message.reply_text("Я робот, мои пули железные! Выберите живого противника. 🤖")
                return

            # Ищем ID оппонента в базе данных
            db = get_db()
            target_id = None
            async with db.session() as session:
                res = await session.execute(
                    select(ChatMessageCache.user_telegram_id)
                    .where(func.lower(ChatMessageCache.username) == target_username.lower())
                    .limit(1)
                )
                target_id = res.scalar_one_or_none()

            # Отправляем сообщение-вызов
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Принять", callback_data=f"duel:accept:{user_id}:{target_username}"),
                    InlineKeyboardButton("❌ Отказать", callback_data=f"duel:decline:{user_id}:{target_username}")
                ]
            ])
            
            msg = await update.effective_message.reply_text(
                f"⚔️ <b>Вызов на дуэль!</b>\n\n"
                f"@{target_username}, вас приглашает на дуэль <b>{user_name}</b>.\n\n"
                f"Напишите в ответ <b>«Дуэль принять»</b> или нажмите кнопку ниже, чтобы принять вызов. "
                f"Для отказа напишите <b>«Дуэль отказано»</b>.",
                parse_mode=ParseMode.HTML,
                reply_markup=kb
            )
            
            # Сохраняем состояние дуэли
            active_duels[msg.message_id] = {
                "chat_id": chat_id,
                "challenger_id": user_id,
                "challenger_name": user_name,
                "target_id": target_id,
                "target_username": target_username,
                "target_name": f"@{target_username}",
                "bullets": 6,
                "aim_level": {user_id: 1},
                "current_turn": None,
                "status": "pending"
            }


# --- Хелперы запуска и отмены дуэлей ---

async def _start_duel_game(message_obj, context, duel_id, target_user_id, target_user_name):
    duel = active_duels[duel_id]
    duel["target_id"] = target_user_id
    duel["target_name"] = target_user_name
    duel["aim_level"][target_user_id] = 1
    duel["current_turn"] = target_user_id # Защищающийся стреляет первым
    duel["status"] = "active"
    
    # Генерируем игровое поле
    text = _get_duel_board_text(duel)
    kb = _get_duel_board_keyboard(duel)
    
    # Если это было вызвано кнопкой, редактируем, если сообщением — шлем новое
    if hasattr(message_obj, "edit_text"):
        await message_obj.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        # Отвечаем на сообщение вызова
        msg = await message_obj.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        # Переносим состояние на новое сообщение, чтобы кнопки работали дальше
        active_duels[msg.message_id] = active_duels.pop(duel_id)


async def _decline_duel_game(message_obj, duel_id, target_user_name):
    duel = active_duels.pop(duel_id, None)
    if duel:
        text = f"❌ <b>{target_user_name}</b> струсил и отклонил дуэль с <b>{duel['challenger_name']}</b>! Выстрелов не будет."
        if hasattr(message_obj, "edit_text"):
            await message_obj.edit_text(text, parse_mode=ParseMode.HTML)
        else:
            await message_obj.reply_text(text, parse_mode=ParseMode.HTML)


# --- Отрисовка игрового поля дуэлей ---

def _get_duel_board_text(duel: dict) -> str:
    turn_name = duel["challenger_name"] if duel["current_turn"] == duel["challenger_id"] else duel["target_name"]
    challenger_aim = f"{duel['aim_level'][duel['challenger_id']]}/6"
    target_aim = f"{duel['aim_level'][duel['target_id']]}/6"
    
    return (
        f"⚔️ <b>ДУЭЛЬ В САМОМ РАЗГАРЕ!</b>\n\n"
        f"🤠 <b>Ход игрока:</b> <b>{turn_name}</b>\n\n"
        f"🔫 Патронов в барабане: <b>{duel['bullets']}/6</b>\n"
        f"🎯 Точность {duel['challenger_name']}: <b>{challenger_aim}</b>\n"
        f"🎯 Точность {duel['target_name']}: <b>{target_aim}</b>"
    )


def _get_duel_board_keyboard(duel: dict) -> InlineKeyboardMarkup:
    # Зарядка доступна только когда патронов осталось <= 3
    btn_row1 = [
        InlineKeyboardButton("💥 Выстрелить", callback_data=f"duel_action:shoot:{duel['challenger_id']}:{duel['target_id']}"),
        InlineKeyboardButton("🎯 Прицелиться", callback_data=f"duel_action:aim:{duel['challenger_id']}:{duel['target_id']}")
    ]
    btn_row2 = [
        InlineKeyboardButton("💨 Сбить прицел", callback_data=f"duel_action:disrupt:{duel['challenger_id']}:{duel['target_id']}"),
        InlineKeyboardButton("💀 Застрелиться", callback_data=f"duel_action:suicide:{duel['challenger_id']}:{duel['target_id']}")
    ]
    
    rows = [btn_row1, btn_row2]
    if duel["bullets"] <= 3:
        rows.insert(1, [
            InlineKeyboardButton("🔄 Зарядить", callback_data=f"duel_action:reload:{duel['challenger_id']}:{duel['target_id']}")
        ])
        
    return InlineKeyboardMarkup(rows)


# --- Коллбеки кнопок мини-игр ---

async def minigames_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    
    parts = query.data.split(":")
    prefix = parts[0]
    
    # 1. Обработка кнопок русской рулетки
    if prefix == "minigame":
        action = parts[1]
        
        # Выбор патронов
        if action == "rlt":
            bullets = int(parts[2])
            player_id = int(parts[3])
            
            if query.from_user.id != player_id:
                await query.answer("Это не ваша игра! Напишите /rlt чтобы запустить свою.", show_alert=True)
                return
            
            await query.answer()
            
            header = "Вижу ты не уверен в себе"
            if bullets == 3:
                header = "Заряжаем половину барабана"
            elif bullets == 5:
                header = "Настоящий безумец!"
                
            await query.edit_message_text(f"{header}\nЗаряжаю 0/6")
            
            for b in range(1, bullets + 1):
                await asyncio.sleep(0.5)
                if b == bullets:
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔫 Крутить барабан", callback_data=f"minigame:spin:{bullets}:{player_id}")]
                    ])
                    await query.edit_message_text(
                        f"{header}\nЗаряжаю {b}/6",
                        reply_markup=kb
                    )
                else:
                    await query.edit_message_text(f"{header}\nЗаряжаю {b}/6")
            return

        # Спин барабана
        elif action == "spin":
            bullets = int(parts[2])
            player_id = int(parts[3])
            
            if query.from_user.id != player_id:
                await query.answer("Это не ваша игра!", show_alert=True)
                return
            
            await query.answer()
            
            animations = [
                "🌀 <i>Барабан крутится... (дзынь)</i>",
                "🌀 <i>Барабан крутится... (вжжж)</i>",
                "🌀 <i>Барабан крутится... (щёлк)</i>"
            ]
            
            for anim in animations:
                await query.edit_message_text(anim, parse_mode=ParseMode.HTML)
                await asyncio.sleep(0.3)

            roll = random.randint(1, 6)
            if roll <= bullets:
                await query.edit_message_text("Вы проиграли🔫")
            else:
                await query.edit_message_text("Вы выжили, вам повезло👍")
            return

    # 2. Принятие вызова дуэли по инлайн-кнопкам
    elif prefix == "duel":
        action = parts[1]
        challenger_id = int(parts[2])
        target_username = parts[3]
        duel_id = query.message.message_id
        
        if duel_id not in active_duels:
            await query.answer("Эта дуэль уже недействительна.", show_alert=True)
            return
            
        duel = active_duels[duel_id]
        
        # Проверяем, что кнопку нажимает именно вызванный соперник
        is_target = False
        if query.from_user.username and query.from_user.username.lower() == target_username.lower():
            is_target = True
        elif duel["target_id"] and query.from_user.id == duel["target_id"]:
            is_target = True
            
        if not is_target:
            await query.answer("Этот вызов брошен не вам!", show_alert=True)
            return
            
        await query.answer()
        
        if action == "accept":
            await _start_duel_game(query.message, context, duel_id, query.from_user.id, query.from_user.first_name)
        else:
            await _decline_duel_game(query.message, duel_id, query.from_user.first_name)

    # 3. Действия во время дуэли
    elif prefix == "duel_action":
        action = parts[1]
        challenger_id = int(parts[2])
        target_id = int(parts[3])
        duel_id = query.message.message_id
        
        if duel_id not in active_duels:
            await query.answer("Дуэль завершена или не найдена.", show_alert=True)
            return
            
        duel = active_duels[duel_id]
        user_id = query.from_user.id
        
        # Проверка очереди хода
        if user_id != duel["current_turn"]:
            await query.answer("Сейчас не ваш ход!", show_alert=True)
            return
            
        await query.answer()
        
        opponent_id = target_id if user_id == challenger_id else challenger_id
        opponent_name = duel["target_name"] if user_id == challenger_id else duel["challenger_name"]
        user_name = duel["challenger_name"] if user_id == challenger_id else duel["target_name"]

        # --- Кнопка: Выстрелить ---
        if action == "shoot":
            # Бросок кубика. Шанс попадания: aim_level / 6
            roll = random.randint(1, 6)
            aim = duel["aim_level"][user_id]
            
            if roll <= aim:
                # Попадание!
                active_duels.pop(duel_id, None)
                await query.edit_message_text(
                    f"💀 <b>ДУЭЛЬ ЗАВЕРШЕНА!</b>\n\n"
                    f"💥 <b>{user_name}</b> выстрелил и попал в <b>{opponent_name}</b>!\n"
                    f"Проигравший покидает чат через 3 секунды...",
                    parse_mode=ParseMode.HTML
                )
                
                try:
                    db = get_db()
                    async with db.session() as session:
                        from bot.models import Group, DuelRecord
                        group = await session.scalar(select(Group).where(Group.telegram_id == duel["chat_id"]))
                        if group:
                            w_name = user_name.replace("<b>", "").replace("</b>", "")
                            l_name = opponent_name.replace("<b>", "").replace("</b>", "")
                            record = DuelRecord(
                                group_id=group.id,
                                winner_telegram_id=user_id,
                                winner_name=w_name,
                                loser_telegram_id=opponent_id,
                                loser_name=l_name,
                                is_suicide=False
                            )
                            session.add(record)
                            await session.commit()
                except Exception as db_err:
                    logger.error(f"Не удалось записать дуэль в базу данных: {db_err}")

                await asyncio.sleep(3.0)
                try:
                    await context.bot.ban_chat_member(duel["chat_id"], opponent_id)
                    await context.bot.unban_chat_member(duel["chat_id"], opponent_id)
                    await context.bot.send_message(duel["chat_id"], f"🚪 <b>{opponent_name}</b> был исключен из группы.")
                except Exception as e:
                    logger.error(f"Не удалось кикнуть проигравшего {opponent_id} в дуэли: {e}")
            else:
                # Промах
                duel["bullets"] -= 1
                duel["aim_level"][user_id] = 1 # Сброс прицела после выстрела
                
                # Если патроны кончились
                if duel["bullets"] <= 0:
                    duel["current_turn"] = opponent_id
                    await query.edit_message_text(
                        f"💨 <b>Промах! Барабан пуст.</b>\n\n"
                        f"Ход переходит к <b>{opponent_name}</b> (ему нужно зарядить пистолет).",
                        parse_mode=ParseMode.HTML,
                        reply_markup=_get_duel_board_keyboard(duel)
                    )
                else:
                    duel["current_turn"] = opponent_id
                    await query.edit_message_text(
                        f"💨 <b>Промах!</b> Пуля прошла мимо.\n\n"
                        f"Ход переходит к <b>{opponent_name}</b>.",
                        parse_mode=ParseMode.HTML,
                        reply_markup=_get_duel_board_keyboard(duel)
                    )

        # --- Кнопка: Прицелиться ---
        elif action == "aim":
            # 75% шанс добавить +1 к прицелу, 25% шанс прибавить +0
            aim_roll = random.randint(1, 100)
            bonus = 1 if aim_roll <= 75 else 0
            
            duel["aim_level"][user_id] = min(6, duel["aim_level"][user_id] + bonus)
            duel["current_turn"] = opponent_id
            
            status_text = "Прицел успешно улучшен! 🎯" if bonus == 1 else "Рука дрогнула, прицел не изменился. 💨"
            
            await query.edit_message_text(
                f"🤠 <b>{user_name} прицеливается...</b>\n\n"
                f"{status_text}\n"
                f"Ход переходит к <b>{opponent_name}</b>.",
                parse_mode=ParseMode.HTML,
                reply_markup=_get_duel_board_keyboard(duel)
            )

        # --- Кнопка: Сбить прицел ---
        elif action == "disrupt":
            # Сбрасывает точность соперника до 1/6
            duel["aim_level"][opponent_id] = 1
            duel["current_turn"] = opponent_id
            
            await query.edit_message_text(
                f"💨 <b>{user_name} совершает отвлекающий маневр!</b>\n\n"
                f"Прицел <b>{opponent_name}</b> сброшен до начального (1/6).\n"
                f"Ход переходит к <b>{opponent_name}</b>.",
                parse_mode=ParseMode.HTML,
                reply_markup=_get_duel_board_keyboard(duel)
            )

        # --- Кнопка: Зарядить ---
        elif action == "reload":
            if duel["bullets"] > 3:
                await query.answer("Заряжать можно только если патронов осталось 3 или меньше!", show_alert=True)
                return
            
            # Анимация зарядки с интервалом в 1 секунду
            current_b = duel["bullets"]
            duel["bullets"] = 6
            
            # Временно блокируем кнопки
            await query.edit_message_text(
                f"🔄 <b>{user_name} начинает перезарядку пистолета...</b>\n\n"
                f"Заряжаю {current_b}/6",
                parse_mode=ParseMode.HTML
            )
            
            for b in range(current_b + 1, 7):
                await asyncio.sleep(1.0)
                await query.edit_message_text(
                    f"🔄 <b>{user_name} перезаряжает пистолет...</b>\n\n"
                    f"Заряжаю {b}/6",
                    parse_mode=ParseMode.HTML
                )
            
            duel["current_turn"] = opponent_id
            
            await query.edit_message_text(
                f"✅ <b>Оружие полностью заряжено (6/6)!</b>\n\n"
                f"Ход переходит к <b>{opponent_name}</b>.",
                parse_mode=ParseMode.HTML,
                reply_markup=_get_duel_board_keyboard(duel)
            )

        # --- Кнопка: Застрелиться ---
        elif action == "suicide":
            if duel["bullets"] < 1:
                await query.answer("В барабане нет патронов, чтобы сделать это!", show_alert=True)
                return
            
            active_duels.pop(duel_id, None)
            
            await query.edit_message_text(
                f"💥 {user_name} нажал Застрелиться...\n\n"
                f"Прощай, жестокий мир! 💀\n"
                f"Игрок покидает чат через 3 секунды...",
                parse_mode=ParseMode.HTML
            )
            
            try:
                db = get_db()
                async with db.session() as session:
                    from bot.models import Group, DuelRecord
                    group = await session.scalar(select(Group).where(Group.telegram_id == duel["chat_id"]))
                    if group:
                        w_name = opponent_name.replace("<b>", "").replace("</b>", "")
                        l_name = user_name.replace("<b>", "").replace("</b>", "")
                        record = DuelRecord(
                            group_id=group.id,
                            winner_telegram_id=opponent_id,
                            winner_name=w_name,
                            loser_telegram_id=user_id,
                            loser_name=l_name,
                            is_suicide=True
                        )
                        session.add(record)
                        await session.commit()
            except Exception as db_err:
                logger.error(f"Не удалось записать дуэль-суицид в базу данных: {db_err}")

            await asyncio.sleep(3.0)
            try:
                await context.bot.ban_chat_member(duel["chat_id"], user_id)
                await context.bot.unban_chat_member(duel["chat_id"], user_id)
                await context.bot.send_message(duel["chat_id"], f"🚪 {user_name} добровольно покинул группу.")
            except Exception as e:
                logger.error(f"Не удалось кикнуть суицидника {user_id} в дуэли: {e}")


async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return
    
    chat_id = update.effective_chat.id
    db = get_db()
    
    async with db.session() as session:
        from bot.models import Group, DuelRecord
        group = await session.scalar(select(Group).where(Group.telegram_id == chat_id))
        if not group:
            await update.effective_message.reply_text("📋 Эта группа ещё не зарегистрирована в базе данных бота.")
            return
        
        wins_q = await session.execute(
            select(DuelRecord.winner_name, func.count(DuelRecord.id))
            .where(DuelRecord.group_id == group.id)
            .group_by(DuelRecord.winner_name)
        )
        wins_map = {row[0]: row[1] for row in wins_q.all()}
        
        losses_q = await session.execute(
            select(DuelRecord.loser_name, func.count(DuelRecord.id))
            .where(DuelRecord.group_id == group.id)
            .group_by(DuelRecord.loser_name)
        )
        losses_map = {row[0]: row[1] for row in losses_q.all()}

    players = set(wins_map.keys()) | set(losses_map.keys())
    if not players:
        await update.effective_message.reply_text("🏆 <b>Таблица лидеров дуэлей пуста.</b>\n\nСыграйте первую дуэль, чтобы попасть в топ!", parse_mode=ParseMode.HTML)
        return

    leaderboard = []
    for name in players:
        w = wins_map.get(name, 0)
        l = losses_map.get(name, 0)
        tot = w + l
        wr = (w / tot * 100) if tot > 0 else 0
        leaderboard.append({
            "name": name,
            "wins": w,
            "losses": l,
            "total": tot,
            "win_rate": wr
        })

    leaderboard.sort(key=lambda x: (x["wins"], x["win_rate"]), reverse=True)
    
    text = "🏆 <b>Таблица лидеров дуэлей:</b>\n\n"
    for idx, p in enumerate(leaderboard[:10]):
        medal = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else f"{idx + 1}."
        text += f"{medal} <b>{p['name']}</b> — <b>{p['wins']}</b> побед(ы) (Винрейт: {p['win_rate']:.1f}%, {p['total']} игр)\n"
        
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)
