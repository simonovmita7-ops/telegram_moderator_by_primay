"""
Веб-сервер Mini App. Отдаёт статику и API для Mini App.
"""
from __future__ import annotations
import asyncio
import json
import logging
import urllib.parse
from pathlib import Path
from aiohttp import web
from sqlalchemy import select, func
from bot.models import Violation, Warning as DBWarning, Mute, Kick, Ban, GroupSettings, Group, GroupAdmin
from bot.config import BASE_DIR, Settings

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


async def cors_middleware(app, handler):
    async def middleware_handler(request):
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            response = await handler(request)
        
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-Init-Data, Authorization, ngrok-skip-browser-warning"
        return response
    return middleware_handler


def get_user_id_from_init_data(init_data: str) -> int | None:
    if not init_data:
        return None
    try:
        parsed = urllib.parse.parse_qs(init_data)
        user_str = parsed.get("user", [None])[0]
        if user_str:
            user_data = json.loads(user_str)
            return user_data.get("id")
    except Exception:
        pass
    return None


async def handle_index(request):
    return web.FileResponse(STATIC_DIR / "index.html")


async def verify_user_and_group(session, request, group_tg_id: int) -> tuple[int, Group | None]:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user_id = get_user_id_from_init_data(init_data)
    if not user_id:
        return 0, None
    
    from bot.services.permissions import PermissionService
    perm = PermissionService()
    group = await perm.get_group_by_telegram_id(session, group_tg_id)
    if not group:
        return user_id, None
        
    access = await perm.is_bot_admin(session, group.id, user_id)
    if not access[0]:
        if group.owner_id != user_id:
            return user_id, None
            
    return user_id, group


async def handle_api_data(request):
    """API: данные для Mini App."""
    try:
        app = request.app
        db = app.get("db")
        rules_loader = app.get("rules_loader")
        settings = app.get("settings")
        
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        user_id = get_user_id_from_init_data(init_data)
        
        if not db:
            return web.json_response({"error": "DB not initialized"}, status=500)

        async with db.session() as session:
            from bot.services.permissions import PermissionService
            perm = PermissionService()
            
            if not user_id:
                groups_result = await session.execute(select(Group).where(Group.is_active.is_(True)))
                groups = groups_result.scalars().all()
                if not groups:
                    return web.json_response({"groups": [], "message": "Авторизуйтесь через Telegram"})
                user_id = groups[0].owner_id or 0

            groups = await perm.get_manageable_groups(session, user_id)
            group_list = [{"id": g.telegram_id, "title": g.title} for g in groups]
            
            global_sub = settings.subscription_channel if settings else None

            group_param = request.query.get("group_id")
            selected_group_tg_id = None
            if group_param:
                try:
                    selected_group_tg_id = int(group_param)
                except ValueError:
                    pass
            
            if not selected_group_tg_id and groups:
                selected_group_tg_id = groups[0].telegram_id
                
            if not selected_group_tg_id:
                return web.json_response({
                    "groups": [],
                    "global_subscription_channel": global_sub,
                    "stats": {"violations": 0, "warnings": 0, "mutes": 0, "bans": 0},
                    "violations": [],
                    "rules": [],
                    "rules_raw": "",
                    "banned_words": [],
                    "exception_words": [],
                    "ai_enabled": True,
                })

            group = await perm.get_group_by_telegram_id(session, selected_group_tg_id)
            if not group:
                return web.json_response({"error": "Группа не найдена"}, status=404)

            from bot.services.settings_service import SettingsService
            gs_svc = SettingsService()
            gs = await gs_svc.get_or_create(session, group.id)
            
            stats = {
                "violations": (await session.scalar(select(func.count(Violation.id)).where(Violation.group_id == group.id))) or 0,
                "warnings": (await session.scalar(select(func.count(DBWarning.id)).where(DBWarning.group_id == group.id))) or 0,
                "mutes": (await session.scalar(select(func.count(Mute.id)).where(Mute.group_id == group.id))) or 0,
                "kicks": (await session.scalar(select(func.count(Kick.id)).where(Kick.group_id == group.id))) or 0,
            }
            
            result = await session.execute(
                select(Violation).where(Violation.group_id == group.id)
                .order_by(Violation.created_at.desc()).limit(8))
            violations = result.scalars().all()
            violations_data = [
                {"user": f"ID {v.user_telegram_id}",
                 "cat": v.category.value,
                 "reason": v.reason[:50],
                 "badge": _cat_badge(v.category.value)}
                for v in violations
            ]
            
            rules_raw = gs.rules_text or (rules_loader.get_rules() if rules_loader else "")
            
            # Получаем таблицу лидеров дуэлей
            from bot.models import DuelRecord
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
                    "win_rate": round(wr, 1)
                })
            leaderboard.sort(key=lambda x: (x["wins"], x["win_rate"]), reverse=True)

            bot_username = app.get("bot_username", "GControlsBot")
            data = {
                "groups": group_list,
                "selected_group_id": selected_group_tg_id,
                "global_subscription_channel": global_sub,
                "bot_username": bot_username,
                "stats": stats,
                "violations": violations_data,
                "rules": _parse_rules(rules_raw),
                "rules_raw": rules_raw,
                "banned_words": gs.banned_words or [],
                "exception_words": gs.exception_words or [],
                "ai_enabled": gs.ai_enabled,
                "ai_provider": getattr(gs, "ai_provider", "gemini") or "gemini",
                "enabled_rules": gs.enabled_rules or {},
                "has_custom_rules": gs.rules_text is not None and len(gs.rules_text.strip()) > 0,
                "leaderboard": leaderboard[:10],  # Топ-10
            }
            return web.json_response(data)
    except Exception as e:
        logger.exception("Mini app data error: %s", e)
        return web.json_response({"error": str(e)}, status=500)


async def handle_check_subscription(request):
    """Проверка подписки на глобальный канал."""
    try:
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        user_id = get_user_id_from_init_data(init_data)
        if not user_id:
            return web.json_response({"subscribed": False, "message": "Не удалось авторизовать пользователя"})
        
        bot = request.app.get("bot")
        settings = request.app.get("settings")
        if not bot or not settings:
            return web.json_response({"subscribed": True, "message": "Компоненты бота не подключены"})

        from bot.handlers.start import is_user_subscribed
        ch = settings.subscription_channel

        if not ch:
            return web.json_response({"subscribed": True, "message": "Канал подписки не настроен"})

        subscribed = await is_user_subscribed(bot, user_id, ch)
        return web.json_response({"subscribed": subscribed, "message": "Подписка проверена"})
    except Exception as e:
        logger.exception("Subscription check error: %s", e)
        return web.json_response({"subscribed": True, "message": f"Ошибка: {e}"})


async def handle_toggle_rule(request):
    try:
        req_data = await request.json()
        group_tg_id = int(req_data.get("group_id"))
        category = req_data.get("category")
        
        db = request.app.get("db")
        async with db.session() as session:
            user_id, group = await verify_user_and_group(session, request, group_tg_id)
            if not group:
                return web.json_response({"error": "Доступ запрещён"}, status=403)
            
            from bot.services.settings_service import SettingsService
            gs_svc = SettingsService()
            new_val = await gs_svc.toggle_rule(session, group.id, category)
            
            return web.json_response({"success": True, "enabled": new_val})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def handle_add_word(request):
    try:
        req_data = await request.json()
        group_tg_id = int(req_data.get("group_id"))
        word = req_data.get("word", "").strip()
        word_type = req_data.get("type", "banned")
        
        if not word:
            return web.json_response({"error": "Слово не может быть пустым"}, status=400)
            
        db = request.app.get("db")
        async with db.session() as session:
            user_id, group = await verify_user_and_group(session, request, group_tg_id)
            if not group:
                return web.json_response({"error": "Доступ запрещён"}, status=403)
                
            from bot.services.settings_service import SettingsService
            gs_svc = SettingsService()
            if word_type == "banned":
                words = await gs_svc.add_banned_word(session, group.id, word)
            else:
                words = await gs_svc.add_exception_word(session, group.id, word)
                
            return web.json_response({"success": True, "words": words})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def handle_remove_word(request):
    try:
        req_data = await request.json()
        group_tg_id = int(req_data.get("group_id"))
        word = req_data.get("word", "").strip()
        word_type = req_data.get("type", "banned")
        
        db = request.app.get("db")
        async with db.session() as session:
            user_id, group = await verify_user_and_group(session, request, group_tg_id)
            if not group:
                return web.json_response({"error": "Доступ запрещён"}, status=403)
                
            from bot.services.settings_service import SettingsService
            gs_svc = SettingsService()
            if word_type == "banned":
                words = await gs_svc.remove_banned_word(session, group.id, word)
            else:
                words = await gs_svc.remove_exception_word(session, group.id, word)
                
            return web.json_response({"success": True, "words": words})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def handle_set_rules_text(request):
    try:
        req_data = await request.json()
        group_tg_id = int(req_data.get("group_id"))
        rules_text = req_data.get("rules_text", "").strip() or None
        
        db = request.app.get("db")
        async with db.session() as session:
            user_id, group = await verify_user_and_group(session, request, group_tg_id)
            if not group:
                return web.json_response({"error": "Доступ запрещён"}, status=403)
                
            from bot.services.settings_service import SettingsService
            gs_svc = SettingsService()
            await gs_svc.set_custom_rules_text(session, group.id, rules_text)
            return web.json_response({"success": True, "rules_text": rules_text})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def handle_toggle_ai(request):
    try:
        req_data = await request.json()
        group_tg_id = int(req_data.get("group_id"))
        
        db = request.app.get("db")
        async with db.session() as session:
            user_id, group = await verify_user_and_group(session, request, group_tg_id)
            if not group:
                return web.json_response({"error": "Доступ запрещён"}, status=403)
                
            from bot.services.settings_service import SettingsService
            gs_svc = SettingsService()
            gs = await gs_svc.get_or_create(session, group.id)
            gs.ai_enabled = not gs.ai_enabled
            await session.flush()
            return web.json_response({"success": True, "ai_enabled": gs.ai_enabled})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def handle_set_ai_provider(request):
    try:
        req_data = await request.json()
        group_tg_id = int(req_data.get("group_id"))
        provider = str(req_data.get("provider", "gemini")).lower()
        if provider not in ("gemini", "groq", "sambanova", "multi"):
            return web.json_response({"error": "Неверный провайдер ИИ"}, status=400)

        db = request.app.get("db")
        async with db.session() as session:
            user_id, group = await verify_user_and_group(session, request, group_tg_id)
            if not group:
                return web.json_response({"error": "Доступ запрещён"}, status=403)
                
            from bot.services.settings_service import SettingsService
            gs_svc = SettingsService()
            gs = await gs_svc.get_or_create(session, group.id)
            gs.ai_provider = provider
            await session.flush()
            return web.json_response({"success": True, "ai_provider": gs.ai_provider})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


def _parse_rules(text: str) -> list[dict]:
    """Парсим правила в структурированный список."""
    rules = []
    lines = text.split('\n')
    num = 0
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        import re
        m = re.match(r'^(\d+)\.\s+(.+)', line)
        if m:
            num = int(m.group(1))
            title = m.group(2).strip()
            desc_lines = []
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(r'^\d+\.', lines[i]):
                desc_lines.append(lines[i].strip())
                i += 1
            rules.append({
                "num": num,
                "title": title,
                "desc": " ".join(desc_lines),
                "tag": _detect_tag(title)
            })
        else:
            i += 1
    return rules


def _detect_tag(title: str) -> str | None:
    title_lower = title.lower()
    if "оскорб" in title_lower or "участник" in title_lower:
        return "insult"
    if "семь" in title_lower or "родствен" in title_lower:
        return "family_insult"
    if "спам" in title_lower or "флуд" in title_lower:
        return "spam"
    if "конфл" in title_lower or "ссор" in title_lower:
        return "conflict"
    if "перепис" in title_lower or "слив" in title_lower:
        return "leak"
    if "18+" in title_lower or "порно" in title_lower or "взросл" in title_lower:
        return "adult"
    if "насил" in title_lower or "жесток" in title_lower:
        return "violence"
    if "стикер" in title_lower:
        return "sticker_abuse"
    if "опрос" in title_lower:
        return "poll_abuse"
    if "угроз" in title_lower:
        return "threat"
    if "реклам" in title_lower or "пиар" in title_lower:
        return "advertisement"
    return None


def _cat_badge(cat: str) -> str:
    mapping = {
        "spam": "badge-yellow", "insult": "badge-red",
        "advertisement": "badge-purple", "threat": "badge-red",
        "violence": "badge-red", "adult": "badge-red",
        "conflict": "badge-yellow",
    }
    return mapping.get(cat, "badge-purple")


async def handle_status(request):
    app = request.app
    settings = app.get("settings")
    version = getattr(settings, "bot_version", "Beta 1.3") if settings else "Beta 1.3"
    return web.json_response({
        "status": "online",
        "online": True,
        "version": version
    })


async def create_app(db=None, rules_loader=None, bot=None, settings=None) -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app["db"] = db
    app["rules_loader"] = rules_loader
    app["bot"] = bot
    app["settings"] = settings

    app.router.add_get("/", handle_index)
    app.router.add_get("/index.html", handle_index)
    app.router.add_get("/api/status", handle_status)
    app.router.add_get("/api/miniapp/data", handle_api_data)
    app.router.add_post("/api/miniapp/check_subscription", handle_check_subscription)
    
    # Настройки
    app.router.add_post("/api/miniapp/toggle_rule", handle_toggle_rule)
    app.router.add_post("/api/miniapp/add_word", handle_add_word)
    app.router.add_post("/api/miniapp/remove_word", handle_remove_word)
    app.router.add_post("/api/miniapp/set_rules_text", handle_set_rules_text)
    app.router.add_post("/api/miniapp/toggle_ai", handle_toggle_ai)
    app.router.add_post("/api/miniapp/set_ai_provider", handle_set_ai_provider)
    
    app.router.add_static("/static", STATIC_DIR)

    return app


async def run_server(host="127.0.0.1", port=8765, db=None, rules_loader=None, bot=None, settings=None):
    app = await create_app(db=db, rules_loader=rules_loader, bot=bot, settings=settings)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("Mini App сервер запущен: http://%s:%s", host, port)
    return runner
