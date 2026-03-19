# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telegram bot for an educational center (Mars IT O'quv Markaz) in Uzbekistan. Manages student registration, daily lesson reminders (odd/even day scheduling), homework distribution, attendance tracking, a Q&A system, curator relay messaging, and a gamification system (XP, levels, streaks, game leaderboards). Includes Telegram Mini Apps for students, curators, and admins.

## Running the Bot

```bash
# Local development
cp .env.example .env   # fill in BOT_TOKEN, ADMIN_IDS
pip install -r requirements.txt
python main.py

# Docker
docker build -t otaonabot .
docker run -e BOT_TOKEN="..." -e ADMIN_IDS="..." -p 8080:8080 otaonabot
```

No test suite. Use `/test_send` (admin only) to test daily reminders. Health check: `GET /health` → `OK ✅`.

## Key Environment Variables

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token (required) |
| `ADMIN_IDS` | Comma-separated Telegram IDs with full admin access |
| `MINI_ADMIN_IDS` | Comma-separated Telegram IDs with admin-mini.html access only |
| `MINI_ADMIN_LOGINS` | `username:password,user2:pass2` — password login for admin-mini.html |
| `WEBAPP_URL` | Public HTTPS URL (e.g. Render URL) for Mini App buttons |
| `DATABASE_URL` | SQLite path (default: `sqlite+aiosqlite:///bot.db`) |
| `SEND_HOUR` / `SEND_MINUTE` | Daily reminder time (default: `20:00`) |
| `CHANNEL_LINK` | Telegram channel URL shown in student panel |

## Architecture

### Entry Point (`main.py`)
Single large file (~2350 lines) that wires everything together:
1. `_verify_webapp_init_data()` / `_get_user_id_from_init_data()` — HMAC-SHA256 authentication for all Mini App API calls using `X-Init-Data` header
2. `_make_api_app()` — defines all 80+ API endpoints as closures with access to `bot` and `db`. Three auth levels: `_auth()` (student), `_admin_auth()` (ADMIN_IDS only), `_mini_admin_auth()` (ADMIN_IDS + MINI_ADMIN_IDS + password sessions)
3. Password sessions stored in `_mini_sessions` dict in-memory (cleared on restart); tokens via `POST /api/mini-admin/login`
4. Registers 8+ aiogram routers, 3 middleware layers, APScheduler, aiohttp server

### Routers (registered in order — earlier takes priority)
- `commands_router` — `/start` (with `ref_USERID` deep-link for referral flow), `/panel`, `/help`, `/list_groups`
- `curator_router` — curator login FSM and relay messaging between curator↔student via bot
- `registration_router` — FSM-based student onboarding (group → Mars ID + password → phone)
- `student_router` — student dashboard, homework viewing
- `attendance_router` — inline-button attendance marking
- `school_router` — schedule display, Q&A submission
- `admin_extras_router` — stats, Excel export, broadcasting, reminder time change
- `callbacks_router` — all remaining inline button callbacks

### Database (`database.py` — ~1800 lines)
`DatabaseService` class wraps all async SQLAlchemy operations. `init_db()` runs `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE` migrations for backwards compatibility on existing deployments.

**Models** (20 total):
- `Group`, `BotChat` — managed groups and chats where the bot is a member
- `Student` — registered students with `xp`, `level`, `streak_days`, `mars_id`
- `StudentCredential` — valid Mars ID/password pairs (mirrors `credentials.py`)
- `Homework`, `HomeworkHistory`, `HomeworkConfirmation` — per-group homework lifecycle
- `AttendanceRecord`, `Schedule` — daily attendance and class schedules
- `Question` — student Q&A submissions
- `BotSetting` — key-value store for runtime settings (reminder time, auto-message toggles)
- `CuratorSession`, `ActiveCuratorChat` — curator login state and active relay chats
- `DailyMood`, `ChatMessage` — mood tracking and in-app chat
- `GameScore`, `GameRoom`, `GamePlayCount` — gamification: best scores, multiplayer rooms, daily play limits (3 plays/game/day)
- `ReferralStudent` — pending registrations (both referral and direct). `referrer_user_id=0` means direct. Fields: `registration_type` ("referral"/"direct"), `has_group`, `group_time`, `group_day_type`, `teacher_name`, `reject_reason`, `mars_id`, `status` (pending/approved/rejected)
- `AdminProfile` — display name/emoji for admin-mini.html
- `ButtonStat` — inline button click analytics

### Hardcoded Data Files
- `credentials.py` — `MARS_CREDENTIALS` dict (`{mars_id: {name, password, group}}`) and `MARS_GROUPS` list. **Add new students here.** Checked during registration to validate Mars ID/password.
- `curator_credentials.py` — `CURATORS` dict for curator login
- `class_schedule.py` — `CLASS_SCHEDULE` dict mapping group names to lesson times, keyed by `"ODD"` / `"EVEN"` day type
- `keyboards.py` — all `InlineKeyboardMarkup` builder functions

### Scheduler (`scheduler.py`)
APScheduler CronTrigger at `SEND_HOUR:SEND_MINUTE` (Asia/Tashkent). Sends different messages to ODD vs EVEN day groups, and different content for PARENT vs STUDENT audience types. Admin can reschedule via bot without restart.

### Mini Apps (`webapp/`)
Six single-page HTML files, all authenticated via `X-Init-Data` header (Telegram `initData`):

| File | Purpose | Auth |
|---|---|---|
| `student.html` | Student dashboard: homework, attendance, XP/level, games, chat, referral | Student (`_auth`) |
| `games.html` | Standalone games page: Typing, Quiz, Chess, 2048, Memory, Block Blast | Student |
| `admin.html` | Full admin panel (legacy, 7 tabs) | `_admin_auth` |
| `admin-mini.html` | New admin Mini App (8 tabs, password login support) | `_mini_admin_auth` |
| `curator.html` | Curator panel: student list, attendance | Curator session |
| `guide.html` | UZ/RU usage guide | Public |

**`admin-mini.html`** has dual auth: Telegram `initData` OR Bearer token from `POST /api/mini-admin/login`. Tokens stored in browser `localStorage`.

**Gamification in `student.html` / `games.html`:**
- Daily play limits: 3 plays/game/day tracked via `GamePlayCount` (`POST /api/game/record-play`)
- XP animated modal replaces toast notifications
- Sound effects via Web Audio API (oscillator-based, no external files)
- Block Blast: canvas-based 8×8 drag-and-drop puzzle
- Per-game leaderboards via `GET /api/game/leaderboard?game_type=X`

### API Auth Layers in `main.py`
```
_auth(request)             → reads X-Init-Data, verifies HMAC, returns user_id
_admin_auth(request)       → _auth() + must be in ADMIN_IDS
_mini_admin_auth(request)  → _auth() in MINI_ADMIN_IDS  OR  Bearer token in _mini_sessions
```

### Referral Flow
1. Admin shares `t.me/bot?start=ref_{user_id}` link
2. Bot receives `/start ref_{id}` → sends Mini App link to new user
3. New user fills form in `student.html?ref={id}` → `POST /api/referral/register`
4. OR new user presses "Yangi ariza topshirish" → `POST /api/student/pending-register` (no referrer)
5. Admin approves in admin-mini.html → `POST /api/admin/referral-students/{id}/approve`
6. `approve_and_register()`: generates Mars ID `P{id:06d}`, MD5 password, creates `StudentCredential` + `Student` rows, notifies student with Mini App button, awards +500 XP to referrer

### Middleware (`middleware.py`)
- `DatabaseMiddleware` — injects `db: DatabaseService` into every handler via `data["db"]`
- `CallbackAnswerMiddleware` — auto-answers all callback queries
- `ButtonTrackingMiddleware` — records every callback button press to `ButtonStat`
- `TypingMiddleware` — sends "typing..." indicator on incoming messages

## Language Note

All comments, string literals, and user-facing text are in Uzbek (O'zbek tili). This is intentional.

## Deployment

Render (Docker via `render.yaml`). `WEBAPP_URL` must be set to the public Render HTTPS URL. The aiohttp server on port 8080 is the keep-alive endpoint. Also has `railway.toml` for Railway.app deployment.
