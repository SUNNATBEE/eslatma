# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telegram bot for an educational center (O'quv Markaz) in Uzbekistan. Manages student registration, daily lesson reminders (odd/even day scheduling), homework distribution, attendance tracking, a Q&A system, and curator relay messaging. Includes a Telegram Mini App (WebApp) for mobile-first attendance and homework viewing.

## Running the Bot

```bash
# Local development
cp .env.example .env   # then fill in BOT_TOKEN, ADMIN_IDS
pip install -r requirements.txt
python main.py

# Docker
docker build -t otaonabot .
docker run -e BOT_TOKEN="..." -e ADMIN_IDS="..." -p 8080:8080 otaonabot
```

No test suite exists. Use `/test_send` command (admin only) to test daily reminders. Health check: `GET /health` returns `OK ✅`.

## Key Environment Variables

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token (required) |
| `ADMIN_IDS` | Comma-separated Telegram user IDs with admin access |
| `WEBAPP_URL` | Public URL of the deployed app (for Mini App buttons) |
| `DATABASE_URL` | SQLite path (default: `sqlite+aiosqlite:///bot.db`) |
| `SEND_HOUR` / `SEND_MINUTE` | Daily reminder time (default: `20:00`) |
| `CHANNEL_LINK` | Telegram channel URL shown in student panel |

## Architecture

**main.py** is the entry point. It wires everything together:
1. Initializes the async SQLite database via SQLAlchemy (`database.py`)
2. Registers 8 aiogram handler routers from `handlers/`
3. Attaches 3 middleware layers (`middleware.py`): DB injection, callback auto-answer, typing indicator
4. Starts APScheduler for daily reminders (`scheduler.py`)
5. Launches an aiohttp web server for health checks and Mini App API

**Routers** (registered in order, earlier routers take priority):
- `commands_router` — `/start`, `/panel`, `/help`, `/list_groups`
- `registration_router` — FSM-based student onboarding
- `student_router` — student dashboard, homework viewing
- `attendance_router` — inline-button attendance marking
- `school_router` — schedule display, Q&A submission
- `curator_router` — curator login and relay messaging
- `admin_extras_router` — stats, Excel export, broadcasting, time settings
- `callbacks_router` — all remaining inline button callbacks (~742 lines)

**Database** (`database.py`): 10 SQLAlchemy models (Groups, Students, Homework, Attendance, Schedules, Questions, Settings, etc.) with a `DatabaseService` class wrapping all CRUD operations. Injected into handlers via `DatabaseMiddleware`.

**Scheduler** (`scheduler.py`): Sends different daily messages to ODD (Toq) vs EVEN (Juft) day groups, and different content for PARENT vs STUDENT audience types. Reschedules itself if admin changes the time via bot.

**Mini App** (`webapp/`): Two single-page HTML files (`student.html`, `curator.html`) authenticated via HMAC-SHA256 signed Telegram `initData`. Backend API routes live in `main.py` under `/api/`.

**Credentials** (`credentials.py`, `curator_credentials.py`): Hardcoded lists of valid student and curator login credentials. These are checked during registration/login flows.

## Language Note

Comments and string literals throughout the codebase are written in Uzbek (O'zbek tili). This is intentional — the bot serves Uzbek-speaking students and parents.

## Deployment

Deployed to Render via Docker (`render.yaml`). The aiohttp server on port 8080 acts as a keep-alive mechanism to prevent Render's free tier from idling. `WEBAPP_URL` must be set to the public Render URL for Mini App buttons to work.
