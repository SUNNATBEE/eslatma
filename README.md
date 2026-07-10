# otaOnaBot

Telegram bot and **Telegram Mini App** backend for an IT training center (Mars IT, Uzbekistan): student registration, homework, attendance, curator relay, XP / levels / games, **AI homework review**, and admin tools.

UI copy and inline documentation are primarily in **Uzbek**; this README is in English for contributors and hosting providers.

## Stack

- **Python 3.12** — [aiogram](https://docs.aiogram.dev/) 3.x, [aiohttp](https://docs.aiohttp.org/) (HTTP + Mini App API), [APScheduler](https://apscheduler.readthedocs.io/), [SQLAlchemy](https://www.sqlalchemy.org/) 2 + aiosqlite
- **Front** — static Mini App pages under `webapp/` (HTML/CSS/JS)

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # if present; otherwise create .env (see below)
python main.py
```

Minimum **`.env`** (see `config.py` for full list):

| Variable        | Description                                      |
|-----------------|--------------------------------------------------|
| `BOT_TOKEN`     | From [@BotFather](https://t.me/BotFather)        |
| `ADMIN_IDS`     | Comma-separated Telegram user IDs                |
| `DATABASE_URL`  | Default: `sqlite+aiosqlite:///bot.db`            |
| `WEBAPP_URL`    | Public HTTPS base URL of this service (Mini App) |
| `TIMEZONE`      | Default: `Asia/Tashkent`                         |

HTTP server listens on `PORT` (default **8080**). Health: `GET /health` → `OK ✅`.

### AI homework review (optional)

Students post work with `#vazifa` in a group; the bot reviews it via **Anthropic
Claude** and replies in Uzbek + Russian. Requires `ANTHROPIC_API_KEY` **and**
disabling group privacy in BotFather (`/setprivacy` → Disable).

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Required to enable the feature |
| `AI_MODEL` | `claude-sonnet-4-6` | Higher quality: `claude-opus-4-8` |
| `AI_HOMEWORK_TRIGGERS` | `#vazifa,#uyvazifa,#дз,#homework` | Trigger hashtags |
| `AI_HOMEWORK_DAILY_LIMIT` | `5` | Per-student daily limit (`0` = unlimited) |

Full reference, formats, security, and troubleshooting: **`docs/AI_HOMEWORK.md`**.

### Monitoring & readiness

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Liveness (plain `OK ✅`) |
| `GET /ready` | Readiness: DB + APScheduler (`200` / `503` JSON) |
| `GET /api/meta/version` | `APP_VERSION`, `GIT_COMMIT_SHA` (JSON) |

**CORS:** If `WEBAPP_URL` is set, browser `Origin` must match that origin (plus `https://web.telegram.org` by default) or entries in `CORS_ALLOW_ORIGINS`. If no origins are configured, the API uses `*` (local dev).

**Logs:** Set `LOG_JSON=1` for one JSON object per line on stdout (aggregator-friendly).

**SQLite backup:** `python scripts/backup_sqlite.py` (optional `BACKUP_DIR`).

See `CONTRIBUTING.md` and `CHANGELOG.md`.

## Development quality gates

```bash
pip install -r requirements-dev.txt
ruff check .
ruff format --check .
python -m compileall -q .
```

CI (`.github/workflows/ci.yml`) runs Ruff and compileall.

## Project layout (short)

| Path            | Role |
|-----------------|------|
| `main.py`       | Bot + dispatcher, scheduler, aiohttp app |
| `config.py`     | Environment |
| `database.py`   | Models and `DatabaseService` |
| `ai_service.py` | Anthropic Claude client (AI homework review) |
| `homework_extract.py` | Telegram messages → Claude content blocks |
| `scheduler.py`  | Reminders, scheduled jobs, etc. |
| `handlers/`     | Telegram handlers |
| `routes/`       | JSON API for Mini App |
| `webapp/`       | Mini App static assets |

More detail: `CLAUDE.md` and `CLAUDE-details.md` (maintainer notes).

## Deployment

- **Docker** — see repo `Dockerfile` / `render.yaml` / `railway.toml`
- Set `PORT` and `WEBAPP_URL` to your public URL; Mini App must be served over **HTTPS**

## License

Proprietary / internal — add a `LICENSE` file if you open-source or redistribute.
