# CLAUDE.md — otaOnaBot

Telegram bot — Mars IT O'quv Markaz (Uzbekistan). Student registration, daily reminders, homework, attendance, gamification (XP/levels/games), curator relay, Mini Apps.

## Run
```bash
pip install -r requirements.txt && python main.py
# Docker: docker build -t otaonabot . && docker run -e BOT_TOKEN=... -p 8080:8080 otaonabot
```

**Sifat:** `pip install -r requirements-dev.txt && ruff check . && ruff format --check . && pytest tests/ -v`  
Umumiy tavsif: repo ildizidagi `README.md`.

## Key Files
```
main.py          2650 qator — 80+ API endpoint (aiohttp), aiogram routers, APScheduler
database.py      2100 qator — DatabaseService, 22 model, init_db() migrations
scheduler.py     — APScheduler, daily reminders (Asia/Tashkent, 20:00)
handlers/        — homework_ai, commands, registration, curator, student, attendance, callbacks
webapp/          — 6 Mini App HTML (student, games, admin-mini, curator, guide, admin)
ai_service.py    — Anthropic Claude wrapper (AI uy vazifa tahlili, lazy import)
homework_extract.py — Telegram xabar → Claude content bloklari (rasm/zip/link/matn)
credentials.py   — MARS_CREDENTIALS {mars_id: {name,password,group}}, MARS_GROUPS
class_schedule.py — CLASS_SCHEDULE {"ODD":{}, "EVEN":{}}
keyboards.py     — InlineKeyboardMarkup builders
```

## Auth Layers (main.py)
```
_auth()           → X-Init-Data HMAC → student user_id
_admin_auth()     → _auth() + ADMIN_IDS
_mini_admin_auth() → ADMIN_IDS/MINI_ADMIN_IDS OR Bearer token (_mini_sessions dict)
```

## Router Order (priority: first wins)
`homework_ai → commands → group_join → curator → registration → student → attendance → school → admin_extras → callbacks`
> ⚠️ `homework_ai` MUST be before `commands` — `commands.auto_save_group` is a
> group catch-all that stops propagation; otherwise `#vazifa` never arrives.

## Critical Patterns
```python
# Mini App tugma (TO'G'RI — web_app=, NOTO'G'RI — url=)
InlineKeyboardButton(text="...", web_app=WebAppInfo(url=f"{WEBAPP_URL}/student.html"))

# StudentCredential: cred.name  (full_name EMAS!)

# register_student() → (student, is_new: bool)  — is_new=False: XP saqlanadi

# ALTER TABLE migration pattern:
try: await conn.execute("ALTER TABLE X ADD COLUMN ...")
except: pass
```

## Language
All UI text, comments, string literals → **Uzbek (O'zbek tili)**. Intentional.

## Deployment
Render (Docker, `render.yaml`) + Railway (`railway.toml`). `WEBAPP_URL` = public HTTPS URL.
Health: `GET /health` → `OK ✅`. Readiness: `GET /ready` (JSON). Versiya: `GET /api/meta/version`. Test reminders: `/test_send` (admin only). CORS / `LOG_JSON` / `APP_VERSION`: `config.py` va `README.md`.

## AI Homework (`#vazifa`)
Guruhda o'quvchi `#vazifa` + rasm/kod/zip/havola yuborsa → Claude tahlil → 2 tilli (UZ+RU) reply.
Sozlash: BotFather privacy OFF + `ANTHROPIC_API_KEY`. Batafsil: `docs/AI_HOMEWORK.md`.

## Details
→ Batafsil arxitektura, model ro'yxati, referral flow: `CLAUDE-details.md`
