"""
routes/curator_routes.py — Kurator API endpointlari
Endpointlar: /api/curator/*
"""
from datetime import datetime, timedelta

from aiohttp import web

from config import ADMIN_IDS
from curator_credentials import CURATORS
from utils import verify_secret


def _merge_known_credentials(static_credentials: dict[str, dict], db_credentials: list) -> dict[str, dict]:
    merged = {
        mars_id: {"name": cred["name"], "group": cred["group"]}
        for mars_id, cred in static_credentials.items()
    }
    for cred in db_credentials:
        merged[cred.mars_id] = {"name": cred.name, "group": cred.group_name}
    return merged


def setup_curator_routes(app: web.Application, ctx: dict) -> None:
    """Kurator endpointlarini ro'yxatdan o'tkazadi."""
    bot   = ctx["bot"]
    db    = ctx["db"]
    tz    = ctx["tz"]
    _auth = ctx["auth"]

    # ── Login / logout / me ────────────────────────────────────────────────────

    async def api_curator_me(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        session = await db.get_curator_session(user_id)
        if not session:
            return web.json_response({"logged_in": False})
        c = CURATORS.get(session.curator_key, {})
        return web.json_response({
            "logged_in":   True,
            "curator_key": session.curator_key,
            "full_name":   c.get("full_name", session.curator_key),
            "username":    c.get("telegram_username", ""),
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
        if not cred or not verify_secret(cred["password"], password):
            return web.json_response({"error": "Login yoki parol noto'g'ri"}, status=403)
        await db.set_curator_session(user_id, login)
        await db.update_curator_last_active(user_id)
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

    # ── Students ───────────────────────────────────────────────────────────────

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
        all_credentials = _merge_known_credentials(
            MARS_CREDENTIALS,
            await db.get_all_student_credentials(),
        )
        registered = await db.get_all_students()
        reg_map    = {s.mars_id: s for s in registered if s.mars_id}
        result = []
        for mars_id, cred in all_credentials.items():
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
                "xp":          reg.xp if reg else 0,
                "level":       reg.level if reg else 1,
                "streak_days": reg.streak_days if reg else 0,
            })
        result.sort(key=lambda x: (x["group_name"], x["full_name"]))
        return web.json_response({"students": result})

    async def api_curator_dashboard_stats(request: web.Request) -> web.Response:
        """Kurator uchun bugungi dashboard statistikasi."""
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        session = await db.get_curator_session(user_id)
        if not session:
            return web.json_response({"error": "Not logged in"}, status=403)
        today = datetime.now(tz).strftime("%Y-%m-%d")
        all_students = await db.get_all_students()
        total        = len(all_students)
        att_records  = await db.get_attendance_by_date(today)
        present_count = sum(1 for r in att_records if r.status == "yes")
        absent_count  = sum(1 for r in att_records if r.status == "no")
        pending_count = max(total - present_count - absent_count, 0)
        from database import HomeworkConfirmation
        from sqlalchemy import func as sa_func, select
        async with db.session_factory() as sess:
            hw_result = await sess.execute(
                select(sa_func.count(HomeworkConfirmation.id)).where(
                    HomeworkConfirmation.date_str == today
                )
            )
            hw_done = hw_result.scalar() or 0
        return web.json_response({
            "date": today, "total": total,
            "present": present_count, "absent": absent_count,
            "pending": pending_count, "homework_done": hw_done,
        })

    # ── Attendance ─────────────────────────────────────────────────────────────

    async def api_curator_attendance(request: web.Request) -> web.Response:
        """Davomat holati — kurator uchun (offset=0 bugun, 1=kecha, ...)."""
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        session = await db.get_curator_session(user_id)
        if not session:
            return web.json_response({"error": "Not logged in"}, status=403)
        group_filter = request.rel_url.query.get("group", "all")
        try:
            day_offset = int(request.rel_url.query.get("offset", "0"))
            day_offset = max(0, min(day_offset, 30))
        except (ValueError, TypeError):
            day_offset = 0
        target_date = datetime.now(tz).date() - timedelta(days=day_offset)
        today = target_date.strftime("%Y-%m-%d")
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
            "date": today, "present": present, "absent": absent, "pending": pending,
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
        """Davomat yoqlamasini ota-ona guruhiga yuboradi."""
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
        group_name     = body.get("group_name", "—")
        marks          = body.get("marks", [])
        parent_chat_id = body.get("parent_chat_id")
        date_str       = body.get("date_str", datetime.now(tz).strftime("%Y-%m-%d"))
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
        """Kurator kechikkan o'quvchining davomatini yangilaydi."""
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
            from sqlalchemy import select
            from database import CuratorSession
            async with db.session_factory() as sess:
                result = await sess.execute(select(CuratorSession))
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

    async def api_curator_send_message(request: web.Request) -> web.Response:
        """Kurator Mini App dan o'quvchiga bot orqali xabar yuboradi."""
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
        student_tg_id = body.get("student_telegram_id")
        text          = (body.get("text") or "").strip()
        if not student_tg_id or not text:
            return web.json_response({"error": "student_telegram_id va text majburiy"}, status=400)
        if len(text) > 4000:
            return web.json_response({"error": "Xabar juda uzun (maks 4000 belgi)"}, status=400)
        cname = CURATORS.get(session.curator_key, {}).get("full_name", session.curator_key)
        try:
            await bot.send_message(
                int(student_tg_id),
                f"📩 <b>Kuratordan xabar</b>\n\n👩‍💼 {cname}:\n\n{text}",
            )
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def api_curator_statistics(request: web.Request) -> web.Response:
        """Davomat statistikasi: guruh foizi, TOP-5, oxirgi 7 kun."""
        user_id = _auth(request)
        if not user_id:
            return web.json_response({"error": "Unauthorized"}, status=401)
        session = await db.get_curator_session(user_id)
        if not session:
            return web.json_response({"error": "Not logged in"}, status=403)
        today       = datetime.now(tz).date()
        all_studs   = await db.get_all_students()
        if not all_studs:
            return web.json_response({"groups": [], "top_present": [], "top_absent": [], "chart": []})
        today_str = today.strftime("%Y-%m-%d")
        att_today = await db.get_attendance_by_date(today_str)
        att_map   = {r.user_id: r for r in att_today}
        group_stats: dict = {}
        for s in all_studs:
            g = s.group_name
            if g not in group_stats:
                group_stats[g] = {"total": 0, "present": 0}
            group_stats[g]["total"] += 1
            rec = att_map.get(s.user_id)
            if rec and rec.status == "yes":
                group_stats[g]["present"] += 1
        groups_list = [
            {"group": g, "total": v["total"], "present": v["present"],
             "pct": round(v["present"] / v["total"] * 100) if v["total"] else 0}
            for g, v in sorted(group_stats.items())
        ]
        present_counts: dict = {}
        absent_counts:  dict = {}
        for i in range(30):
            d_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            for r in await db.get_attendance_by_date(d_str):
                if r.status == "yes":
                    present_counts[r.user_id] = present_counts.get(r.user_id, 0) + 1
                else:
                    absent_counts[r.user_id] = absent_counts.get(r.user_id, 0) + 1
        stud_map = {s.user_id: s for s in all_studs}
        top_present = sorted(present_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_absent  = sorted(absent_counts.items(),  key=lambda x: x[1], reverse=True)[:5]
        top_present_list = [
            {"full_name": stud_map[uid].full_name if uid in stud_map else str(uid),
             "group_name": stud_map[uid].group_name if uid in stud_map else "—", "count": cnt}
            for uid, cnt in top_present if uid in stud_map
        ]
        top_absent_list = [
            {"full_name": stud_map[uid].full_name if uid in stud_map else str(uid),
             "group_name": stud_map[uid].group_name if uid in stud_map else "—", "count": cnt}
            for uid, cnt in top_absent if uid in stud_map
        ]
        total_studs = len(all_studs)
        chart = []
        day_names_uz = ["Yak", "Dush", "Sesh", "Chor", "Pay", "Juma", "Shan"]
        for i in range(6, -1, -1):
            d     = today - timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            recs  = await db.get_attendance_by_date(d_str)
            p_cnt = sum(1 for r in recs if r.status == "yes")
            pct   = round(p_cnt / total_studs * 100) if total_studs else 0
            chart.append({"date": d_str, "label": day_names_uz[d.weekday()],
                          "present": p_cnt, "total": total_studs, "pct": pct})
        return web.json_response({
            "groups": groups_list, "top_present": top_present_list,
            "top_absent": top_absent_list, "chart": chart,
        })

    # ── Route registration ─────────────────────────────────────────────────────

    app.router.add_get("/api/curator/me",                  api_curator_me)
    app.router.add_post("/api/curator/login",              api_curator_login)
    app.router.add_post("/api/curator/logout",             api_curator_logout)
    app.router.add_get("/api/curator/students",            api_curator_students)
    app.router.add_get("/api/curator/all-students",        api_curator_all_students)
    app.router.add_get("/api/curator/dashboard-stats",     api_curator_dashboard_stats)
    app.router.add_get("/api/curator/attendance",          api_curator_attendance)
    app.router.add_get("/api/curator/parent-groups",       api_curator_parent_groups)
    app.router.add_post("/api/curator/send-yoqlama",       api_curator_send_yoqlama)
    app.router.add_post("/api/curator/update-attendance",  api_curator_update_attendance)
    app.router.add_post("/api/curator/send-message",       api_curator_send_message)
    app.router.add_get("/api/curator/statistics",          api_curator_statistics)
