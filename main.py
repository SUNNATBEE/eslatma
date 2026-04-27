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
import time
import urllib.parse
from datetime import UTC, datetime

import pytz
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats
from aiohttp import web

from config import (
    ADMIN_IDS,
    APP_VERSION,
    BOT_TOKEN,
    CORS_ORIGINS,
    CORS_USE_WILDCARD,
    DATABASE_URL,
    GIT_COMMIT_SHA,
    LOG_JSON,
    MINI_ADMIN_IDS,
    PORT,
    RATE_LIMIT_LOGIN_MAX,
    RATE_LIMIT_LOGIN_WINDOW_SEC,
    TIMEZONE,
    TRUST_X_FORWARDED_FOR,
    WEBAPP_URL,
)
from database import DatabaseService
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
from rate_limit import SlidingWindowLimiter
from scheduler import setup_scheduler

# ─── Logging sozlash ─────────────────────────────────────────────────────────


class _JsonLogFormatter(logging.Formatter):
    """LOG_JSON=1 bo'lsa — bir qator JSON (log agregatorlar uchun)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    """
    Structured logging sozlaymiz.
    Stdout + bot.log fayliga bir vaqtda yoziladi.
    LOG_JSON=1 bo'lsa stdout uchun JSON qatorlar.
    """
    datefmt = "%Y-%m-%d %H:%M:%S"
    stdout = logging.StreamHandler(sys.stdout)
    file_h = logging.FileHandler("bot.log", encoding="utf-8")
    if LOG_JSON:
        stdout.setFormatter(_JsonLogFormatter())
        file_h.setFormatter(_JsonLogFormatter())
        fmt = None
    else:
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        stdout.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
        file_h.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    handlers: list[logging.Handler] = [stdout, file_h]
    if LOG_JSON:
        logging.basicConfig(level=logging.INFO, handlers=handlers)
    else:
        logging.basicConfig(level=logging.INFO, format=fmt, datefmt=datefmt, handlers=handlers)
    # Shovqinli tashqi kutubxona log'larini kamaytirish
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


def _cors_allow_origin_value(request: web.Request) -> str | None:
    """Access-Control-Allow-Origin qiymati (None — header qo'yilmaydi)."""
    if CORS_USE_WILDCARD:
        return "*"
    origin = request.headers.get("Origin")
    if origin and origin in CORS_ORIGINS:
        return origin
    if not origin:
        return "*"
    return None


def _apply_cors_to_response(request: web.Request, response: web.Response) -> None:
    acao = _cors_allow_origin_value(request)
    if acao:
        response.headers["Access-Control-Allow-Origin"] = acao
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Init-Data, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "geolocation=(), microphone=(), camera=(), payment=()",
    )


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

        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

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

    # ── CORS middleware (WEBAPP_URL / CORS_ALLOW_ORIGINS bo'yicha toraytirilgan) ─
    @web.middleware
    async def cors_middleware(request: web.Request, handler):
        response = await handler(request)
        _apply_cors_to_response(request, response)
        return response

    # ── Level-up bildirishnoma ────────────────────────────────────────────────
    async def _notify_level_up(user_id: int, new_level: int) -> None:
        """O'quvchiga level oshganda xabar yuboradi; Lv.7 da adminni xabardor qiladi."""
        from database import LEVEL_UP_BONUS, _level_name

        PERK_TEXT = {
            2: "💬 Chat ochildi + 🎨 Emoji avatar!",
            3: "⭐ Streak bonuslar 2x kuchaydi!",
            4: "📊 VIP belgi + batafsil statistika!",
            5: "🌟 Reytingda oltin ism — hammaga ko'rinasan!",
            6: "⚡ 2x XP mode ON — hamma XP ikki barobar!",
            7: "👑 LEGEND! Adminga yoz — Telegram Premium seniki!",
        }
        bonus = LEVEL_UP_BONUS.get(new_level, 0)
        lname = _level_name(new_level)
        perk = PERK_TEXT.get(new_level, "")
        icons = {1: "🎯", 2: "⭐", 3: "🌟", 4: "💎", 5: "🏆", 6: "⚡", 7: "👑"}
        icon = icons.get(new_level, "🎉")
        text = f"{icon} <b>LEVEL UP!</b>\n\n🏅 {new_level}-daraja — <b>{lname}</b>\n🎁 +<b>{bonus} XP</b> bonus!\n"
        if perk:
            text += f"✨ {perk}\n"
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
        except Exception:
            logger.warning("Level-up xabari yuborilmadi | user_id=%s level=%s", user_id, new_level, exc_info=True)
        if new_level == 7:
            student = await db.get_student(user_id)
            notif = (
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
        sess = _mini_sessions.get(token)
        if not sess:
            return None
        if datetime.now(UTC) > sess["expires"]:
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

    from routes.admin_routes import setup_admin_routes
    from routes.curator_routes import setup_curator_routes
    from routes.game_routes import setup_game_routes
    from routes.student_routes import setup_student_routes

    login_rate_limiter = SlidingWindowLimiter(RATE_LIMIT_LOGIN_MAX, RATE_LIMIT_LOGIN_WINDOW_SEC)

    ctx = {
        "bot": bot,
        "db": db,
        "tz": tz,
        "auth": _auth,
        "admin_auth": _admin_auth,
        "mini_admin_auth": _mini_admin_auth,
        "mini_sessions": _mini_sessions,
        "notify_level_up": _notify_level_up,
        "get_user_id": _get_user_id_from_init_data,
        "verify_init_data": _verify_webapp_init_data,
        "login_rate_limiter": login_rate_limiter,
        "trust_x_forwarded_for": TRUST_X_FORWARDED_FOR,
    }

    app = web.Application(middlewares=[cors_middleware])
    app["boot_ts_epoch"] = time.time()

    async def api_meta_version(_request: web.Request) -> web.Response:
        """Jamoat: versiya va commit (deploy tekshiruvi)."""
        body = {"ok": True, "version": APP_VERSION, "commit": GIT_COMMIT_SHA or None}
        return web.json_response(body)

    async def api_ready(request: web.Request) -> web.Response:
        """DB + scheduler holati (load balancer / k8s readiness)."""
        from scheduler import scheduler_health

        db_ok = await db.check_db_live()
        sch = scheduler_health()
        alive = db_ok and sch.get("running") is True
        body = {
            "ok": alive,
            "database": db_ok,
            "scheduler": sch,
            "uptime_sec": int(time.time() - float(request.app.get("boot_ts_epoch", time.time()))),
        }
        return web.json_response(body, status=200 if alive else 503)

    app.router.add_get("/api/meta/version", api_meta_version)
    app.router.add_get("/ready", api_ready)

    setup_student_routes(app, ctx)
    setup_curator_routes(app, ctx)
    setup_admin_routes(app, ctx)
    setup_game_routes(app, ctx)

    async def options_handler(request: web.Request) -> web.Response:
        hdrs: dict[str, str] = {}
        resp = web.Response(status=204, headers=hdrs)
        _apply_cors_to_response(request, resp)
        return resp

    webapp_dir = os.path.join(os.path.dirname(__file__), "webapp")
    app.router.add_route("OPTIONS", "/{path_info:.*}", options_handler)
    if os.path.isdir(webapp_dir):
        app.router.add_static("/webapp", webapp_dir, show_index=True)

        def _html_file_handler(file_path: str):
            async def _handler(_request: web.Request) -> web.FileResponse:
                return web.FileResponse(file_path)

            return _handler

        for _fname in ["student.html", "admin.html", "admin-mini.html", "curator.html", "guide.html", "games.html"]:
            _fpath = os.path.join(webapp_dir, _fname)
            if os.path.isfile(_fpath):
                app.router.add_get(f"/{_fname}", _html_file_handler(_fpath))
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

    app.router.add_get("/", _health_check)
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

    # 0. Healthcheck serverini darhol ishga tushirish (Railway/Render timeout oldidan)
    async def _early_meta_version(_r: web.Request) -> web.Response:
        return web.json_response({"ok": True, "version": APP_VERSION, "commit": GIT_COMMIT_SHA or None})

    async def _early_ready(_r: web.Request) -> web.Response:
        return web.json_response(
            {"ok": False, "database": False, "scheduler": {"state": "booting"}, "boot": "starting"},
            status=503,
        )

    early_app = web.Application()
    early_app.router.add_get("/", _health_check)
    early_app.router.add_get("/health", _health_check)
    early_app.router.add_get("/api/meta/version", _early_meta_version)
    early_app.router.add_get("/ready", _early_ready)
    early_runner = web.AppRunner(early_app)
    await early_runner.setup()
    early_site = web.TCPSite(early_runner, host="0.0.0.0", port=PORT)
    try:
        await early_site.start()
        logger.info(f"Healthcheck server ishga tushdi | port {PORT}")
    except OSError as e:
        logger.warning(f"Healthcheck server port {PORT} band: {e}")

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
    dp.callback_query.middleware(CallbackAnswerMiddleware())  # Tugma → darhol javob
    dp.callback_query.middleware(ButtonTrackingMiddleware(db))  # Tugma statistikasi
    dp.message.middleware(TypingMiddleware())  # Xabar → "yozmoqda..."

    # 4. Handler router'larini ulash
    dp.include_router(commands_router)  # /start, /panel, ...
    dp.include_router(curator_router)  # /curator + kurator relay chat
    dp.include_router(registration_router)  # Ro'yxatdan o'tish FSM
    dp.include_router(student_router)  # O'quvchi paneli + uy vazifasi
    dp.include_router(attendance_router)  # Davomat tugmalari
    dp.include_router(school_router)  # Jadval + savol-javob
    dp.include_router(admin_extras_router)  # Statistika, broadcast, vaqt ...
    dp.include_router(callbacks_router)  # Admin inline callbacks
    logger.info("Handler router'lari ulandi.")

    # 5. Schedulerni sozlash va ishga tushirish
    scheduler = setup_scheduler(bot=bot, db=db, timezone_str=TIMEZONE, webapp_url=WEBAPP_URL)
    scheduler.start()

    # 6. Healthcheck serverni to'xtatib, to'liq API serverni ishga tushirish
    await early_runner.cleanup()
    web_runner = await start_web_server(bot=bot, db=db)

    # 7. Bot command menu'ni sozlash (Telegram "/" menyusi)
    await bot.set_my_commands(
        commands=[
            BotCommand(command="start", description="Botni boshlash"),
            BotCommand(command="panel", description="Admin panel"),
            BotCommand(command="list_groups", description="Guruhlar ro'yxati"),
            BotCommand(command="status", description="Bot holati"),
            BotCommand(command="test_send", description="Test xabar yuborish"),
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
