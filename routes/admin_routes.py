"""
routes/admin_routes.py — Admin va Mini-Admin API endpointlari
Endpointlar: /api/admin/*, /api/mini-admin/*
"""

import asyncio
import secrets
import time
from datetime import UTC, datetime, timedelta

from aiohttp import web

from config import (
    APP_VERSION,
    GIT_COMMIT_SHA,
    MINI_ADMIN_LOGINS,
    SEND_HOUR,
    SEND_MINUTE,
    TIMEZONE,
    WEBAPP_URL,
)
from rate_limit import client_ip
from routes.api_json import json_err, json_ok
from utils import verify_secret


def _merge_known_credentials(static_credentials: dict[str, dict], db_credentials: list) -> dict[str, dict]:
    merged = {mars_id: {"name": cred["name"], "group": cred["group"]} for mars_id, cred in static_credentials.items()}
    for cred in db_credentials:
        merged[cred.mars_id] = {"name": cred.name, "group": cred.group_name}
    return merged


def setup_admin_routes(app: web.Application, ctx: dict) -> None:
    """Admin va mini-admin endpointlarini ro'yxatdan o'tkazadi."""
    bot = ctx["bot"]
    db = ctx["db"]
    tz = ctx["tz"]
    _auth = ctx["auth"]
    _admin_auth = ctx["admin_auth"]
    _mini_admin_auth = ctx["mini_admin_auth"]
    _mini_sessions = ctx["mini_sessions"]
    _login_limiter = ctx.get("login_rate_limiter")
    _trust_xff = ctx.get("trust_x_forwarded_for", False)

    async def _audit(actor: int | None, action: str, target: str | None = None, details: str | None = None) -> None:
        try:
            await db.add_admin_audit_log(actor_user_id=actor, action=action, target=target, details=details)
        except Exception:
            pass

    def _mentions_for_students(students: list) -> list[str]:
        usernames: list[str] = []
        for s in students:
            u = (getattr(s, "telegram_username", None) or "").strip().lstrip("@")
            if u:
                usernames.append(f"@{u}")
        return sorted(set(usernames))

    # ── Mini Admin Session ────────────────────────────────────────────────────

    async def api_mini_admin_login(request: web.Request) -> web.Response:
        """Mini admin parol bilan login. {username, password} → {token}"""
        if _login_limiter is not None:
            ip = client_ip(request, trust_x_forwarded_for=bool(_trust_xff))
            if not _login_limiter.allow(ip):
                return json_err(
                    "Juda ko'p urinish. Birozdan keyin qayta urining.",
                    code="rate_limited",
                    status=429,
                )
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        username = (body.get("username") or "").strip()
        password = (body.get("password") or "").strip()
        expected = MINI_ADMIN_LOGINS.get(username)
        if not expected or not verify_secret(expected, password):
            return json_err("Login yoki parol noto'g'ri", code="invalid_credentials", status=401)
        token = secrets.token_hex(32)
        expires = datetime.now(UTC) + timedelta(days=30)
        _mini_sessions[token] = {"username": username, "expires": expires}
        return web.json_response({"ok": True, "token": token, "username": username})

    async def api_mini_admin_verify(request: web.Request) -> web.Response:
        """Token hali amal qiladimi?"""
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return json_err("Token kerak", code="unauthorized", status=401)
        token = auth_header[7:].strip()
        sess = _mini_sessions.get(token)
        if not sess or datetime.now(UTC) > sess["expires"]:
            if sess:
                del _mini_sessions[token]
            return json_err("Token yaroqsiz yoki muddati o'tgan", code="unauthorized", status=401)
        return web.json_response({"ok": True, "username": sess["username"]})

    async def api_mini_admin_logout(request: web.Request) -> web.Response:
        """Token o'chiriladi."""
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            _mini_sessions.pop(auth_header[7:].strip(), None)
        return web.json_response({"ok": True})

    # ── Admin API ─────────────────────────────────────────────────────────────

    async def api_admin_me(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        return web.json_response({"ok": True, "user_id": user_id})

    async def api_admin_stats(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        today = datetime.now(tz).strftime("%Y-%m-%d")
        students = await db.get_all_students()
        groups = await db.get_all_groups()
        att_recs = await db.get_attendance_by_date(today)
        present = sum(1 for r in att_recs if r.status == "yes")
        absent = sum(1 for r in att_recs if r.status == "no")
        total_xp = sum(s.xp or 0 for s in students)
        avg_xp = round(total_xp / len(students)) if students else 0
        return web.json_response(
            {
                "total_students": len(students),
                "active_groups": sum(1 for g in groups if g.is_active),
                "total_groups": len(groups),
                "today_present": present,
                "today_absent": absent,
                "today_pending": len(students) - present - absent,
                "today": today,
                "avg_xp": avg_xp,
                "total_xp": total_xp,
            }
        )

    async def api_admin_students(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        today = datetime.now(tz).strftime("%Y-%m-%d")
        students = await db.get_all_students()
        att_recs = await db.get_attendance_by_date(today)
        att_map = {r.user_id: r.status for r in att_recs}
        return web.json_response(
            {
                "students": [
                    {
                        "user_id": s.user_id,
                        "full_name": s.full_name,
                        "group_name": s.group_name,
                        "mars_id": s.mars_id,
                        "username": s.telegram_username or "",
                        "phone": s.phone_number or "",
                        "last_active": s.last_active.strftime("%d.%m.%Y %H:%M") if s.last_active else None,
                        "att_today": att_map.get(s.user_id),
                        "xp": s.xp or 0,
                        "level": s.level or 1,
                        "streak": s.streak_days or 0,
                        "avatar": s.avatar_emoji or "",
                    }
                    for s in students
                ]
            }
        )

    async def api_admin_attendance(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        today = datetime.now(tz).strftime("%Y-%m-%d")
        students = await db.get_all_students()
        att_recs = await db.get_attendance_by_date(today)
        att_map = {r.user_id: r for r in att_recs}
        present, absent, pending = [], [], []
        for s in students:
            entry = {
                "user_id": s.user_id,
                "full_name": s.full_name,
                "group_name": s.group_name,
                "username": s.telegram_username or "",
            }
            rec = att_map.get(s.user_id)
            if rec is None:
                pending.append(entry)
            elif rec.status == "yes":
                present.append(entry)
            else:
                entry["reason"] = rec.reason or ""
                absent.append(entry)
        return web.json_response(
            {
                "date": today,
                "present": present,
                "absent": absent,
                "pending": pending,
            }
        )

    async def api_admin_all_students(request: web.Request) -> web.Response:
        """MARS_CREDENTIALS dagi barcha o'quvchilar — admin uchun."""
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        from credentials import MARS_CREDENTIALS

        all_credentials = _merge_known_credentials(
            MARS_CREDENTIALS,
            await db.get_all_student_credentials(),
        )
        today = datetime.now(tz).strftime("%Y-%m-%d")
        registered = await db.get_all_students()
        att_recs = await db.get_attendance_by_date(today)
        reg_map = {s.mars_id: s for s in registered if s.mars_id}
        att_map = {r.user_id: r.status for r in att_recs}
        result = []
        for mars_id, cred in all_credentials.items():
            reg = reg_map.get(mars_id)
            result.append(
                {
                    "mars_id": mars_id,
                    "full_name": cred["name"],
                    "group_name": cred["group"],
                    "registered": reg is not None,
                    "user_id": reg.user_id if reg else None,
                    "username": reg.telegram_username if reg else None,
                    "phone": reg.phone_number if reg else None,
                    "last_active": reg.last_active.strftime("%d.%m.%Y %H:%M") if reg and reg.last_active else None,
                    "att_today": att_map.get(reg.user_id) if reg else None,
                }
            )
        result.sort(key=lambda x: (x["group_name"], x["full_name"]))
        return web.json_response({"students": result})

    async def api_admin_groups(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        groups = await db.get_all_groups()
        return web.json_response(
            {
                "groups": [
                    {
                        "id": g.id,
                        "chat_id": g.chat_id,
                        "name": g.name,
                        "group_type": g.group_type.value,
                        "audience": g.audience.value,
                        "is_active": g.is_active,
                    }
                    for g in groups
                ]
            }
        )

    async def api_admin_groups_detail(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        from class_schedule import CLASS_SCHEDULE

        groups = await db.get_all_groups()
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
            day_type = g.group_type.value
            class_time = CLASS_SCHEDULE.get(day_type, {}).get(g.name)
            result.append(
                {
                    "id": g.id,
                    "chat_id": g.chat_id,
                    "name": g.name,
                    "group_type": day_type,
                    "audience": g.audience.value,
                    "is_active": g.is_active,
                    "class_time": class_time,
                    "student_count": student_count.get(g.name, 0),
                    "has_homework": g.name in hw_map,
                    "hw_sent_at": hw_map.get(g.name),
                }
            )
        return web.json_response({"groups": result})

    async def api_admin_toggle_group(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        chat_id = body.get("chat_id")
        is_active = body.get("is_active")
        if chat_id is None or is_active is None:
            return json_err("Missing fields", code="validation_error", status=400)
        await db.set_group_active(int(chat_id), bool(is_active))
        return web.json_response({"ok": True})

    async def api_admin_hw_schedule(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        from class_schedule import CLASS_SCHEDULE

        students = await db.get_all_students()
        unique_groups = sorted({s.group_name for s in students})
        result = []
        for gname in unique_groups:
            hw = await db.get_homework(gname)
            odd_time = CLASS_SCHEDULE.get("ODD", {}).get(gname)
            even_time = CLASS_SCHEDULE.get("EVEN", {}).get(gname)
            day_type = "ODD" if odd_time else ("EVEN" if even_time else None)
            class_time = odd_time or even_time
            cnt = sum(1 for s in students if s.group_name == gname)
            result.append(
                {
                    "group_name": gname,
                    "day_type": day_type,
                    "class_time": class_time,
                    "student_count": cnt,
                    "has_homework": hw is not None,
                    "hw_sent_at": hw.sent_at.strftime("%d.%m.%Y %H:%M") if hw else None,
                }
            )
        result.sort(key=lambda x: (x.get("day_type") or "ZZ", x.get("class_time") or ""))
        return web.json_response(
            {
                "groups": result,
                "odd_days": "Dushanba, Chorshanba, Juma",
                "even_days": "Seshanba, Payshanba, Shanba",
            }
        )

    async def api_admin_broadcast(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        text = (body.get("text") or "").strip()
        target = body.get("target", "all")
        if not text:
            return json_err("Empty message", code="validation_error", status=400)
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
            from database import AudienceType as AT

            all_groups = await db.get_all_groups()
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
        await _audit(
            user_id,
            "broadcast",
            target=target,
            details=f"sent={ok},failed={fail},len={len(text)}",
        )
        return web.json_response({"ok": True, "sent": ok, "failed": fail})

    async def api_admin_auto_msg_preview(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        import pytz as _pytz

        from database import GroupType
        from scheduler import build_reminder_message, get_tomorrow_info

        _tz = _pytz.timezone(TIMEZONE)
        info = get_tomorrow_info(TIMEZONE)
        h = await db.get_setting("SEND_HOUR", str(SEND_HOUR))
        m = await db.get_setting("SEND_MINUTE", str(SEND_MINUTE))
        global_on = await db.get_setting("AUTO_MSG_GROUPS", "1") == "1"
        day_key = "AUTO_MSG_ODD" if info.group_type == GroupType.ODD else "AUTO_MSG_EVEN"
        day_on = await db.get_setting(day_key, "1") == "1"
        groups = await db.get_groups_by_type(info.group_type)
        will_send, will_skip = [], []
        for g in groups:
            msg = build_reminder_message(info, g.audience)
            grp_on = await db.get_setting(f"AUTO_MSG_GROUP:{g.name}", "1") == "1"
            if not global_on:
                reason = "Umumiy guruh xabari o'chirilgan"
            elif not day_on:
                reason = f"{'Toq' if info.group_type == GroupType.ODD else 'Juft'} kun o'chirilgan"
            elif not grp_on:
                reason = "Bu guruh uchun avto xabar o'chirilgan"
            else:
                reason = None
            entry = {"group_name": g.name, "audience": g.audience.value, "message": msg}
            if reason:
                entry["reason_off"] = reason
                will_skip.append(entry)
            else:
                will_send.append(entry)
        return web.json_response(
            {
                "tomorrow": info.date_str,
                "weekday": info.weekday_uz,
                "day_type": info.group_type.value,
                "send_time": f"{int(h):02d}:{int(m):02d}",
                "global_on": global_on,
                "day_on": day_on,
                "will_send": will_send,
                "will_skip": will_skip,
            }
        )

    async def api_admin_auto_msg_get(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        from sqlalchemy import select

        from database import CuratorSession

        groups = await db.get_all_groups()
        per_group = {}
        for g in groups:
            per_group[g.name] = await db.get_setting(f"AUTO_MSG_GROUP:{g.name}", "1") == "1"
        async with db.session_factory() as _sess:
            _res = await _sess.execute(select(CuratorSession))
            curator_sessions = list(_res.scalars().all())
        per_curator = {}
        for cs in curator_sessions:
            per_curator[str(cs.telegram_id)] = await db.get_setting(f"AUTO_MSG_CURATOR:{cs.telegram_id}", "1") == "1"
        return web.json_response(
            {
                "groups": await db.get_setting("AUTO_MSG_GROUPS", "1") == "1",
                "students": await db.get_setting("AUTO_MSG_STUDENTS", "1") == "1",
                "curators": await db.get_setting("AUTO_MSG_CURATORS", "1") == "1",
                "odd": await db.get_setting("AUTO_MSG_ODD", "1") == "1",
                "even": await db.get_setting("AUTO_MSG_EVEN", "1") == "1",
                "per_group": per_group,
                "per_curator": per_curator,
            }
        )

    async def api_admin_auto_msg_set(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        for key in ("groups", "students", "curators", "odd", "even"):
            if key in body:
                await db.set_setting(f"AUTO_MSG_{key.upper()}", "1" if body[key] else "0")
        for group_name, enabled in body.get("per_group", {}).items():
            await db.set_setting(f"AUTO_MSG_GROUP:{group_name}", "1" if enabled else "0")
        for curator_id, enabled in body.get("per_curator", {}).items():
            await db.set_setting(f"AUTO_MSG_CURATOR:{curator_id}", "1" if enabled else "0")
        return web.json_response({"ok": True})

    async def api_admin_reminder_get(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        h = await db.get_setting("SEND_HOUR", str(SEND_HOUR))
        m = await db.get_setting("SEND_MINUTE", str(SEND_MINUTE))
        return web.json_response({"hour": int(h), "minute": int(m)})

    async def api_admin_reminder_set(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        hour = body.get("hour")
        minute = body.get("minute")
        if hour is None or minute is None:
            return json_err("Missing fields", code="validation_error", status=400)
        try:
            hour, minute = int(hour), int(minute)
        except (ValueError, TypeError):
            return json_err("Noto'g'ri vaqt formati", code="validation_error", status=400)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return json_err("Invalid time", code="validation_error", status=400)
        await db.set_setting("SEND_HOUR", str(hour))
        await db.set_setting("SEND_MINUTE", str(minute))
        from scheduler import reschedule_reminder

        reschedule_reminder(hour, minute)
        return web.json_response({"ok": True, "hour": hour, "minute": minute})

    async def api_admin_inactive(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            days = int(request.rel_url.query.get("days", "7"))
        except (ValueError, TypeError):
            days = 7
        inactive = await db.get_inactive_students(days=days)
        return web.json_response(
            {
                "days": days,
                "students": [
                    {
                        "user_id": s.user_id,
                        "full_name": s.full_name,
                        "group_name": s.group_name,
                        "username": s.telegram_username or "",
                        "last_active": s.last_active.strftime("%d.%m.%Y %H:%M") if s.last_active else None,
                    }
                    for s in inactive
                ],
            }
        )

    async def api_admin_test_send(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        group_name = body.get("group_name")
        try:
            from scheduler import send_daily_reminder_to_group, send_daily_reminders

            if group_name and group_name != "all":
                result = await send_daily_reminder_to_group(
                    bot=bot, db=db, timezone_str=TIMEZONE, group_name=group_name
                )
                if result:
                    message_id, chat_id = result
                    return web.json_response(
                        {
                            "ok": True,
                            "target": group_name,
                            "message_id": message_id,
                            "chat_id": chat_id,
                        }
                    )
                else:
                    return web.json_response(
                        {"error": f"Guruh topilmadi yoki xabar yuborib bo'lmadi: '{group_name}'"},
                        status=400,
                    )
            else:
                asyncio.create_task(send_daily_reminders(bot=bot, db=db, timezone_str=TIMEZONE))
                return web.json_response({"ok": True, "target": "all"})
        except Exception as e:
            return json_err(str(e), code="internal_error", status=500)

    async def api_admin_delete_message(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        chat_id = body.get("chat_id")
        message_id = body.get("message_id")
        if not chat_id or not message_id:
            return json_err("chat_id va message_id kerak", code="validation_error", status=400)
        try:
            await bot.delete_message(chat_id=int(chat_id), message_id=int(message_id))
            return web.json_response({"ok": True})
        except Exception as e:
            return json_err(str(e), code="internal_error", status=500)

    async def api_admin_test_leaderboard(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            from scheduler import send_leaderboard_broadcast

            asyncio.create_task(
                send_leaderboard_broadcast(bot=bot, db=db, webapp_url=WEBAPP_URL, timezone_str=TIMEZONE)
            )
            return web.json_response({"ok": True})
        except Exception as e:
            return json_err(str(e), code="internal_error", status=500)

    async def api_admin_delete_test_messages(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        groups = await db.get_groups_with_message()
        deleted, errors = 0, 0
        for group in groups:
            if not group.last_message_id:
                continue
            try:
                await bot.delete_message(chat_id=group.chat_id, message_id=group.last_message_id)
                deleted += 1
            except Exception:
                errors += 1
            await db.clear_message_id(group.chat_id)
        return web.json_response({"ok": True, "deleted": deleted, "errors": errors})

    async def api_admin_curator_stats(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        from curator_credentials import CURATORS

        sessions = await db.get_all_curator_sessions()
        result = []
        for key, info in CURATORS.items():
            matched = [cs for cs in sessions if cs.curator_key == key]
            if matched:
                cs = matched[0]
                result.append(
                    {
                        "key": key,
                        "full_name": info.get("full_name", key),
                        "logged_in": True,
                        "telegram_id": cs.telegram_id,
                        "logged_in_at": cs.logged_in_at.isoformat() if cs.logged_in_at else None,
                        "last_active": cs.last_active.isoformat() if cs.last_active else None,
                    }
                )
            else:
                result.append(
                    {
                        "key": key,
                        "full_name": info.get("full_name", key),
                        "logged_in": False,
                        "telegram_id": None,
                        "logged_in_at": None,
                        "last_active": None,
                    }
                )
        return web.json_response(result)

    async def api_admin_button_stats(request: web.Request) -> web.Response:
        user_id = _admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        stats = await db.get_button_stats(limit=30)
        return web.json_response(
            [
                {
                    "button_name": s.button_name,
                    "count": s.count,
                    "last_used": s.last_used.isoformat() if s.last_used else None,
                }
                for s in stats
            ]
        )

    # ── Admin Referral ────────────────────────────────────────────────────────

    async def api_admin_referral_students(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        status_filter = request.rel_url.query.get("status")
        items = await db.get_referral_students(status=status_filter or None)
        return web.json_response(
            {
                "referrals": [
                    {
                        "id": r.id,
                        "referrer_user_id": r.referrer_user_id,
                        "telegram_user_id": r.telegram_user_id,
                        "full_name": r.full_name,
                        "age": r.age,
                        "location": r.location,
                        "interests": r.interests,
                        "phone": r.phone,
                        "status": r.status,
                        "group_name": r.group_name,
                        "xp_awarded": r.xp_awarded,
                        "mars_id": getattr(r, "mars_id", None),
                        "reject_reason": getattr(r, "reject_reason", None),
                        "registration_type": getattr(r, "registration_type", "referral"),
                        "has_group": getattr(r, "has_group", False),
                        "group_time": getattr(r, "group_time", None),
                        "group_day_type": getattr(r, "group_day_type", None),
                        "teacher_name": getattr(r, "teacher_name", None),
                        "created_at": r.created_at.strftime("%d.%m.%Y %H:%M") if r.created_at else "",
                    }
                    for r in items
                ]
            }
        )

    async def api_admin_referral_approve(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            rs_id = int(request.match_info["id"])
        except Exception:
            return json_err("Invalid id", code="validation_error", status=400)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        group_name = (body.get("group_name") or "").strip()
        if not group_name:
            return json_err("group_name kerak", code="validation_error", status=400)
        rs = await db.approve_and_register(rs_id, group_name)
        if not rs:
            return json_err("Topilmadi", code="not_found", status=404)
        if rs.referrer_user_id and rs.referrer_user_id != 0:
            await db.award_referral_xp(rs.referrer_user_id, rs_id)
            wa_url = WEBAPP_URL.rstrip("/") + "/webapp/student.html" if WEBAPP_URL else None
            try:
                from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

                ref_msg = (
                    f"🎉 <b>Siz taklif qilgan do'st qabul qilindi!</b>\n\n"
                    f"👤 {rs.full_name}\n📚 Guruh: {group_name}\n\n"
                    f"💰 <b>+500 XP</b> hisobingizga qo'shildi!\n"
                    f"Mini App da reytingingizni ko'ring 👇"
                )
                if wa_url:
                    ref_kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="🏆 Mini App — XP ni ko'rish",
                                    web_app=WebAppInfo(url=wa_url),
                                )
                            ]
                        ]
                    )
                    await bot.send_message(rs.referrer_user_id, ref_msg, parse_mode="HTML", reply_markup=ref_kb)
                else:
                    await bot.send_message(rs.referrer_user_id, ref_msg, parse_mode="HTML")
            except Exception:
                pass
        if rs.telegram_user_id:
            wa_url = WEBAPP_URL.rstrip("/") + "/webapp/student.html" if WEBAPP_URL else None
            try:
                msg_text = (
                    f"✅ <b>Arizangiz tasdiqlandi!</b>\n\n"
                    f"📚 Guruh: <b>{group_name}</b>\n"
                    f"🆔 Mars ID: <b>{rs.mars_id or '—'}</b>\n\n"
                    f"Endi Mini App orqali kiring va o'qishni boshlang!"
                )
                if wa_url:
                    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="📱 Mini App ni ochish",
                                    web_app=WebAppInfo(url=wa_url),
                                )
                            ]
                        ]
                    )
                    await bot.send_message(rs.telegram_user_id, msg_text, parse_mode="HTML", reply_markup=kb)
                else:
                    await bot.send_message(rs.telegram_user_id, msg_text, parse_mode="HTML")
            except Exception:
                pass
        return web.json_response({"ok": True, "mars_id": rs.mars_id})

    async def api_admin_referral_reject(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            rs_id = int(request.match_info["id"])
        except Exception:
            return json_err("Invalid id", code="validation_error", status=400)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        reason = (body.get("reason") or "").strip()
        if not reason:
            return json_err("Rad etish sababini kiriting", code="validation_error", status=400)
        rs = await db.reject_referral_with_reason(rs_id, reason)
        if not rs:
            return json_err("Topilmadi", code="not_found", status=404)
        if rs.telegram_user_id:
            try:
                await bot.send_message(
                    rs.telegram_user_id,
                    f"❌ <b>Arizangiz rad etildi</b>\n\n"
                    f"📋 Sabab: {reason}\n\n"
                    f"Savollar bo'lsa, markaz bilan bog'laning.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        return web.json_response({"ok": True})

    # ── Admin Messaging ───────────────────────────────────────────────────────

    async def api_admin_message_student(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        target_id = body.get("user_id")
        text = (body.get("text") or "").strip()
        if not target_id or not text:
            return json_err("user_id va text kerak", code="validation_error", status=400)
        try:
            await bot.send_message(int(target_id), f"📢 <b>Admin xabari:</b>\n\n{text}", parse_mode="HTML")
            await _audit(user_id, "message_student", target=str(target_id), details=f"len={len(text)}")
            return web.json_response({"ok": True})
        except Exception as e:
            return json_err(str(e), code="internal_error", status=500)

    async def api_admin_student_move(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        target_user_id = body.get("user_id")
        group_name = (body.get("group_name") or "").strip()
        if not target_user_id or not group_name:
            return json_err("user_id va group_name kerak", code="validation_error", status=400)
        ok = await db.update_student_group(int(target_user_id), group_name)
        if ok:
            await _audit(user_id, "move_student_group", target=str(target_user_id), details=group_name)
        return json_ok(ok=ok)

    async def api_admin_student_delete(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        target_user_id = body.get("user_id")
        if not target_user_id:
            return json_err("user_id kerak", code="validation_error", status=400)
        ok = await db.soft_delete_student(int(target_user_id), deleted_by=user_id)
        if ok:
            await _audit(user_id, "delete_student_from_group", target=str(target_user_id))
        return json_ok(ok=ok)

    async def api_admin_student_restore(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        target_user_id = body.get("user_id")
        if not target_user_id:
            return json_err("user_id kerak", code="validation_error", status=400)
        ok = await db.restore_deleted_student(int(target_user_id))
        if ok:
            await _audit(user_id, "restore_student_to_group", target=str(target_user_id))
        return json_ok(ok=ok)

    async def api_admin_deleted_students(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        rows = await db.get_deleted_students(limit=120)
        return json_ok(
            students=[
                {
                    "user_id": s.user_id,
                    "full_name": s.full_name,
                    "group_name": s.group_name,
                    "mars_id": s.mars_id,
                    "deleted_at": s.deleted_at.isoformat() if s.deleted_at else None,
                }
                for s in rows
            ]
        )

    async def api_admin_message_group(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        chat_id = body.get("chat_id")
        text = (body.get("text") or "").strip()
        if not chat_id or not text:
            return json_err("chat_id va text kerak", code="validation_error", status=400)
        try:
            await bot.send_message(int(chat_id), text)
            await _audit(user_id, "message_group", target=str(chat_id), details=f"len={len(text)}")
            return web.json_response({"ok": True})
        except Exception as e:
            return json_err(str(e), code="internal_error", status=500)

    # ── Admin Profile ─────────────────────────────────────────────────────────

    async def api_admin_profile_get(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        ap = await db.get_admin_profile(user_id)
        if not ap:
            ap = await db.upsert_admin_profile(user_id, {"display_name": f"Admin {user_id}"})
        today = datetime.now(tz).strftime("%Y-%m-%d")
        att_recs = await db.get_attendance_by_date(today)
        students = await db.get_all_students()
        pending = await db.get_referral_students(status="pending")
        return web.json_response(
            {
                "telegram_id": ap.telegram_id,
                "display_name": ap.display_name,
                "avatar_emoji": ap.avatar_emoji,
                "total_students": len(students),
                "today_present": sum(1 for r in att_recs if r.status == "yes"),
                "today_absent": sum(1 for r in att_recs if r.status == "no"),
                "referral_pending": len(pending),
            }
        )

    async def api_admin_profile_set(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        ap = await db.upsert_admin_profile(user_id, body)
        return web.json_response({"ok": True, "display_name": ap.display_name, "avatar_emoji": ap.avatar_emoji})

    # ── Admin Attendance / Warnings / Homework / Weekly Stats ─────────────────

    async def api_admin_attendance_update(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        try:
            target_user_id = int(body.get("user_id", 0))
        except (ValueError, TypeError):
            return json_err("Noto'g'ri user_id", code="validation_error", status=400)
        date_str = body.get("date", "")
        status = body.get("status", "")
        if not target_user_id or not date_str or status not in ("yes", "no"):
            return json_err("user_id, date va status kerak", code="validation_error", status=400)
        ok = await db.admin_set_attendance(target_user_id, date_str, status)
        return web.json_response({"ok": ok})

    async def api_admin_warnings(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        import pytz as _pytz

        _tz = _pytz.timezone(TIMEZONE)
        today_str = datetime.now(_tz).strftime("%Y-%m-%d")
        absent_students = await db.get_absent_streak_students(days=3)
        absent_list = [
            {
                "user_id": s.get("user_id"),
                "full_name": s.get("full_name"),
                "group_name": s.get("group_name"),
                "absent_days": s.get("absent_days"),
            }
            for s in absent_students
        ]
        from class_schedule import CLASS_SCHEDULE

        day_type = "ODD" if datetime.now(_tz).weekday() in (0, 2, 4) else "EVEN"
        no_hw = []
        for gname in CLASS_SCHEDULE.get(day_type, {}).keys():
            hw = await db.get_homework(gname)
            if not hw:
                no_hw.append({"group_name": gname})
        return web.json_response(
            {
                "absent_3days": absent_list,
                "no_homework": no_hw,
                "total": len(absent_list) + len(no_hw),
                "date": today_str,
            }
        )

    async def api_admin_send_homework(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        group_name = (body.get("group_name") or "").strip()
        text = (body.get("text") or "").strip()
        due_at_raw = (body.get("due_at") or "").strip()
        due_at = None
        if due_at_raw:
            try:
                due_at = datetime.fromisoformat(due_at_raw)
            except ValueError:
                return json_err("due_at noto'g'ri formatda", code="validation_error", status=400)
        if not group_name or not text:
            return json_err("group_name va text kerak", code="validation_error", status=400)
        from sqlalchemy import select

        from database import Group

        async with db.session_factory() as session:
            result = await session.execute(select(Group).where(Group.name == group_name))
            group = result.scalar_one_or_none()

        students = await db.get_students_by_group(group_name)
        if not group and not students:
            return json_err(
                "Guruh topilmadi va o'quvchi yo'q",
                code="not_found",
                status=404,
            )

        # Group chat mavjud bo'lsa — chatga yuboramiz va Homework yozuvini chatdagi xabarga
        # bog'laymiz (copy_message uchun). Aks holda — guruhsiz rejimda DM va student panelda
        # ko'rsatish uchun Homework ni admin chatiga bog'laymiz.
        warning = None
        if group:
            try:
                sent = await bot.send_message(
                    chat_id=group.chat_id,
                    text=f"📝 <b>Uy vazifasi</b>\n\n{text}",
                    parse_mode="HTML",
                )
            except Exception as e:
                return json_err(str(e), code="internal_error", status=500)
            await db.set_homework(
                group_name=group_name,
                from_chat_id=sent.chat.id,
                message_id=sent.message_id,
            )
            mentions = _mentions_for_students(students)
            max_mentions = 10
            shown_mentions = mentions[:max_mentions]
            remaining = max(0, len(mentions) - len(shown_mentions))
            mention_lines = "".join([f"{i + 1}) {u}\n" for i, u in enumerate(shown_mentions)])
            if remaining:
                mention_lines += f"... va yana {remaining} ta\n"
            reminder_group_text = (
                f"🔔 <b>Uy vazifa eslatmasi</b>\n\n"
                f"🏫 Guruh: <b>{group_name}</b>\n"
                f"👥 O'quvchilar soni: <b>{len(students)}</b>\n\n"
                f"{('<b>Belgilanganlar:</b>\n' + mention_lines) if mentions else '⚠️ Username topilmadi'}"
            )
            try:
                await bot.send_message(chat_id=group.chat_id, text=reminder_group_text, parse_mode="HTML")
            except Exception:
                pass
        else:
            # Telegram chat ro'yxatdan o'tmagan — admin bilan bog'liq xabarga saqlaymiz
            try:
                sent = await bot.send_message(
                    chat_id=user_id,
                    text=f"📝 <b>Uy vazifasi (saqlandi)</b>\n\nGuruh: <b>{group_name}</b>\n\n{text}",
                    parse_mode="HTML",
                )
                await db.set_homework(
                    group_name=group_name,
                    from_chat_id=sent.chat.id,
                    message_id=sent.message_id,
                )
                warning = (
                    f"'{group_name}' uchun Telegram chat ro'yxatdan o'tmagan — "
                    f"vazifa saqlandi va o'quvchilarga DM yuborildi"
                )
            except Exception as e:
                return json_err(f"Vazifani saqlab bo'lmadi: {e}", code="internal_error", status=500)

        dm_sent = 0
        for s in students:
            try:
                await bot.send_message(
                    chat_id=s.user_id,
                    text=(
                        f"📝 <b>Yangi uy vazifa berildi</b>\n\n"
                        f"Guruh: <b>{group_name}</b>\n"
                        f"Uy vazifani bajarib, tasdiqlashni unutmang."
                    ),
                    parse_mode="HTML",
                )
                dm_sent += 1
            except Exception:
                continue
        task = await db.create_homework_task(
            group_name,
            text,
            created_by=user_id,
            status="assigned",
            due_at=due_at,
        )
        await _audit(
            user_id,
            "send_homework",
            target=group_name,
            details=f"task_id={task.id},students={len(students)},dm={dm_sent},chat={'yes' if group else 'no'}",
        )
        return web.json_response(
            {
                "ok": True,
                "students": len(students),
                "dm_sent": dm_sent,
                "chat_sent": bool(group),
                "warning": warning,
            }
        )

    async def api_admin_update_homework(request: web.Request) -> web.Response:
        """Mavjud uy vazifani yangilash (overwrite)."""
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        group_name = (body.get("group_name") or "").strip()
        text = (body.get("text") or "").strip()
        if not group_name or not text:
            return json_err("group_name va text kerak", code="validation_error", status=400)
        from sqlalchemy import select

        from database import Group

        async with db.session_factory() as session:
            result = await session.execute(select(Group).where(Group.name == group_name))
            group = result.scalar_one_or_none()

        students = await db.get_students_by_group(group_name)
        if not group and not students:
            return json_err("Guruh topilmadi va o'quvchi yo'q", code="not_found", status=404)

        warning = None
        try:
            if group:
                sent = await bot.send_message(
                    chat_id=group.chat_id,
                    text=f"✏️ <b>Uy vazifasi yangilandi</b>\n\n{text}",
                    parse_mode="HTML",
                )
            else:
                sent = await bot.send_message(
                    chat_id=user_id,
                    text=f"✏️ <b>Uy vazifasi yangilandi (saqlandi)</b>\n\nGuruh: <b>{group_name}</b>\n\n{text}",
                    parse_mode="HTML",
                )
                warning = f"'{group_name}' uchun Telegram chat ro'yxatdan o'tmagan — vazifa saqlandi"
        except Exception as e:
            return json_err(str(e), code="internal_error", status=500)
        await db.set_homework(group_name=group_name, from_chat_id=sent.chat.id, message_id=sent.message_id)
        await db.create_homework_task(group_name, text, created_by=user_id, status="reviewed")
        await _audit(user_id, "update_homework", target=group_name)
        return web.json_response({"ok": True, "chat_sent": bool(group), "warning": warning})

    async def api_admin_homework_tasks(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        group_name = (request.rel_url.query.get("group_name") or "").strip() or None
        tasks = await db.list_homework_tasks(group_name=group_name, limit=200)
        return json_ok(
            tasks=[
                {
                    "id": t.id,
                    "group_name": t.group_name,
                    "text": t.text,
                    "status": t.status,
                    "due_at": t.due_at.isoformat() if t.due_at else None,
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                }
                for t in tasks
            ]
        )

    async def api_admin_homework_task_update(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        task_id = body.get("task_id")
        status = (body.get("status") or "").strip()
        allowed = {"draft", "assigned", "reviewed", "rework", "done"}
        if not task_id or status not in allowed:
            return json_err("task_id va status kerak", code="validation_error", status=400)
        ok = await db.update_homework_task_status(int(task_id), status)
        if ok:
            await _audit(user_id, "update_homework_task", target=str(task_id), details=status)
        return json_ok(ok=ok)

    async def api_admin_homework_task_bulk_update(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        ids = body.get("task_ids") or []
        status = (body.get("status") or "").strip()
        allowed = {"draft", "assigned", "reviewed", "rework", "done"}
        if not ids or status not in allowed:
            return json_err("task_ids va status kerak", code="validation_error", status=400)
        updated = 0
        for task_id in ids:
            try:
                ok = await db.update_homework_task_status(int(task_id), status)
                if ok:
                    updated += 1
            except Exception:
                continue
        await _audit(user_id, "bulk_update_homework_task", target=str(updated), details=status)
        return json_ok(updated=updated, requested=len(ids))

    async def api_admin_restore_homework(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        group_name = (body.get("group_name") or "").strip()
        if not group_name:
            return json_err("group_name kerak", code="validation_error", status=400)
        ok = await db.restore_last_deleted_homework(group_name)
        if ok:
            await _audit(user_id, "restore_homework", target=group_name)
        return json_ok(ok=ok)

    async def api_admin_delete_homework(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        group_name = (body.get("group_name") or "").strip()
        if not group_name:
            return json_err("group_name kerak", code="validation_error", status=400)
        ok = await db.delete_homework(group_name)
        if ok:
            await _audit(user_id, "delete_homework", target=group_name, details="soft_delete")
        return json_ok(ok=ok)

    async def api_admin_message_templates(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        templates = [
            {"id": "hw_assign", "label": "Uy vazifa berildi", "text": "📝 Uy vazifa berildi. Vaqtida bajarib keling."},
            {"id": "hw_rework", "label": "Qayta topshiring", "text": "♻️ Ishni qayta ishlang va qayta topshiring."},
            {"id": "praise", "label": "A'lo", "text": "🌟 Zo'r ishladingiz! Davom eting."},
            {"id": "att_warn", "label": "Davomat", "text": "⏰ Davomatni unutmang, darsga o'z vaqtida keling."},
        ]
        return json_ok(templates=templates)

    async def api_admin_audit_logs(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        logs = await db.get_admin_audit_logs(limit=200)
        return json_ok(
            logs=[
                {
                    "id": x.id,
                    "actor_user_id": x.actor_user_id,
                    "action": x.action,
                    "target": x.target,
                    "details": x.details,
                    "created_at": x.created_at.isoformat() if x.created_at else None,
                }
                for x in logs
            ]
        )

    async def api_admin_weekly_stats(request: web.Request) -> web.Response:
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        stats = await db.get_weekly_attendance_stats(days=7)
        return web.json_response({"days": stats})

    async def api_admin_scheduled_jobs_get(request: web.Request) -> web.Response:
        """Cron-jadvalli ishlar ro'yxati va ularning hozirgi vaqtlari."""
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        from scheduler import SCHEDULED_JOBS_REGISTRY, get_job_schedule

        items = []
        for job_id, cfg in SCHEDULED_JOBS_REGISTRY.items():
            h, m, dow = await get_job_schedule(db, job_id)
            items.append(
                {
                    "job_id": job_id,
                    "name": cfg["name"],
                    "hour": h,
                    "minute": m,
                    "day_of_week": dow,
                    "default_hour": cfg["default_hour"],
                    "default_minute": cfg["default_minute"],
                    "default_day_of_week": cfg.get("default_dow", ""),
                    "is_weekly": bool(cfg.get("default_dow")),
                }
            )
        return web.json_response({"jobs": items})

    async def api_admin_scheduled_jobs_set(request: web.Request) -> web.Response:
        """Bitta scheduled job vaqtini o'zgartiradi."""
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        from scheduler import _VALID_DOWS, SCHEDULED_JOBS_REGISTRY, reschedule_job_by_id

        job_id = (body.get("job_id") or "").strip()
        if job_id not in SCHEDULED_JOBS_REGISTRY:
            return json_err("Noma'lum job_id", code="validation_error", status=400)
        try:
            hour = int(body.get("hour"))
            minute = int(body.get("minute"))
        except (ValueError, TypeError):
            return json_err("Noto'g'ri vaqt formati", code="validation_error", status=400)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return json_err("Vaqt 0..23:0..59 oralig'ida bo'lishi kerak", code="validation_error", status=400)
        dow = (body.get("day_of_week") or "").strip().lower()
        cfg = SCHEDULED_JOBS_REGISTRY[job_id]
        is_weekly = bool(cfg.get("default_dow"))
        if is_weekly:
            if dow not in _VALID_DOWS:
                return json_err("day_of_week kerak (mon..sun)", code="validation_error", status=400)
        else:
            dow = ""
        await db.set_setting(f"SCHED:{job_id}:HOUR", str(hour))
        await db.set_setting(f"SCHED:{job_id}:MINUTE", str(minute))
        await db.set_setting(f"SCHED:{job_id}:DOW", dow)
        ok = reschedule_job_by_id(job_id, hour, minute, dow)
        await _audit(
            user_id,
            "reschedule_job",
            target=job_id,
            details=f"{dow + ' ' if dow else ''}{hour:02d}:{minute:02d}",
        )
        # Eski API bilan moslik: daily_lesson_reminder uchun SEND_HOUR/MINUTE ni ham yangilaymiz
        if job_id == "daily_lesson_reminder":
            await db.set_setting("SEND_HOUR", str(hour))
            await db.set_setting("SEND_MINUTE", str(minute))
        return web.json_response(
            {"ok": ok, "job_id": job_id, "hour": hour, "minute": minute, "day_of_week": dow}
        )

    async def api_admin_scheduled_jobs_reset(request: web.Request) -> web.Response:
        """Bitta scheduled job vaqtini default qiymatga qaytaradi."""
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        from scheduler import SCHEDULED_JOBS_REGISTRY, reschedule_job_by_id

        job_id = (body.get("job_id") or "").strip()
        cfg = SCHEDULED_JOBS_REGISTRY.get(job_id)
        if not cfg:
            return json_err("Noma'lum job_id", code="validation_error", status=400)
        h = int(cfg["default_hour"])
        m = int(cfg["default_minute"])
        dow = str(cfg.get("default_dow", "") or "")
        await db.set_setting(f"SCHED:{job_id}:HOUR", str(h))
        await db.set_setting(f"SCHED:{job_id}:MINUTE", str(m))
        await db.set_setting(f"SCHED:{job_id}:DOW", dow)
        reschedule_job_by_id(job_id, h, m, dow)
        await _audit(user_id, "reset_job_schedule", target=job_id)
        if job_id == "daily_lesson_reminder":
            await db.set_setting("SEND_HOUR", str(h))
            await db.set_setting("SEND_MINUTE", str(m))
        return web.json_response({"ok": True, "job_id": job_id, "hour": h, "minute": m, "day_of_week": dow})

    async def api_admin_system_status(request: web.Request) -> web.Response:
        """Mini-admin: DB, scheduler, versiya (monitoring)."""
        user_id = _mini_admin_auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        from scheduler import scheduler_health

        db_ok = await db.check_db_live()
        sch = scheduler_health()
        boot = float(request.app.get("boot_ts_epoch", time.time()))
        body = {
            "ok": True,
            "version": APP_VERSION,
            "commit": GIT_COMMIT_SHA or None,
            "database": db_ok,
            "scheduler": sch,
            "uptime_sec": max(0, int(time.time() - boot)),
        }
        return web.json_response(body)

    # ── Route registration ─────────────────────────────────────────────────────

    app.router.add_post("/api/mini-admin/login", api_mini_admin_login)
    app.router.add_get("/api/mini-admin/verify", api_mini_admin_verify)
    app.router.add_post("/api/mini-admin/logout", api_mini_admin_logout)
    app.router.add_get("/api/admin/system-status", api_admin_system_status)
    app.router.add_get("/api/admin/me", api_admin_me)
    app.router.add_get("/api/admin/stats", api_admin_stats)
    app.router.add_get("/api/admin/students", api_admin_students)
    app.router.add_get("/api/admin/all-students", api_admin_all_students)
    app.router.add_get("/api/admin/attendance", api_admin_attendance)
    app.router.add_get("/api/admin/groups", api_admin_groups)
    app.router.add_get("/api/admin/groups-detail", api_admin_groups_detail)
    app.router.add_post("/api/admin/toggle-group", api_admin_toggle_group)
    app.router.add_get("/api/admin/hw-schedule", api_admin_hw_schedule)
    app.router.add_post("/api/admin/broadcast", api_admin_broadcast)
    app.router.add_get("/api/admin/reminder-time", api_admin_reminder_get)
    app.router.add_post("/api/admin/reminder-time", api_admin_reminder_set)
    app.router.add_get("/api/admin/scheduled-jobs", api_admin_scheduled_jobs_get)
    app.router.add_post("/api/admin/scheduled-jobs", api_admin_scheduled_jobs_set)
    app.router.add_post("/api/admin/scheduled-jobs/reset", api_admin_scheduled_jobs_reset)
    app.router.add_get("/api/admin/auto-msg", api_admin_auto_msg_get)
    app.router.add_post("/api/admin/auto-msg", api_admin_auto_msg_set)
    app.router.add_get("/api/admin/auto-msg-preview", api_admin_auto_msg_preview)
    app.router.add_get("/api/admin/inactive", api_admin_inactive)
    app.router.add_post("/api/admin/test-send", api_admin_test_send)
    app.router.add_post("/api/admin/test-leaderboard", api_admin_test_leaderboard)
    app.router.add_post("/api/admin/delete-message", api_admin_delete_message)
    app.router.add_post("/api/admin/delete-test-messages", api_admin_delete_test_messages)
    app.router.add_get("/api/admin/curator-stats", api_admin_curator_stats)
    app.router.add_get("/api/admin/button-stats", api_admin_button_stats)
    app.router.add_get("/api/admin/referral-students", api_admin_referral_students)
    app.router.add_post("/api/admin/referral-students/{id}/approve", api_admin_referral_approve)
    app.router.add_post("/api/admin/referral-students/{id}/reject", api_admin_referral_reject)
    app.router.add_post("/api/admin/message/student", api_admin_message_student)
    app.router.add_post("/api/admin/student-move", api_admin_student_move)
    app.router.add_post("/api/admin/student-delete", api_admin_student_delete)
    app.router.add_post("/api/admin/student-restore", api_admin_student_restore)
    app.router.add_get("/api/admin/deleted-students", api_admin_deleted_students)
    app.router.add_post("/api/admin/message/group", api_admin_message_group)
    app.router.add_get("/api/admin/profile", api_admin_profile_get)
    app.router.add_post("/api/admin/profile", api_admin_profile_set)
    app.router.add_post("/api/admin/attendance-update", api_admin_attendance_update)
    app.router.add_get("/api/admin/warnings", api_admin_warnings)
    app.router.add_post("/api/admin/send-homework", api_admin_send_homework)
    app.router.add_post("/api/admin/update-homework", api_admin_update_homework)
    app.router.add_get("/api/admin/homework-tasks", api_admin_homework_tasks)
    app.router.add_post("/api/admin/homework-task-update", api_admin_homework_task_update)
    app.router.add_post("/api/admin/homework-task-bulk-update", api_admin_homework_task_bulk_update)
    app.router.add_post("/api/admin/restore-homework", api_admin_restore_homework)
    app.router.add_post("/api/admin/delete-homework", api_admin_delete_homework)
    app.router.add_get("/api/admin/message-templates", api_admin_message_templates)
    app.router.add_get("/api/admin/audit-logs", api_admin_audit_logs)
    app.router.add_get("/api/admin/weekly-stats", api_admin_weekly_stats)
