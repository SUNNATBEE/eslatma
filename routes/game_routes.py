"""
routes/game_routes.py — O'yin API endpointlari
Endpointlar: /api/game/*
"""

import asyncio
from datetime import datetime

from aiohttp import web

from routes.api_json import json_err

# Har o'yin uchun server tomonda ruxsat etilgan maksimal XP.
# Frontenddagi savol soni × har to'g'ri javob XP'siga mos (mijozga ishonmaymiz):
#   quiz: 10×2, css_duel: 10×3, bug_hunter: 8×5,
#   code_order: 6×5, tag_match: 10×2, selector_quiz: 10×2
GAME_MAX_XP: dict[str, int] = {
    "quiz": 20,
    "css_duel": 30,
    "bug_hunter": 40,
    "code_order": 30,
    "tag_match": 20,
    "selector_quiz": 20,
}
_GAME_XP_FALLBACK = 30  # noma'lum o'yin turi uchun ehtiyot chegarasi

# ── Multiplayer (typing_race) anti-cheat chegaralari ─────────────────────────
# Mijoz o'yin boshlanishi bilanoq {progress:100, finished:true} POST qilib XP
# yutib ketmasligi uchun server tomonda minimal real o'yin vaqti talab qilinadi.
# Inson maksimal taxminan shu tezlikda yozadi — bundan tez = bot/cheat.
MAX_CHARS_PER_SEC = 20.0
MIN_GAME_SECONDS = 5  # matn maydoni bo'lmasa ishlatiladigan qat'iy chegara


def setup_game_routes(app: web.Application, ctx: dict) -> None:
    """O'yin va leaderboard endpointlarini ro'yxatdan o'tkazadi."""
    db = ctx["db"]
    _auth = ctx["auth"]
    _mini_admin_auth = ctx["mini_admin_auth"]
    _notify_level_up = ctx["notify_level_up"]

    # ── Solo o'yin natijasi ────────────────────────────────────────────────────

    async def api_game_score(request: web.Request) -> web.Response:
        """Solo o'yin natijasini saqlaydi (+XP)."""
        user_id = _auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        student = await db.get_student(user_id)
        if not student:
            return json_err("Not registered", code="not_registered", status=404)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        game_type = (body.get("game_type") or "").strip()[:30]
        try:
            score = int(body.get("score", 0))
            xp_earned = int(body.get("xp_earned", 0))
        except (ValueError, TypeError):
            return json_err("Noto'g'ri qiymat", code="validation_error", status=400)
        if not game_type:
            return json_err("game_type kerak", code="validation_error", status=400)
        # Salbiy/aql bovar qilmas qiymatlardan himoya
        score = max(0, min(score, 1_000_000))
        xp_earned = max(0, xp_earned)
        # XP'ni server tomonda har o'yin uchun belgilangan maksimal bilan cheklaymiz
        # (mijoz yuborgan xp_earned ga ishonmaymiz)
        xp_earned = min(xp_earned, GAME_MAX_XP.get(game_type, _GAME_XP_FALLBACK))
        # Cooldown faol bo'lsa — natija saqlanadi, ammo XP berilmaydi
        # (3 soatlik cheklovni server tomonda majburlab, cheksiz XP yig'ishni to'xtatamiz)
        window = await db.get_play_window(user_id, game_type)
        if window.get("blocked"):
            xp_earned = 0
        await db.save_game_score(user_id, game_type, score, xp_earned)
        # Bu o'yin uchun cooldown'ni server tomonda yoqamiz (XP berilgan bo'lsa)
        if xp_earned > 0:
            await db.increment_play_in_window(user_id, game_type)
        prog = await db.get_student_progress(user_id)
        lvup = False
        if prog and prog.get("level", 1) > (student.level or 1):
            lvup = True
            asyncio.create_task(_notify_level_up(user_id, prog["level"]))
        best = await db.get_game_best_scores(user_id)
        return web.json_response(
            {
                "ok": True,
                "xp_earned": xp_earned,
                "new_xp": prog.get("xp", 0) if prog else 0,
                "new_level": prog.get("level", 1) if prog else 1,
                "level_name": prog.get("level_name", "") if prog else "",
                "next_level_xp": prog.get("next_level_xp", 0) if prog else 0,
                "leveled_up": lvup,
                "best_score": best.get(game_type, score),
            }
        )

    # ── Multiplayer xonalar ────────────────────────────────────────────────────

    async def api_game_rooms_get(request: web.Request) -> web.Response:
        """Ochiq multiplayer xonalar ro'yxati."""
        user_id = _auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        game_type = request.rel_url.query.get("type", "typing_race")
        rooms = await db.get_open_game_rooms(game_type)
        return web.json_response(
            {
                "rooms": [
                    {
                        "id": r.id,
                        "player1_name": r.player1_name,
                        "game_type": r.game_type,
                        "created_at": r.created_at.isoformat() if r.created_at else "",
                    }
                    for r in rooms
                    if r.player1_id != user_id
                ]
            }
        )

    async def api_game_rooms_post(request: web.Request) -> web.Response:
        """Yangi multiplayer xona yaratadi."""
        user_id = _auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        student = await db.get_student(user_id)
        if not student:
            return json_err("Not registered", code="not_registered", status=404)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        game_type = body.get("game_type", "typing_race")
        room = await db.create_game_room(user_id, student.full_name, game_type)
        return web.json_response(
            {"ok": True, "room": {"id": room.id, "text": room.text_passage, "status": room.status}}
        )

    async def api_game_room_get(request: web.Request) -> web.Response:
        """Xona holati — polling uchun."""
        user_id = _auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            room_id = int(request.match_info["room_id"])
        except (ValueError, TypeError):
            return json_err("Noto'g'ri room_id", code="invalid_room_id", status=400)
        room = await db.get_game_room(room_id)
        if not room:
            return json_err("Xona topilmadi", code="not_found", status=404)
        return web.json_response(
            {
                "id": room.id,
                "status": room.status,
                "text": room.text_passage,
                "player1_name": room.player1_name,
                "player1_id": room.player1_id,
                "player2_name": room.player2_name,
                "player2_id": room.player2_id,
                "p1_progress": room.p1_progress,
                "p2_progress": room.p2_progress,
                "p1_finished": room.p1_finished,
                "p2_finished": room.p2_finished,
                "winner_id": room.winner_id,
            }
        )

    async def api_game_room_join(request: web.Request) -> web.Response:
        """Xonaga qo'shilish."""
        user_id = _auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        student = await db.get_student(user_id)
        if not student:
            return json_err("Not registered", code="not_registered", status=404)
        try:
            room_id = int(request.match_info["room_id"])
        except (ValueError, TypeError):
            return json_err("Noto'g'ri room_id", code="invalid_room_id", status=400)
        room = await db.join_game_room(room_id, user_id, student.full_name)
        if not room:
            return json_err("Xona band yoki topilmadi", code="room_unavailable", status=400)
        return web.json_response(
            {
                "ok": True,
                "room": {
                    "id": room.id,
                    "text": room.text_passage,
                    "status": room.status,
                    "player1_name": room.player1_name,
                    "player2_name": room.player2_name,
                },
            }
        )

    async def api_game_room_progress(request: web.Request) -> web.Response:
        """Typing progress yangilash."""
        user_id = _auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            room_id = int(request.match_info["room_id"])
        except (ValueError, TypeError):
            return json_err("Noto'g'ri room_id", code="invalid_room_id", status=400)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        try:
            progress = int(body.get("progress", 0))
        except (ValueError, TypeError):
            return json_err("Noto'g'ri qiymat", code="validation_error", status=400)
        # progress'ni 0..100 oralig'iga clamp qilamiz (mijoz qiymatiga ishonmaymiz).
        progress = max(0, min(100, progress))
        finished = bool(body.get("finished", False))

        # ── Anti-cheat: finished=true bo'lganda minimal real o'yin vaqtini talab qil ──
        # Mijoz o'yin boshlanishi bilanoq finished=true yuborsa, XP bermaymiz.
        # created_at — naive UTC (server_default=func.now()), shuning uchun utcnow() bilan
        # solishtiriladi. Avval xona holatini o'qib, o'tgan vaqtni hisoblaymiz.
        if finished:
            pre = await db.get_game_room(room_id)
            if pre is None:
                return json_err("Xona topilmadi", code="not_found", status=404)
            created = pre.created_at
            elapsed = None
            if created is not None:
                try:
                    # naive (UTC) bo'lsa to'g'ridan-to'g'ri, aware bo'lsa tzinfo'ni olib tashlaymiz.
                    if created.tzinfo is not None:
                        created = created.replace(tzinfo=None)
                    elapsed = (datetime.utcnow() - created).total_seconds()
                except Exception:
                    elapsed = None
            # Minimal kerakli vaqt: matn uzunligiga nisbatan, aks holda qat'iy chegara.
            text = pre.text_passage or ""
            if text:
                min_seconds = max(MIN_GAME_SECONDS, len(text) / MAX_CHARS_PER_SEC)
            else:
                min_seconds = float(MIN_GAME_SECONDS)
            # Vaqt aniqlangan VA juda qisqa bo'lsa — finished'ni qabul qilmaymiz
            # (progress saqlanadi, lekin g'olib/XP belgilanmaydi). Mavjud javob shaklini buzmaymiz.
            if elapsed is not None and elapsed < min_seconds:
                finished = False

        room = await db.update_game_progress(room_id, user_id, progress, finished)
        if not room:
            return json_err("Xona topilmadi", code="not_found", status=404)
        # XP faqat o'yin tugagach VA atomik tarzda bir martagina beriladi.
        # claim_room_xp() faqat birinchi chaqiruvda True qaytaradi — shuning uchun
        # finished=true bilan qayta-qayta so'rov yuborib XP yig'ib bo'lmaydi.
        if room.status == "finished" and room.winner_id and await db.claim_room_xp(room.id):
            await db.add_xp(room.winner_id, 20)
            await db.record_game_win(room.winner_id)
            loser_id = room.player2_id if room.winner_id == room.player1_id else room.player1_id
            if loser_id:
                await db.add_xp(loser_id, 5)
        return web.json_response(
            {
                "ok": True,
                "winner_id": room.winner_id,
                "status": room.status,
                "p1_progress": room.p1_progress,
                "p2_progress": room.p2_progress,
            }
        )

    # ── Leaderboard ────────────────────────────────────────────────────────────

    async def api_game_leaderboard(request: web.Request) -> web.Response:
        """O'yin bo'yicha global top-10."""
        user_id = _mini_admin_auth(request) or _auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        game_type = request.rel_url.query.get("game_type") or request.rel_url.query.get("type") or "quiz"
        rows = await db.get_game_global_scores(game_type, limit=10)
        return web.json_response({"leaders": rows})

    # ── Play count / limit ─────────────────────────────────────────────────────

    async def api_game_plays_today(request: web.Request) -> web.Response:
        """3 soatlik cooldown uchun o'ynash ma'lumotlari."""
        user_id = _auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        windows = await db.get_all_play_windows(user_id)
        return web.json_response(windows)

    async def api_game_record_play(request: web.Request) -> web.Response:
        """O'yin boshlanishida o'ynash sonini oshiradi."""
        user_id = _auth(request)
        if not user_id:
            return json_err("Unauthorized", code="unauthorized", status=401)
        try:
            body = await request.json()
        except Exception:
            return json_err("Bad JSON", code="bad_json", status=400)
        game_type = (body.get("game_type") or "").strip()
        if not game_type:
            return json_err("game_type kerak", code="validation_error", status=400)
        current = await db.get_play_window(user_id, game_type)
        if current["blocked"]:
            return web.json_response(
                {
                    "blocked": True,
                    "plays_left": 0,
                    "play_count": current["count"],
                    "seconds_left": current["seconds_left"],
                }
            )
        result = await db.increment_play_in_window(user_id, game_type)
        return web.json_response(
            {
                "blocked": result["blocked"],
                "plays_left": result["plays_left"],
                "play_count": result["count"],
                "seconds_left": result["seconds_left"],
            }
        )

    # ── Route registration ─────────────────────────────────────────────────────

    app.router.add_post("/api/game/score", api_game_score)
    app.router.add_get("/api/game/rooms", api_game_rooms_get)
    app.router.add_post("/api/game/rooms", api_game_rooms_post)
    app.router.add_get("/api/game/rooms/{room_id}", api_game_room_get)
    app.router.add_post("/api/game/rooms/{room_id}/join", api_game_room_join)
    app.router.add_post("/api/game/rooms/{room_id}/progress", api_game_room_progress)
    app.router.add_get("/api/game/leaderboard", api_game_leaderboard)
    app.router.add_get("/api/game/plays-today", api_game_plays_today)
    app.router.add_post("/api/game/record-play", api_game_record_play)
