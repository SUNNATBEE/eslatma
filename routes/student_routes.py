"""
routes/student_routes.py — Talaba API endpointlari
Endpointlar: /api/me, /api/student/*, /api/referral/*, /api/chat, /api/class-schedule, /api/public/*
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta

from aiohttp import web

from config import ADMIN_IDS, CHANNEL_LINK
from utils import is_hashed_secret, verify_secret

logger = logging.getLogger(__name__)


def _normalize_mars_id(raw: str) -> str:
    value = (raw or "").strip()
    upper = value.upper()
    if upper.startswith("P") and len(upper) >= 2 and upper[1:].isdigit():
        return upper
    return value


async def _send_notification(bot, chat_id: int, text: str, *, context: str) -> None:
    try:
        await bot.send_message(chat_id, text)
    except Exception:
        logger.warning("Notification yuborilmadi | context=%s chat_id=%s", context, chat_id, exc_info=True)


def setup_student_routes(app: web.Application, ctx: dict) -> None:
    """Talaba endpointlarini ro'yxatdan o'tkazadi."""
    bot              = ctx["bot"]
    db               = ctx["db"]
    tz               = ctx["tz"]
    _auth            = ctx["auth"]
    _mini_admin_auth = ctx["mini_admin_auth"]
    _notify_level_up = ctx["notify_level_up"]
    _get_user_id     = ctx["get_user_id"]
    _verify_init_data = ctx["verify_init_data"]

    # ── Basic student routes ──────────────────────────────────────────────────

    async def api_me(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        student = await db.get_student(user_id)
        if not student:
            return web.json_response({"error": "Not registered"}, status=404)
        return web.json_response({
            "full_name":    student.full_name,
            "group_name":   student.group_name,
            "mars_id":      student.mars_id,
            "phone_number": student.phone_number or "",
            "avatar_emoji": student.avatar_emoji or "",
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
        from class_schedule import CLASS_SCHEDULE

        if tomorrow.weekday() == 6:
            return web.json_response({
                "tomorrow": tomorrow.strftime("%d.%m.%Y"),
                "day_type": None,
                "has_lesson": False,
                "class_time": None,
                "group_name": student.group_name,
            })

        day_type = "ODD" if tomorrow.weekday() in (0, 2, 4) else "EVEN"
        class_time = CLASS_SCHEDULE.get(day_type, {}).get(student.group_name)
        return web.json_response({
            "tomorrow": tomorrow.strftime("%d.%m.%Y"),
            "day_type": "Toq" if day_type == "ODD" else "Juft",
            "has_lesson": class_time is not None,
            "class_time": class_time,
            "group_name": student.group_name,
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
        status_val = body.get("status")
        if status_val not in ("yes", "no"):
            return web.json_response({"error": "Invalid status"}, status=400)
        reason = body.get("reason") or None
        today  = datetime.now(tz).strftime("%Y-%m-%d")
        await db.save_attendance(user_id, today, status_val, reason=reason)
        await db.update_last_active(user_id)
        if status_val == "yes":
            _, _, lvup, _ = await db.add_xp(user_id, 10)
            if lvup:
                student2 = await db.get_student(user_id)
                if student2:
                    asyncio.create_task(_notify_level_up(user_id, student2.level))
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
            await _send_notification(bot, admin_id, notify_text, context="attendance:admin")
        try:
            from sqlalchemy import select as sa_select

            from database import CuratorSession
            async with db.session_factory() as sess:
                result = await sess.execute(sa_select(CuratorSession))
                curator_sessions = list(result.scalars().all())
            for cs in curator_sessions:
                if cs.telegram_id not in ADMIN_IDS:
                    await _send_notification(bot, cs.telegram_id, notify_text, context="attendance:curator")
        except Exception:
            logger.warning("Curator sessionlarini yuklash yoki notify yuborish muvaffaqiyatsiz", exc_info=True)
        return web.json_response({"ok": True, "date": today, "status": status_val})

    async def api_attendance_today(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        today = datetime.now(tz).strftime("%Y-%m-%d")
        rec = await db.get_student_attendance(user_id, today)
        return web.json_response({
            "date":   today,
            "status": rec.status if rec else None,
        })

    async def api_class_schedule(request: web.Request) -> web.Response:
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
        day_type   = "ODD" if weekday in (0, 2, 4) else "EVEN"
        schedule   = CLASS_SCHEDULE.get(day_type, {})
        class_time = schedule.get(student.group_name)
        today_str  = now.strftime("%Y-%m-%d")
        rec = await db.get_student_attendance(user_id, today_str)
        return web.json_response({
            "has_class":  class_time is not None,
            "class_time": class_time,
            "group_name": student.group_name,
            "day_type":   day_type,
            "today":      today_str,
            "att_status": rec.status if rec else None,
        })

    # ── Public ────────────────────────────────────────────────────────────────

    async def api_public_groups(request: web.Request) -> web.Response:
        from credentials import MARS_GROUPS
        return web.json_response({"groups": MARS_GROUPS})

    # ── Student Registration ───────────────────────────────────────────────────

    async def api_student_register(request: web.Request) -> web.Response:
        user_id = _get_user_id(request.headers.get("X-Init-Data", ""))
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Bad JSON"}, status=400)
        mars_id    = _normalize_mars_id(body.get("mars_id") or "")
        password   = (body.get("password")   or "").strip()
        phone      = (body.get("phone")      or "").strip()
        group_name = (body.get("group_name") or "").strip()
        if not mars_id or not password or not phone or not group_name:
            return web.json_response({"error": "Barcha maydonlarni to'ldiring"}, status=400)
        if not (mars_id.isdigit() or (mars_id.startswith("P") and mars_id[1:].isdigit())):
            return web.json_response({"error": "Mars ID faqat raqam yoki P12345 formatida bo'lishi kerak"}, status=400)
        if not re.fullmatch(r"\+998\d{9}", phone):
            return web.json_response({"error": "Telefon formati: +998901234567"}, status=400)
        from credentials import MARS_CREDENTIALS
        cred = MARS_CREDENTIALS.get(mars_id)
        db_cred = None
        if not cred:
            db_cred = await db.get_student_credential(mars_id)
            if db_cred:
                cred = {"password": db_cred.password, "name": db_cred.name, "group": db_cred.group_name}
        if not cred:
            return web.json_response({"error": "Bu Mars ID topilmadi"}, status=403)
        if not verify_secret(cred["password"], password):
            return web.json_response({"error": "Parol noto'g'ri"}, status=403)
        if db_cred and not is_hashed_secret(db_cred.password):
            await db.upgrade_student_credential_password(mars_id, password)
        if cred["group"] != group_name:
            return web.json_response({
                "error": f"Sizning guruhingiz: {cred['group']}. {group_name} ni tanlamang."
            }, status=403)
        existing = await db.get_student_by_mars_id(mars_id)
        if existing and existing.user_id != user_id:
            return web.json_response({
                "error": "Bu Mars ID boshqa Telegram akkountda ro'yxatdan o'tilgan. Admin bilan bog'laning."
            }, status=409)
        parsed   = _verify_init_data(request.headers.get("X-Init-Data", ""))
        tg_udata = json.loads(parsed.get("user", "{}")) if parsed else {}
        tg_un    = f"@{tg_udata['username']}" if tg_udata.get("username") else str(user_id)
        _student, is_new = await db.register_student(
            user_id=user_id, telegram_username=tg_un,
            full_name=cred["name"], mars_id=mars_id,
            group_name=group_name, phone_number=phone,
        )
        notif_header = (
            "🔔 <b>Yangi o'quvchi (Mini App)</b>"
            if is_new
            else "🔄 <b>Mavjud o'quvchi qayta kirdi (Mini App)</b>"
        )
        notify = (
            f"{notif_header}\n\n"
            f"👤 {cred['name']}\n"
            f"📚 Guruh: {group_name}\n"
            f"🆔 Mars ID: <code>{mars_id}</code>\n"
            f"📱 Telefon: <code>{phone}</code>\n"
            f"💬 {tg_un}"
        )
        for admin_id in ADMIN_IDS:
            await _send_notification(bot, admin_id, notify, context="student-register:admin")
        return web.json_response({"ok": True, "full_name": cred["name"], "group_name": group_name, "is_new": is_new})

    # ── Student Gamification ───────────────────────────────────────────────────

    async def api_student_checkin(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        student = await db.get_student(user_id)
        if not student:
            return web.json_response({"error": "Not registered"}, status=404)
        result = await db.daily_checkin(user_id)
        if result.get("leveled_up"):
            asyncio.create_task(_notify_level_up(user_id, result["new_level"]))
        return web.json_response(result)

    async def api_student_progress(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        student = await db.get_student(user_id)
        if not student:
            return web.json_response({"error": "Not registered"}, status=404)
        from database import _level_name, _next_level_xp
        attend_count  = await db.get_attend_yes_count(user_id)
        hw_conf_count = await db.get_hw_confirm_count(user_id)
        rank          = await db.get_student_rank(user_id, student.group_name)
        today_str     = datetime.now(tz).strftime("%Y-%m-%d")
        mood          = await db.get_mood(user_id, today_str)
        cur_xp    = student.xp    or 0
        cur_level = student.level or 1
        nx_xp     = _next_level_xp(cur_level)
        return web.json_response({
            "xp":            cur_xp,
            "level":         cur_level,
            "level_name":    _level_name(cur_level),
            "next_level_xp": nx_xp,
            "streak_days":   student.streak_days or 0,
            "attend_count":  attend_count,
            "hw_conf_count": hw_conf_count,
            "rank":          rank,
            "mood_today":    mood,
        })

    async def api_student_leaderboard(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        student = await db.get_student(user_id)
        if not student:
            return web.json_response({"error": "Not registered"}, status=404)
        from database import _level_name
        leaders = await db.get_leaderboard(student.group_name, limit=20)
        result = []
        for i, s in enumerate(leaders):
            result.append({
                "rank":       i + 1,
                "user_id":    s.user_id,
                "full_name":  s.full_name,
                "group_name": s.group_name,
                "xp":         s.xp or 0,
                "level":      s.level or 1,
                "level_name": _level_name(s.level or 1),
                "streak":     s.streak_days or 0,
                "is_me":      s.user_id == user_id,
                "avatar":     s.avatar_emoji or "",
            })
        return web.json_response({"group_name": student.group_name, "leaders": result})

    async def api_student_mood(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        today_str = datetime.now(tz).strftime("%Y-%m-%d")
        if request.method == "POST":
            try:
                body = await request.json()
            except Exception:
                return web.json_response({"error": "Bad JSON"}, status=400)
            mood = body.get("mood")
            if mood not in ("happy", "ok", "sad"):
                return web.json_response({"error": "Invalid mood"}, status=400)
            await db.save_mood(user_id, today_str, mood)
            return web.json_response({"ok": True, "mood": mood})
        else:
            mood = await db.get_mood(user_id, today_str)
            return web.json_response({"mood": mood})

    async def api_student_hw_confirm(request: web.Request) -> web.Response:
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
        date_str = body.get("date_str")
        if not date_str:
            return web.json_response({"error": "Missing date_str"}, status=400)
        is_new = await db.confirm_homework(user_id, date_str)
        if is_new:
            new_xp, new_level, lvup, _ = await db.add_xp(user_id, 15)
            if lvup:
                asyncio.create_task(_notify_level_up(user_id, new_level))
            return web.json_response({
                "ok": True, "xp_gained": 15,
                "new_xp": new_xp, "new_level": new_level,
                "leveled_up": lvup,
            })
        return web.json_response({"ok": True, "xp_gained": 0, "already_confirmed": True})

    async def api_student_hw_confirm_status(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        date_str = request.rel_url.query.get("date_str", "")
        if not date_str:
            return web.json_response({"confirmed": False})
        confirmed = await db.is_hw_confirmed(user_id, date_str)
        return web.json_response({"confirmed": confirmed})

    async def api_student_profile(request: web.Request) -> web.Response:
        viewer_id = _auth(request)
        if not viewer_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        viewer = await db.get_student(viewer_id)
        if not viewer:
            return web.json_response({"error": "Not registered"}, status=404)
        try:
            target_id = int(request.match_info["user_id"])
        except Exception:
            return web.json_response({"error": "Invalid user_id"}, status=400)
        target = await db.get_student(target_id)
        if not target:
            return web.json_response({"error": "Student not found"}, status=404)
        from database import _level_name
        attend_count  = await db.get_attend_yes_count(target_id)
        hw_conf_count = await db.get_hw_confirm_count(target_id)
        rank          = await db.get_student_rank(target_id, target.group_name)
        best_scores   = await db.get_game_best_scores(target_id)
        return web.json_response({
            "user_id":     target.user_id,
            "full_name":   target.full_name,
            "group_name":  target.group_name,
            "avatar_emoji": target.avatar_emoji or "",
            "xp":          target.xp or 0,
            "level":       target.level or 1,
            "level_name":  _level_name(target.level or 1),
            "streak_days": target.streak_days or 0,
            "attend_count": attend_count,
            "hw_conf_count": hw_conf_count,
            "rank":        rank,
            "game_best":   best_scores,
            "is_me":       target_id == viewer_id,
        })

    async def api_student_logout(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        student = await db.get_student(user_id)
        if not student:
            return web.json_response({"error": "Not registered"}, status=404)
        name  = student.full_name
        group = student.group_name
        await db.delete_student(user_id)
        notif = (
            f"🚪 <b>O'quvchi akkountdan chiqdi</b>\n\n"
            f"👤 {name}\n📚 Guruh: {group}\n🆔 TG: <code>{user_id}</code>"
        )
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, notif, parse_mode="HTML")
            except Exception:
                pass
        return web.json_response({"ok": True})

    async def api_student_leaderboard_global(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request) or _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        from database import _level_name
        leaders = await db.get_global_leaderboard(limit=50)
        result = []
        for i, s in enumerate(leaders):
            result.append({
                "rank":       i + 1,
                "user_id":    s.user_id,
                "full_name":  s.full_name,
                "group_name": s.group_name,
                "xp":         s.xp or 0,
                "level":      s.level or 1,
                "level_name": _level_name(s.level or 1),
                "streak":     s.streak_days or 0,
                "is_me":      s.user_id == user_id,
                "avatar":     s.avatar_emoji or "",
            })
        return web.json_response({"leaders": result, "total": len(result)})

    async def api_student_avatar(request: web.Request) -> web.Response:
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
        avatar = (body.get("avatar") or "").strip()
        if not avatar:
            return web.json_response({"error": "Avatar bo'sh bo'lmasin"}, status=400)
        await db.set_avatar(user_id, avatar)
        return web.json_response({"ok": True, "avatar": avatar})

    # ── Chat ──────────────────────────────────────────────────────────────────

    async def api_chat_get(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        student = await db.get_student(user_id)
        if not student:
            return web.json_response({"error": "Not registered"}, status=404)
        try:
            after_id = int(request.rel_url.query.get("after_id", "0"))
        except (ValueError, TypeError):
            after_id = 0
        msgs = await db.get_chat_messages(limit=50, after_id=after_id)
        return web.json_response({
            "messages": [
                {
                    "id":         m.id,
                    "user_id":    m.user_id,
                    "full_name":  m.full_name,
                    "group_name": m.group_name,
                    "avatar":     m.avatar or "",
                    "text":       m.text,
                    "time":       m.created_at.strftime("%H:%M") if m.created_at else "",
                    "is_me":      m.user_id == user_id,
                }
                for m in msgs
            ]
        })

    async def api_chat_post(request: web.Request) -> web.Response:
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
        text = (body.get("text") or "").strip()
        if not text:
            return web.json_response({"error": "Xabar bo'sh bo'lmasin"}, status=400)
        if len(text) > 500:
            return web.json_response({"error": "Xabar 500 belgidan oshmasin"}, status=400)
        msg = await db.add_chat_message(
            user_id=user_id, full_name=student.full_name,
            group_name=student.group_name, avatar=student.avatar_emoji,
            text=text,
        )
        await db.update_last_active(user_id)
        return web.json_response({
            "ok": True,
            "message": {
                "id":         msg.id,
                "user_id":    msg.user_id,
                "full_name":  msg.full_name,
                "group_name": msg.group_name,
                "avatar":     msg.avatar or "",
                "text":       msg.text,
                "time":       msg.created_at.strftime("%H:%M") if msg.created_at else "",
                "is_me":      True,
            }
        })

    # ── Leaderboards (group / monthly) ────────────────────────────────────────

    async def api_student_leaderboard_group(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        from database import _level_name
        student = await db.get_student(user_id)
        if not student:
            return web.json_response({"error": "Not registered"}, status=404)
        group_name = student.group_name or ""
        leaders = await db.get_group_leaderboard(group_name, limit=20)
        result = []
        for i, s in enumerate(leaders):
            result.append({
                "rank":       i + 1,
                "user_id":    s.user_id,
                "full_name":  s.full_name,
                "group_name": s.group_name,
                "xp":         s.xp or 0,
                "level":      s.level or 1,
                "level_name": _level_name(s.level or 1),
                "streak":     s.streak_days or 0,
                "is_me":      s.user_id == user_id,
                "avatar":     s.avatar_emoji or "",
            })
        return web.json_response({"leaders": result, "group_name": group_name})

    async def api_student_leaderboard_monthly(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request) or _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        import pytz as _pytz

        from config import TIMEZONE as _TZ
        _tz = _pytz.timezone(_TZ)
        year_month = datetime.now(_tz).strftime("%Y-%m")
        leaders = await db.get_monthly_leaderboard(year_month, limit=50)
        for i, row in enumerate(leaders):
            row["rank"]  = i + 1
            row["is_me"] = (row.get("user_id") == user_id)
        return web.json_response({"leaders": leaders, "year_month": year_month})

    # ── Referral ──────────────────────────────────────────────────────────────

    async def api_student_referral(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        bot_info = await bot.get_me()
        bot_name = bot_info.username
        link     = f"https://t.me/{bot_name}?start=ref_{user_id}"
        invited  = await db.get_my_referrals(user_id)
        xp_total = sum(500 for r in invited if r.xp_awarded)
        return web.json_response({
            "code":            str(user_id),
            "link":            link,
            "invited_count":   len(invited),
            "xp_earned_total": xp_total,
        })

    async def api_student_referral_invited(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        invited = await db.get_my_referrals(user_id)
        return web.json_response({
            "invited": [
                {
                    "name":     r.full_name,
                    "status":   r.status,
                    "joined_at": r.created_at.strftime("%d.%m.%Y") if r.created_at else "",
                }
                for r in invited
            ]
        })

    async def api_referral_register(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Bad JSON"}, status=400)
        ref_code         = (body.get("ref_code") or "").strip()
        full_name        = (body.get("full_name") or "").strip()
        age              = (body.get("age") or "").strip()
        location         = (body.get("location") or "").strip()
        interests        = (body.get("interests") or "").strip()
        phone            = (body.get("phone") or "").strip()
        telegram_user_id = body.get("telegram_user_id")
        if not all([ref_code, full_name, age, location, interests, phone]):
            return web.json_response({"error": "Barcha maydonlarni to'ldiring"}, status=400)
        try:
            referrer_user_id = int(ref_code)
        except ValueError:
            return web.json_response({"error": "Noto'g'ri referal kod"}, status=400)
        rs = await db.create_referral_student({
            "referrer_user_id": referrer_user_id,
            "telegram_user_id": int(telegram_user_id) if telegram_user_id else None,
            "full_name":        full_name,
            "age":              age,
            "location":         location,
            "interests":        interests,
            "phone":            phone,
        })
        notif = (
            f"🔗 <b>Yangi referal o'quvchi</b>\n\n"
            f"👤 {full_name} | Yosh: {age}\n"
            f"📍 Joylashuv: {location}\n"
            f"💡 Qiziqishlari: {interests}\n"
            f"📱 Telefon: {phone}\n"
            f"🆔 Taklif qilgan: <code>{referrer_user_id}</code>\n"
            f"✅ Admin Mini App da tasdiqlang (Referal tab)"
        )
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, notif, parse_mode="HTML")
            except Exception:
                pass
        return web.json_response({"ok": True, "id": rs.id})

    async def api_student_pending_register(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Bad JSON"}, status=400)
        full_name        = (body.get("full_name") or "").strip()
        age              = (body.get("age") or "").strip()
        location         = (body.get("location") or "").strip()
        interests        = (body.get("interests") or "").strip()
        phone            = (body.get("phone") or "").strip()
        telegram_user_id = body.get("telegram_user_id")
        has_group        = bool(body.get("has_group", False))
        group_time       = (body.get("group_time") or "").strip() or None
        group_day_type   = (body.get("group_day_type") or "").strip() or None
        teacher_name     = (body.get("teacher_name") or "").strip() or None
        if not all([full_name, age, location, interests, phone]):
            return web.json_response({"error": "Barcha majburiy maydonlarni to'ldiring"}, status=400)
        if has_group and not all([group_time, group_day_type, teacher_name]):
            return web.json_response({"error": "Guruh ma'lumotlarini to'liq kiriting"}, status=400)
        try:
            tg_id = int(telegram_user_id) if telegram_user_id else None
        except (ValueError, TypeError):
            return web.json_response({"error": "Noto'g'ri telegram_user_id"}, status=400)
        if tg_id:
            existing = await db.get_pending_registration_by_user(tg_id)
            if existing:
                return web.json_response({"ok": True, "id": existing.id, "status": existing.status, "already": True})
        rs = await db.create_direct_registration({
            "telegram_user_id": tg_id,
            "full_name":        full_name,
            "age":              age,
            "location":         location,
            "interests":        interests,
            "phone":            phone,
            "has_group":        has_group,
            "group_time":       group_time,
            "group_day_type":   group_day_type,
            "teacher_name":     teacher_name,
        })
        group_info = ""
        if has_group:
            if group_day_type == "ODD":
                day_label = "Toq kunlar"
            elif group_day_type == "EVEN":
                day_label = "Juft kunlar"
            else:
                day_label = group_day_type
            group_info = (
                f"\n🏫 Guruh vaqti: {group_time}\n"
                f"📅 Kun turi: {day_label}\n"
                f"👨‍🏫 O'qituvchi: {teacher_name}"
            )
        notif = (
            f"📝 <b>Yangi ariza (to'g'ridan-to'g'ri)</b>\n\n"
            f"👤 {full_name} | Yosh: {age}\n"
            f"📍 Joylashuv: {location}\n"
            f"💡 Qiziqishlari: {interests}\n"
            f"📱 Telefon: {phone}"
            f"{group_info}\n\n"
            f"✅ Admin Mini App da tasdiqlang (Ariza tab)"
        )
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, notif, parse_mode="HTML")
            except Exception:
                pass
        return web.json_response({"ok": True, "id": rs.id, "status": rs.status})

    async def api_student_pending_status(request: web.Request) -> web.Response:
        tg_id_str = request.rel_url.query.get("telegram_user_id", "")
        try:
            tg_id = int(tg_id_str)
        except ValueError:
            return web.json_response({"error": "telegram_user_id kerak"}, status=400)
        rs = await db.get_pending_registration_by_user(tg_id)
        if not rs:
            return web.json_response({"found": False})
        return web.json_response({
            "found":             True,
            "id":                rs.id,
            "status":            rs.status,
            "full_name":         rs.full_name,
            "group_name":        rs.group_name,
            "mars_id":           getattr(rs, "mars_id", None),
            "reject_reason":     getattr(rs, "reject_reason", None),
            "registration_type": getattr(rs, "registration_type", "direct"),
        })

    # ── Daily challenge & XP reset notice ─────────────────────────────────────

    async def api_student_daily_challenge(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        import pytz as _pytz

        from config import TIMEZONE as _TZ
        _tz = _pytz.timezone(_TZ)
        today_str = datetime.now(_tz).strftime("%Y-%m-%d")
        student = await db.get_student(user_id)
        if not student:
            return web.json_response({"error": "Not registered"}, status=404)
        streak    = student.streak_days or 0
        task      = "7 kun ketma-ket Mini App ga kiring" if streak < 7 else "Haftalik rekordni yangilang!"
        xp_reward = 100
        completed = streak >= 7
        progress  = min(streak, 7)
        total     = 7
        att = await db.get_student_attendance(user_id, today_str)
        if not att:
            task      = "Bugun davomatni belgilang"
            xp_reward = 20
            completed = False
            progress  = 0
            total     = 1
        else:
            task      = "Davomat belgilandi ✅"
            completed = True
            progress  = 1
            total     = 1
        return web.json_response({
            "task":      task,
            "xp_reward": xp_reward,
            "completed": completed,
            "progress":  progress,
            "total":     total,
            "streak":    streak,
        })

    async def api_xp_reset_notice(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        student = await db.get_student(user_id)
        if not student or student.xp_notice_seen:
            return web.json_response({"show": False})
        return web.json_response({
            "show": True,
            "title": "⚠️ XP tizimi qayta boshlandi",
            "message": (
                "Hurmatli o'quvchi!\n\n"
                "Tizimimizda texnik nosozliklar sababli ko'pchilik o'quvchilar "
                "noto'g'ri XP yig'ishdi. Adolatlilik va teng raqobat uchun "
                "barcha o'quvchilarning XP lari 0 ga qayta boshlandi.\n\n"
                "Kechirasiz noqulaylik uchun va yangi boshlang! 💪"
            ),
        })

    async def api_xp_reset_notice_seen(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        await db.mark_xp_notice_seen(user_id)
        return web.json_response({"ok": True})

    # ── Route registration ─────────────────────────────────────────────────────

    app.router.add_get("/api/public/groups",    api_public_groups)
    app.router.add_post("/api/student/register", api_student_register)
    app.router.add_get("/api/me",               api_me)
    app.router.add_get("/api/tomorrow",         api_tomorrow)
    app.router.add_get("/api/homework",         api_homework)
    app.router.add_get("/api/hw-history",       api_hw_history)
    app.router.add_post("/api/attendance",      api_attendance)
    app.router.add_get("/api/attendance",       api_attendance_today)
    app.router.add_get("/api/class-schedule",   api_class_schedule)
    app.router.add_post("/api/student/checkin",         api_student_checkin)
    app.router.add_get("/api/student/progress",         api_student_progress)
    app.router.add_get("/api/student/leaderboard",      api_student_leaderboard)
    app.router.add_get("/api/student/mood",             api_student_mood)
    app.router.add_post("/api/student/mood",            api_student_mood)
    app.router.add_post("/api/student/hw-confirm",         api_student_hw_confirm)
    app.router.add_get("/api/student/hw-confirm-status",   api_student_hw_confirm_status)
    app.router.add_post("/api/student/logout",             api_student_logout)
    app.router.add_get("/api/student/leaderboard/global",  api_student_leaderboard_global)
    app.router.add_get("/api/student/profile/{user_id}",   api_student_profile)
    app.router.add_post("/api/student/avatar",             api_student_avatar)
    app.router.add_get("/api/chat",                        api_chat_get)
    app.router.add_post("/api/chat",                       api_chat_post)
    app.router.add_get("/api/student/leaderboard/group",   api_student_leaderboard_group)
    app.router.add_get("/api/student/leaderboard/monthly", api_student_leaderboard_monthly)
    app.router.add_get("/api/student/referral",            api_student_referral)
    app.router.add_get("/api/student/referral/invited",    api_student_referral_invited)
    app.router.add_post("/api/referral/register",          api_referral_register)
    app.router.add_post("/api/student/pending-register",   api_student_pending_register)
    app.router.add_get("/api/student/pending-status",      api_student_pending_status)
    app.router.add_get("/api/student/daily-challenge",     api_student_daily_challenge)
    app.router.add_get("/api/student/xp-reset-notice",    api_xp_reset_notice)
    app.router.add_post("/api/student/xp-reset-notice/seen", api_xp_reset_notice_seen)
