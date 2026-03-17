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

from config import ADMIN_IDS, BOT_TOKEN, DATABASE_URL, PORT, TIMEZONE, WEBAPP_URL
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
        from config import CHANNEL_LINK
        return web.json_response({
            "full_name":    student.full_name,
            "group_name":   student.group_name,
            "mars_id":      student.mars_id,
            "phone_number": student.phone_number or "",
            "registered":   student.registered_at.isoformat() if student.registered_at else None,
            "last_active":  student.last_active.isoformat() if student.last_active else None,
            "channel_link": CHANNEL_LINK,
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

        reason = body.get("reason") or None  # "no" uchun sabab (ixtiyoriy)

        today = datetime.now(tz).strftime("%Y-%m-%d")
        await db.save_attendance(user_id, today, status_val, reason=reason)
        await db.update_last_active(user_id)

        # Admin + kuratorlarga bildirishnoma
        time_str = datetime.now(tz).strftime("%H:%M")
        if status_val == "yes":
            notify_text = (
                f"✅ <b>{student.full_name}</b> — Boraman (Mini App)\n"
                f"📚 Guruh: <b>{student.group_name}</b>\n"
                f"📅 Kun: {today} | 🕐 {time_str}"
            )
        else:
            notify_text = (
                f"❌ <b>{student.full_name}</b> — Kela olmayman (Mini App)\n"
                f"📚 Guruh: <b>{student.group_name}</b>\n"
                f"📅 Kun: {today} | 🕐 {time_str}\n"
                + (f"💬 Sabab: <i>{reason}</i>" if reason else "")
            )

        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, notify_text)
            except Exception:
                pass

        try:
            from sqlalchemy import select as sa_select
            from database import CuratorSession
            async with db.session_factory() as sess:
                result = await sess.execute(sa_select(CuratorSession))
                curator_sessions = list(result.scalars().all())
            for cs in curator_sessions:
                if cs.telegram_id not in ADMIN_IDS:
                    try:
                        await bot.send_message(cs.telegram_id, notify_text)
                    except Exception:
                        pass
        except Exception:
            pass

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

    async def api_curator_all_students(request: web.Request) -> web.Response:
        """MARS_CREDENTIALS dagi barcha o'quvchilar (ro'yxatdan o'tgan + o'tmagan)."""
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        session = await db.get_curator_session(user_id)
        if not session:
            return web.json_response({"error": "Not logged in"}, status=403)

        from credentials import MARS_CREDENTIALS
        registered = await db.get_all_students()
        reg_map    = {s.mars_id: s for s in registered if s.mars_id}

        result = []
        for mars_id, cred in MARS_CREDENTIALS.items():
            reg = reg_map.get(mars_id)
            result.append({
                "mars_id":    mars_id,
                "full_name":  cred["name"],
                "group_name": cred["group"],
                "registered": reg is not None,
                "user_id":    reg.user_id if reg else None,
                "username":   reg.telegram_username if reg else None,
                "last_active": reg.last_active.strftime("%d.%m.%Y %H:%M") if reg and reg.last_active else None,
            })

        result.sort(key=lambda x: (x["group_name"], x["full_name"]))
        return web.json_response({"students": result})

    # ── Admin API ─────────────────────────────────────────────────────────────

    def _admin_auth(request: web.Request) -> int | None:
        uid = _auth(request)
        return uid if uid and uid in ADMIN_IDS else None

    async def api_admin_me(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        return web.json_response({"ok": True, "user_id": user_id})

    async def api_admin_stats(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        today     = datetime.now(tz).strftime("%Y-%m-%d")
        students  = await db.get_all_students()
        groups    = await db.get_all_groups()
        att_recs  = await db.get_attendance_by_date(today)

        present = sum(1 for r in att_recs if r.status == "yes")
        absent  = sum(1 for r in att_recs if r.status == "no")

        return web.json_response({
            "total_students":  len(students),
            "active_groups":   sum(1 for g in groups if g.is_active),
            "total_groups":    len(groups),
            "today_present":   present,
            "today_absent":    absent,
            "today_pending":   len(students) - present - absent,
            "today":           today,
        })

    async def api_admin_students(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        today    = datetime.now(tz).strftime("%Y-%m-%d")
        students = await db.get_all_students()
        att_recs = await db.get_attendance_by_date(today)
        att_map  = {r.user_id: r.status for r in att_recs}

        return web.json_response({
            "students": [
                {
                    "user_id":    s.user_id,
                    "full_name":  s.full_name,
                    "group_name": s.group_name,
                    "mars_id":    s.mars_id,
                    "username":   s.telegram_username or "",
                    "phone":      s.phone_number or "",
                    "last_active": s.last_active.strftime("%d.%m.%Y %H:%M") if s.last_active else None,
                    "att_today":  att_map.get(s.user_id),
                }
                for s in students
            ]
        })

    async def api_admin_attendance(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        today    = datetime.now(tz).strftime("%Y-%m-%d")
        students = await db.get_all_students()
        att_recs = await db.get_attendance_by_date(today)
        att_map  = {r.user_id: r for r in att_recs}

        present, absent, pending = [], [], []
        for s in students:
            entry = {
                "user_id":    s.user_id,
                "full_name":  s.full_name,
                "group_name": s.group_name,
                "username":   s.telegram_username or "",
            }
            rec = att_map.get(s.user_id)
            if rec is None:
                pending.append(entry)
            elif rec.status == "yes":
                present.append(entry)
            else:
                entry["reason"] = rec.reason or ""
                absent.append(entry)

        return web.json_response({
            "date": today, "present": present, "absent": absent, "pending": pending,
        })

    async def api_admin_all_students(request: web.Request) -> web.Response:
        """MARS_CREDENTIALS dagi barcha o'quvchilar (ro'yxatdan o'tgan + o'tmagan) — admin uchun."""
        user_id = _admin_auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        from credentials import MARS_CREDENTIALS

        today      = datetime.now(tz).strftime("%Y-%m-%d")
        registered = await db.get_all_students()
        att_recs   = await db.get_attendance_by_date(today)

        reg_map = {s.mars_id: s for s in registered if s.mars_id}
        att_map = {r.user_id: r.status for r in att_recs}

        result = []
        for mars_id, cred in MARS_CREDENTIALS.items():
            reg = reg_map.get(mars_id)
            result.append({
                "mars_id":    mars_id,
                "full_name":  cred["name"],
                "group_name": cred["group"],
                "registered": reg is not None,
                "user_id":    reg.user_id if reg else None,
                "username":   reg.telegram_username if reg else None,
                "phone":      reg.phone_number if reg else None,
                "last_active": reg.last_active.strftime("%d.%m.%Y %H:%M") if reg and reg.last_active else None,
                "att_today":  att_map.get(reg.user_id) if reg else None,
            })

        result.sort(key=lambda x: (x["group_name"], x["full_name"]))
        return web.json_response({"students": result})

    async def api_admin_groups(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        groups = await db.get_all_groups()
        return web.json_response({
            "groups": [
                {
                    "id":         g.id,
                    "chat_id":    g.chat_id,
                    "name":       g.name,
                    "group_type": g.group_type.value,
                    "audience":   g.audience.value,
                    "is_active":  g.is_active,
                }
                for g in groups
            ]
        })

    async def api_admin_groups_detail(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        from class_schedule import CLASS_SCHEDULE

        groups   = await db.get_all_groups()
        students = await db.get_all_students()

        student_count: dict[str, int] = {}
        for s in students:
            student_count[s.group_name] = student_count.get(s.group_name, 0) + 1

        hw_map: dict[str, str] = {}
        for gname in {s.group_name for s in students}:
            hw = await db.get_homework(gname)
            if hw:
                hw_map[gname] = hw.sent_at.strftime("%d.%m.%Y %H:%M")

        result = []
        for g in groups:
            day_type   = g.group_type.value
            class_time = CLASS_SCHEDULE.get(day_type, {}).get(g.name)
            result.append({
                "id":            g.id,
                "chat_id":       g.chat_id,
                "name":          g.name,
                "group_type":    day_type,
                "audience":      g.audience.value,
                "is_active":     g.is_active,
                "class_time":    class_time,
                "student_count": student_count.get(g.name, 0),
                "has_homework":  g.name in hw_map,
                "hw_sent_at":    hw_map.get(g.name),
            })

        return web.json_response({"groups": result})

    async def api_admin_toggle_group(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Bad JSON"}, status=400)
        chat_id  = body.get("chat_id")
        is_active = body.get("is_active")
        if chat_id is None or is_active is None:
            return web.json_response({"error": "Missing fields"}, status=400)
        await db.set_group_active(int(chat_id), bool(is_active))
        return web.json_response({"ok": True})

    async def api_admin_hw_schedule(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)

        from class_schedule import CLASS_SCHEDULE

        students = await db.get_all_students()
        unique_groups = sorted({s.group_name for s in students})

        result = []
        for gname in unique_groups:
            hw        = await db.get_homework(gname)
            odd_time  = CLASS_SCHEDULE.get("ODD",  {}).get(gname)
            even_time = CLASS_SCHEDULE.get("EVEN", {}).get(gname)
            day_type  = "ODD" if odd_time else ("EVEN" if even_time else None)
            class_time = odd_time or even_time
            cnt = sum(1 for s in students if s.group_name == gname)
            result.append({
                "group_name":    gname,
                "day_type":      day_type,
                "class_time":    class_time,
                "student_count": cnt,
                "has_homework":  hw is not None,
                "hw_sent_at":    hw.sent_at.strftime("%d.%m.%Y %H:%M") if hw else None,
            })

        result.sort(key=lambda x: (x.get("day_type") or "ZZ", x.get("class_time") or ""))
        return web.json_response({
            "groups":     result,
            "odd_days":   "Dushanba, Chorshanba, Juma",
            "even_days":  "Seshanba, Payshanba, Shanba",
        })

    async def api_admin_broadcast(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Bad JSON"}, status=400)

        text   = (body.get("text") or "").strip()
        target = body.get("target", "all")
        if not text:
            return web.json_response({"error": "Empty message"}, status=400)

        ok = fail = 0
        if target == "parents":
            from database import AudienceType as AT
            all_groups = await db.get_all_groups()
            for g in all_groups:
                if g.audience == AT.PARENT and g.is_active:
                    try:
                        await bot.send_message(g.chat_id, text)
                        ok += 1
                    except Exception:
                        fail += 1
        elif target == "students_group":
            all_groups = await db.get_all_groups()
            from database import AudienceType as AT
            for g in all_groups:
                if g.audience == AT.STUDENT and g.is_active:
                    try:
                        await bot.send_message(g.chat_id, text)
                        ok += 1
                    except Exception:
                        fail += 1
        else:
            if target == "all":
                students = await db.get_all_students()
            else:
                students = await db.get_students_by_group(target)
            for s in students:
                try:
                    await bot.send_message(s.user_id, text)
                    ok += 1
                except Exception:
                    fail += 1

        return web.json_response({"ok": True, "sent": ok, "failed": fail})

    async def api_admin_reminder_get(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        h = await db.get_setting("SEND_HOUR",   str(SEND_HOUR))
        m = await db.get_setting("SEND_MINUTE", str(SEND_MINUTE))
        return web.json_response({"hour": int(h), "minute": int(m)})

    async def api_admin_reminder_set(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Bad JSON"}, status=400)
        hour   = body.get("hour")
        minute = body.get("minute")
        if hour is None or minute is None:
            return web.json_response({"error": "Missing fields"}, status=400)
        hour, minute = int(hour), int(minute)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return web.json_response({"error": "Invalid time"}, status=400)
        await db.set_setting("SEND_HOUR",   str(hour))
        await db.set_setting("SEND_MINUTE", str(minute))
        from scheduler import reschedule_reminder
        reschedule_reminder(hour, minute)
        return web.json_response({"ok": True, "hour": hour, "minute": minute})

    async def api_admin_inactive(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        days    = int(request.rel_url.query.get("days", "7"))
        inactive = await db.get_inactive_students(days=days)
        return web.json_response({
            "days": days,
            "students": [
                {
                    "user_id":    s.user_id,
                    "full_name":  s.full_name,
                    "group_name": s.group_name,
                    "username":   s.telegram_username or "",
                    "last_active": s.last_active.strftime("%d.%m.%Y %H:%M") if s.last_active else None,
                }
                for s in inactive
            ],
        })

    async def api_admin_test_send(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            from scheduler import send_daily_reminders
            asyncio.create_task(send_daily_reminders(bot=bot, db=db, timezone_str=TIMEZONE))
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def api_admin_curator_stats(request: web.Request) -> web.Response:
        """Admin: kuratorlar ro'yxati va aktivlik statistikasi."""
        user_id = _admin_auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        from curator_credentials import CURATORS
        sessions = await db.get_all_curator_sessions()
        sess_map = {cs.telegram_id: cs for cs in sessions}
        result = []
        for key, info in CURATORS.items():
            # Faol sessionlarda bu kuratorning telegram_id sini qidirmaymiz (key orqali)
            matched = [cs for cs in sessions if cs.curator_key == key]
            if matched:
                cs = matched[0]
                result.append({
                    "key":         key,
                    "full_name":   info.get("full_name", key),
                    "logged_in":   True,
                    "telegram_id": cs.telegram_id,
                    "logged_in_at": cs.logged_in_at.isoformat() if cs.logged_in_at else None,
                    "last_active": cs.last_active.isoformat() if cs.last_active else None,
                })
            else:
                result.append({
                    "key":         key,
                    "full_name":   info.get("full_name", key),
                    "logged_in":   False,
                    "telegram_id": None,
                    "logged_in_at": None,
                    "last_active":  None,
                })
        return web.json_response(result)

    async def api_admin_button_stats(request: web.Request) -> web.Response:
        """Admin: eng ko'p bosilgan tugmalar statistikasi."""
        user_id = _admin_auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        stats = await db.get_button_stats(limit=30)
        return web.json_response([
            {
                "button_name": s.button_name,
                "count":       s.count,
                "last_used":   s.last_used.isoformat() if s.last_used else None,
            }
            for s in stats
        ])

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

    async def api_curator_parent_groups(request: web.Request) -> web.Response:
        """Kurator uchun ota-ona guruhlar ro'yxati."""
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        session = await db.get_curator_session(user_id)
        if not session:
            return web.json_response({"error": "Not logged in"}, status=403)
        from database import AudienceType
        all_groups    = await db.get_all_groups()
        parent_groups = [
            {"chat_id": g.chat_id, "name": g.name}
            for g in all_groups if g.audience == AudienceType.PARENT and g.is_active
        ]
        return web.json_response({"groups": parent_groups})

    async def api_curator_send_yoqlama(request: web.Request) -> web.Response:
        """Davomat yoqlamasini ota-ona guruhiga yuboradi (Mini App dan)."""
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        session = await db.get_curator_session(user_id)
        if not session:
            return web.json_response({"error": "Not logged in"}, status=403)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Bad JSON"}, status=400)
        group_name      = body.get("group_name", "—")
        marks           = body.get("marks", [])   # [{"full_name": "...", "present": true}]
        parent_chat_id  = body.get("parent_chat_id")
        date_str        = body.get("date_str", datetime.now(tz).strftime("%Y-%m-%d"))
        if not parent_chat_id or not marks:
            return web.json_response({"error": "Missing fields"}, status=400)
        cname = CURATORS.get(session.curator_key, {}).get("full_name", session.curator_key)
        try:
            y, m, d = date_str.split("-")
            date_fmt = f"{d}.{m}.{y}"
        except Exception:
            date_fmt = date_str
        lines = [f"{cname} | MARS IT", f"{date_fmt}", "📌Davomat", ""]
        for mark in marks:
            emoji = "✅" if mark.get("present") else "❌"
            lines.append(f"{mark.get('full_name', '—')} {emoji}")
        try:
            await bot.send_message(int(parent_chat_id), "\n".join(lines))
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def api_curator_update_attendance(request: web.Request) -> web.Response:
        """Kurator kechikkan o'quvchining davomatini yangilaydi (Mini App dan)."""
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        session = await db.get_curator_session(user_id)
        if not session:
            return web.json_response({"error": "Not logged in"}, status=403)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Bad JSON"}, status=400)

        student_id = body.get("user_id")
        date_str   = body.get("date_str")
        new_status = body.get("status")

        if not student_id or not date_str or new_status not in ("yes", "no"):
            return web.json_response({"error": "Missing or invalid fields"}, status=400)

        student = await db.get_student(int(student_id))
        if not student:
            return web.json_response({"error": "Student not found"}, status=404)

        await db.save_attendance(int(student_id), date_str, new_status)

        old_emoji = "❌" if new_status == "yes" else "✅"
        new_emoji = "✅" if new_status == "yes" else "❌"
        cname = CURATORS.get(session.curator_key, {}).get("full_name", session.curator_key)
        notify = (
            f"✏️ <b>Davomat o'zgartirildi</b>\n\n"
            f"👤 {student.full_name} ({student.group_name})\n"
            f"📅 Sana: {date_str}\n"
            f"{old_emoji} → {new_emoji}\n"
            f"👩‍💼 Kurator: {cname} (Mini App)"
        )

        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, notify)
            except Exception:
                pass

        try:
            from sqlalchemy import select as sa_select
            from database import CuratorSession
            async with db.session_factory() as sess:
                result = await sess.execute(sa_select(CuratorSession))
                curator_sessions = list(result.scalars().all())
            for cs in curator_sessions:
                if cs.telegram_id != user_id and cs.telegram_id not in ADMIN_IDS:
                    try:
                        await bot.send_message(cs.telegram_id, notify)
                    except Exception:
                        pass
        except Exception:
            pass

        return web.json_response({"ok": True})

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
    app.router.add_get("/api/admin/me",           api_admin_me)
    app.router.add_get("/api/admin/stats",        api_admin_stats)
    app.router.add_get("/api/admin/students",         api_admin_students)
    app.router.add_get("/api/admin/all-students",    api_admin_all_students)
    app.router.add_get("/api/admin/attendance",   api_admin_attendance)
    app.router.add_get("/api/admin/groups",            api_admin_groups)
    app.router.add_get("/api/admin/groups-detail",     api_admin_groups_detail)
    app.router.add_post("/api/admin/toggle-group",     api_admin_toggle_group)
    app.router.add_get("/api/admin/hw-schedule",       api_admin_hw_schedule)
    app.router.add_post("/api/admin/broadcast",        api_admin_broadcast)
    app.router.add_get("/api/admin/reminder-time",     api_admin_reminder_get)
    app.router.add_post("/api/admin/reminder-time",    api_admin_reminder_set)
    app.router.add_get("/api/admin/inactive",          api_admin_inactive)
    app.router.add_post("/api/admin/test-send",        api_admin_test_send)
    app.router.add_get("/api/admin/curator-stats",     api_admin_curator_stats)
    app.router.add_get("/api/admin/button-stats",      api_admin_button_stats)
    app.router.add_get("/api/curator/me",         api_curator_me)
    app.router.add_post("/api/curator/login",     api_curator_login)
    app.router.add_post("/api/curator/logout",    api_curator_logout)
    app.router.add_get("/api/curator/students",       api_curator_students)
    app.router.add_get("/api/curator/all-students",  api_curator_all_students)
    app.router.add_get("/api/curator/attendance",     api_curator_attendance)
    app.router.add_get("/api/curator/parent-groups",         api_curator_parent_groups)
    app.router.add_post("/api/curator/send-yoqlama",         api_curator_send_yoqlama)
    app.router.add_post("/api/curator/update-attendance",    api_curator_update_attendance)
    app.router.add_get("/api/class-schedule",                api_class_schedule)
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
