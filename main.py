"""
main.py — Botning kirish nuqtasi (entry point).

Ishga tushish tartibi:
  1. Logging sozlanadi
  2. Ma'lumotlar bazasi ishga tushiriladi
  3. Bot va Dispatcher yaratiladi
  4. Middleware qo'shiladi (DB injection)
  5. Handler router'lari ulanadi
  6. APScheduler ishga tushiriladi
  7. Keep-alive web server ishga tushiriladi (Render/Koyeb uchun)
  8. Polling boshlanadi
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import sys
import urllib.parse
from datetime import datetime, timedelta

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats
import pytz

import secrets
from config import ADMIN_IDS, MINI_ADMIN_IDS, MINI_ADMIN_LOGINS, BOT_TOKEN, DATABASE_URL, PORT, TIMEZONE, WEBAPP_URL
from curator_credentials import CURATORS
from database import DatabaseService, GroupType
from handlers import (
    admin_extras_router,
    attendance_router,
    callbacks_router,
    commands_router,
    curator_router,
    registration_router,
    school_router,
    student_router,
)
from middleware import ButtonTrackingMiddleware, CallbackAnswerMiddleware, DatabaseMiddleware, TypingMiddleware
from scheduler import setup_scheduler


# ─── Logging sozlash ─────────────────────────────────────────────────────────

def setup_logging() -> None:
    """
    Structured logging sozlaymiz.
    Stdout + bot.log fayliga bir vaqtda yoziladi.
    """
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, datefmt=datefmt, handlers=handlers)
    # Shovqinli tashqi kutubxona log'larini kamaytirish
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


# ─── WebApp: initData verifikatsiya ──────────────────────────────────────────

def _verify_webapp_init_data(init_data: str) -> dict | None:
    """
    Telegram WebApp initData ni HMAC-SHA256 orqali tekshiradi.
    Yaroqli bo'lsa — parsed dict qaytaradi, aks holda None.
    """
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )
        secret_key = hmac.new(
            b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256
        ).digest()
        computed_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(computed_hash, received_hash):
            return None
        return parsed
    except Exception:
        return None


def _get_user_id_from_init_data(init_data: str) -> int | None:
    parsed = _verify_webapp_init_data(init_data)
    if not parsed:
        return None
    user_json = parsed.get("user")
    if not user_json:
        return None
    try:
        user = json.loads(user_json)
        return int(user.get("id", 0)) or None
    except Exception:
        return None


# ─── Keep-alive web server + Mini App API ────────────────────────────────────

async def _health_check(request: web.Request) -> web.Response:
    return web.Response(text="OK ✅", status=200, content_type="text/plain")


def _make_api_app(bot: Bot, db: DatabaseService) -> web.Application:
    """Mini App uchun API endpointlar + static fayllar."""

    tz = pytz.timezone(TIMEZONE)

    # ── CORS middleware ────────────────────────────────────────────────────────
    @web.middleware
    async def cors_middleware(request: web.Request, handler):
        response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Init-Data"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    # ── Level-up bildirishnoma ────────────────────────────────────────────────
    async def _notify_level_up(user_id: int, new_level: int) -> None:
        """O'quvchiga level oshganda xabar yuboradi; Lv.7 da adminni xabardor qiladi."""
        from database import _level_name, LEVEL_UP_BONUS
        PERK_TEXT = {
            2: "💬 Chat + 🎨 Emoji avatar ochildi!",
            3: "⭐ Streak bonuslari oshdi!",
            4: "📊 Chat da VIP belgisi va batafsil statistika!",
            5: "🌟 Reyting da sariq ism!",
            6: "⚡ 2x XP multiplikator faollashdi — barcha XP ikki barobar!",
            7: "👑 LEGEND! Admin bilan bog'laning — 1 oylik Telegram Premium kutmoqda!",
        }
        bonus  = LEVEL_UP_BONUS.get(new_level, 0)
        lname  = _level_name(new_level)
        perk   = PERK_TEXT.get(new_level, "")
        icons  = {1:'🎯',2:'⭐',3:'🌟',4:'💎',5:'🏆',6:'⚡',7:'👑'}
        icon   = icons.get(new_level, '🎉')
        text   = (
            f"{icon} <b>Tabriklaymiz! Daraja oshdi!</b>\n\n"
            f"🏅 {new_level}-daraja — <b>{lname}</b>\n"
            f"🎁 Bonus: <b>+{bonus} XP</b>\n"
        )
        if perk:
            text += f"✨ {perk}\n"
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
        except Exception:
            logger.warning("Level-up xabari yuborilmadi | user_id=%s level=%s", user_id, new_level, exc_info=True)
        if new_level == 7:
            student = await db.get_student(user_id)
            notif   = (
                f"🏆 <b>{student.full_name if student else user_id}</b> 7-darajaga yetdi!\n"
                f"📚 Guruh: {student.group_name if student else '—'}\n"
                f"🎁 1 oylik Telegram Premium berishni unutmang!"
            )
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, notif, parse_mode="HTML")
                except Exception:
                    logger.warning(
                        "Legend level admin notify yuborilmadi | admin_id=%s user_id=%s",
                        admin_id,
                        user_id,
                        exc_info=True,
                    )

    # ── Auth helper ───────────────────────────────────────────────────────────
    def _auth(request: web.Request) -> int | None:
        init_data = request.headers.get("X-Init-Data", "")
        return _get_user_id_from_init_data(init_data)

    # ── Mini Admin Session ────────────────────────────────────────────────────
    _mini_sessions: dict[str, dict] = {}

    def _check_mini_session(request: web.Request) -> str | None:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        token = auth[7:].strip()
        sess  = _mini_sessions.get(token)
        if not sess:
            return None
        if datetime.utcnow() > sess["expires"]:
            del _mini_sessions[token]
            return None
        return sess["username"]

    def _admin_auth(request: web.Request) -> int | None:
        uid = _auth(request)
        return uid if uid and uid in ADMIN_IDS else None

    def _mini_admin_auth(request: web.Request) -> int | None:
        uid = _auth(request)
        if uid and uid in MINI_ADMIN_IDS:
            return uid
        username = _check_mini_session(request)
        if username:
            return -1
        return None

    # ── Route setup ──────────────────────────────────────────────────────────

    from routes.student_routes import setup_student_routes
    from routes.curator_routes import setup_curator_routes
    from routes.admin_routes   import setup_admin_routes
    from routes.game_routes    import setup_game_routes

    ctx = {
        "bot":             bot,
        "db":              db,
        "tz":              tz,
        "auth":            _auth,
        "admin_auth":      _admin_auth,
        "mini_admin_auth": _mini_admin_auth,
        "mini_sessions":   _mini_sessions,
        "notify_level_up": _notify_level_up,
        "get_user_id":     _get_user_id_from_init_data,
        "verify_init_data": _verify_webapp_init_data,
    }

    app = web.Application(middlewares=[cors_middleware])

    setup_student_routes(app, ctx)
    setup_curator_routes(app, ctx)
    setup_admin_routes(app, ctx)
    setup_game_routes(app, ctx)

    async def options_handler(request: web.Request) -> web.Response:
        return web.Response(status=204, headers={
            "Access-Control-Allow-Origin":  "*",
            "Access-Control-Allow-Headers": "Content-Type, X-Init-Data",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        })

    webapp_dir = os.path.join(os.path.dirname(__file__), "webapp")
    app.router.add_route("OPTIONS", "/{path_info:.*}", options_handler)
    if os.path.isdir(webapp_dir):
        app.router.add_static("/webapp", webapp_dir, show_index=True)
        for _fname in ["student.html", "admin.html", "admin-mini.html", "curator.html", "guide.html", "games.html"]:
            _fpath = os.path.join(webapp_dir, _fname)
            if os.path.isfile(_fpath):
                app.router.add_get(f"/{_fname}", lambda r, p=_fpath: web.FileResponse(p))
    return app


async def start_web_server(bot: Bot = None, db: DatabaseService = None) -> web.AppRunner:
    """
    Render va Koyeb uchun HTTP server.
    bot va db berilsa — Mini App API ham ishga tushadi.
    """
    if bot and db:
        app = _make_api_app(bot, db)
    else:
        app = web.Application()

    app.router.add_get("/",       _health_check)
    app.router.add_get("/health", _health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    try:
        await site.start()
        logger.info(f"Keep-alive web server ishga tushdi | port {PORT}")
    except OSError as e:
        logger.warning(f"Web server port {PORT} band, o'tkazib yuborildi: {e}")
    return runner


# ─── Asosiy funksiya ──────────────────────────────────────────────────────────

async def main() -> None:
    setup_logging()

    logger.info("=" * 60)
    logger.info("  O'QUV MARKAZ DARS ESLATMASI BOTI ISHGA TUSHMOQDA")
    logger.info("=" * 60)

    # 1. Ma'lumotlar bazasini ishga tushirish
    db = DatabaseService(DATABASE_URL)
    await db.init_db()

    # 2. Bot va Dispatcher yaratish
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # 3. Middleware'larni ulash
    dp.update.middleware(DatabaseMiddleware(db))
    dp.callback_query.middleware(CallbackAnswerMiddleware())      # Tugma → darhol javob
    dp.callback_query.middleware(ButtonTrackingMiddleware(db))    # Tugma statistikasi
    dp.message.middleware(TypingMiddleware())                     # Xabar → "yozmoqda..."

    # 4. Handler router'larini ulash
    dp.include_router(commands_router)      # /start, /panel, ...
    dp.include_router(curator_router)       # /curator + kurator relay chat
    dp.include_router(registration_router)  # Ro'yxatdan o'tish FSM
    dp.include_router(student_router)       # O'quvchi paneli + uy vazifasi
    dp.include_router(attendance_router)    # Davomat tugmalari
    dp.include_router(school_router)        # Jadval + savol-javob
    dp.include_router(admin_extras_router)  # Statistika, broadcast, vaqt ...
    dp.include_router(callbacks_router)     # Admin inline callbacks
    logger.info("Handler router'lari ulandi.")

    # 5. Schedulerni sozlash va ishga tushirish
    scheduler = setup_scheduler(bot=bot, db=db, timezone_str=TIMEZONE, webapp_url=WEBAPP_URL)
    scheduler.start()

    # 6. Keep-alive web server'ni ishga tushirish (Mini App API bilan)
    web_runner = await start_web_server(bot=bot, db=db)

    # 7. Bot command menu'ni sozlash (Telegram "/" menyusi)
    await bot.set_my_commands(
        commands=[
            BotCommand(command="start",       description="Botni boshlash"),
            BotCommand(command="panel",       description="Admin panel"),
            BotCommand(command="list_groups", description="Guruhlar ro'yxati"),
            BotCommand(command="status",      description="Bot holati"),
            BotCommand(command="test_send",   description="Test xabar yuborish"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )
    logger.info("Bot command menu sozlandi.")

    # 8. Bot ma'lumotlarini ko'rsatish
    bot_info = await bot.get_me()
    logger.info(f"Bot: @{bot_info.username} (ID: {bot_info.id})")
    logger.info("Polling boshlanmoqda... (Ctrl+C - to'xtatish)")
    logger.info("=" * 60)

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        logger.info("Bot to'xtatilmoqda...")
        scheduler.shutdown(wait=False)
        await web_runner.cleanup()
        await bot.session.close()
        logger.info("Bot muvaffaqiyatli to'xtatildi.")


# ─── Kirish nuqtasi ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Foydalanuvchi tomonidan to'xtatildi (KeyboardInterrupt).")
