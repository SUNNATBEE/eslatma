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

from config import BOT_TOKEN, DATABASE_URL, PORT, TIMEZONE, WEBAPP_URL
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
from middleware import CallbackAnswerMiddleware, DatabaseMiddleware, TypingMiddleware
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

    # ── Auth helper ───────────────────────────────────────────────────────────
    def _auth(request: web.Request) -> int | None:
        init_data = request.headers.get("X-Init-Data", "")
        return _get_user_id_from_init_data(init_data)

    # ── Handlers ──────────────────────────────────────────────────────────────

    async def api_me(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        student = await db.get_student(user_id)
        if not student:
            return web.json_response({"error": "Not registered"}, status=404)
        return web.json_response({
            "full_name":   student.full_name,
            "group_name":  student.group_name,
            "mars_id":     student.mars_id,
            "registered":  student.registered_at.isoformat() if student.registered_at else None,
            "last_active": student.last_active.isoformat() if student.last_active else None,
        })

    async def api_tomorrow(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        student = await db.get_student(user_id)
        if not student:
            return web.json_response({"error": "Not registered"}, status=404)

        tomorrow = datetime.now(tz) + timedelta(days=1)
        day_num = tomorrow.day
        is_odd = day_num % 2 == 1
        gtype = GroupType.ODD if is_odd else GroupType.EVEN
        groups = await db.get_groups_by_type(gtype)
        lesson_day = is_odd
        return web.json_response({
            "tomorrow":   tomorrow.strftime("%d.%m.%Y"),
            "day_type":   "Toq" if is_odd else "Juft",
            "has_lesson": lesson_day,
        })

    async def api_homework(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        student = await db.get_student(user_id)
        if not student:
            return web.json_response({"error": "Not registered"}, status=404)
        hw = await db.get_homework(student.group_name)
        if not hw:
            return web.json_response({"exists": False})
        return web.json_response({
            "exists":     True,
            "group_name": hw.group_name,
            "sent_at":    hw.sent_at.strftime("%d.%m.%Y %H:%M"),
            "message_id": hw.message_id,
            "chat_id":    hw.from_chat_id,
        })

    async def api_hw_history(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        student = await db.get_student(user_id)
        if not student:
            return web.json_response({"error": "Not registered"}, status=404)
        history = await db.get_homework_history(student.group_name, limit=10)
        return web.json_response({
            "items": [
                {"sent_at": h.sent_at.strftime("%d.%m.%Y %H:%M"), "message_id": h.message_id}
                for h in history
            ]
        })

    async def api_attendance(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        student = await db.get_student(user_id)
        if not student:
            return web.json_response({"error": "Not registered"}, status=404)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Bad JSON"}, status=400)

        status_val = body.get("status")  # "yes" | "no"
        if status_val not in ("yes", "no"):
            return web.json_response({"error": "Invalid status"}, status=400)

        today = datetime.now(tz).strftime("%Y-%m-%d")
        await db.save_attendance(user_id, today, status_val)
        await db.update_last_active(user_id)
        return web.json_response({"ok": True, "date": today, "status": status_val})

    async def api_attendance_today(request: web.Request) -> web.Response:
        """O'quvchining bugungi davomati holatini qaytaradi."""
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        today = datetime.now(tz).strftime("%Y-%m-%d")
        rec = await db.get_student_attendance(user_id, today)
        return web.json_response({
            "date":   today,
            "status": rec.status if rec else None,
        })

    # ── Curator API ───────────────────────────────────────────────────────────

    async def api_curator_me(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        session = await db.get_curator_session(user_id)
        if not session:
            return web.json_response({"logged_in": False})
        c = CURATORS.get(session.curator_key, {})
        return web.json_response({
            "logged_in":  True,
            "curator_key": session.curator_key,
            "full_name":  c.get("full_name", session.curator_key),
            "username":   c.get("telegram_username", ""),
        })

    async def api_curator_login(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Bad JSON"}, status=400)
        login    = (body.get("login") or "").strip().lower()
        password = (body.get("password") or "").strip()
        cred = CURATORS.get(login)
        if not cred or cred["password"] != password:
            return web.json_response({"error": "Login yoki parol noto'g'ri"}, status=403)
        await db.set_curator_session(user_id, login)
        return web.json_response({
            "ok":        True,
            "full_name": cred["full_name"],
            "username":  cred.get("telegram_username", ""),
        })

    async def api_curator_logout(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        await db.remove_curator_session(user_id)
        return web.json_response({"ok": True})

    async def api_curator_students(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        session = await db.get_curator_session(user_id)
        if not session:
            return web.json_response({"error": "Not logged in"}, status=403)
        students = await db.get_all_students()
        return web.json_response({
            "students": [
                {
                    "user_id":    s.user_id,
                    "full_name":  s.full_name,
                    "group_name": s.group_name,
                    "username":   s.telegram_username or "",
                    "last_active": s.last_active.strftime("%d.%m.%Y %H:%M") if s.last_active else None,
                }
                for s in students
            ]
        })

    # ── Curator Attendance API ────────────────────────────────────────────────

    async def api_curator_attendance(request: web.Request) -> web.Response:
        """Bugungi davomat holati — kurator uchun."""
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        session = await db.get_curator_session(user_id)
        if not session:
            return web.json_response({"error": "Not logged in"}, status=403)

        group_filter = request.rel_url.query.get("group", "all")
        today = datetime.now(tz).strftime("%Y-%m-%d")

        all_students = await db.get_all_students()
        if group_filter != "all":
            all_students = [s for s in all_students if s.group_name == group_filter]

        att_records = await db.get_attendance_by_date(today)
        att_map = {r.user_id: r for r in att_records}

        present, absent, pending = [], [], []
        for s in all_students:
            rec = att_map.get(s.user_id)
            entry = {
                "user_id":    s.user_id,
                "full_name":  s.full_name,
                "group_name": s.group_name,
                "username":   s.telegram_username or "",
            }
            if rec is None:
                pending.append(entry)
            elif rec.status == "yes":
                present.append(entry)
            else:
                entry["reason"] = rec.reason or ""
                absent.append(entry)

        return web.json_response({
            "date":    today,
            "present": present,
            "absent":  absent,
            "pending": pending,
        })

    async def api_class_schedule(request: web.Request) -> web.Response:
        """O'quvchi uchun bugungi dars vaqtini qaytaradi."""
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        student = await db.get_student(user_id)
        if not student:
            return web.json_response({"error": "Not registered"}, status=404)

        from class_schedule import CLASS_SCHEDULE

        now     = datetime.now(tz)
        weekday = now.weekday()

        if weekday == 6:
            return web.json_response({"has_class": False, "class_time": None, "group_name": student.group_name})

        day_type = "ODD" if weekday in (0, 2, 4) else "EVEN"
        schedule = CLASS_SCHEDULE.get(day_type, {})
        class_time = schedule.get(student.group_name)

        today_str = now.strftime("%Y-%m-%d")
        rec = await db.get_student_attendance(user_id, today_str)

        return web.json_response({
            "has_class":  class_time is not None,
            "class_time": class_time,
            "group_name": student.group_name,
            "day_type":   day_type,
            "today":      today_str,
            "att_status": rec.status if rec else None,
        })

    # ── OPTIONS preflight ──────────────────────────────────────────────────────
    async def options_handler(request: web.Request) -> web.Response:
        return web.Response(status=204, headers={
            "Access-Control-Allow-Origin":  "*",
            "Access-Control-Allow-Headers": "Content-Type, X-Init-Data",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        })

    # ── Static: webapp/ directory ──────────────────────────────────────────────
    webapp_dir = os.path.join(os.path.dirname(__file__), "webapp")

    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/api/me",               api_me)
    app.router.add_get("/api/tomorrow",         api_tomorrow)
    app.router.add_get("/api/homework",         api_homework)
    app.router.add_get("/api/hw-history",       api_hw_history)
    app.router.add_post("/api/attendance",      api_attendance)
    app.router.add_get("/api/attendance",       api_attendance_today)
    app.router.add_get("/api/curator/me",         api_curator_me)
    app.router.add_post("/api/curator/login",     api_curator_login)
    app.router.add_post("/api/curator/logout",    api_curator_logout)
    app.router.add_get("/api/curator/students",   api_curator_students)
    app.router.add_get("/api/curator/attendance", api_curator_attendance)
    app.router.add_get("/api/class-schedule",     api_class_schedule)
    app.router.add_route("OPTIONS", "/{path_info:.*}", options_handler)
    if os.path.isdir(webapp_dir):
        app.router.add_static("/webapp", webapp_dir, show_index=True)
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
    dp.callback_query.middleware(CallbackAnswerMiddleware())  # Tugma → darhol javob
    dp.message.middleware(TypingMiddleware())                 # Xabar → "yozmoqda..."

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
    scheduler = setup_scheduler(bot=bot, db=db, timezone_str=TIMEZONE)
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
