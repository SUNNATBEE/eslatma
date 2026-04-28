# otaOnaBot

Telegram bot and **Telegram Mini App** backend for an IT training center (Mars IT, Uzbekistan): student registration, homework, attendance, curator relay, XP / levels / games, and admin tools.

UI copy and inline documentation are primarily in **Uzbek**; this README is in English for contributors and hosting providers.

## Stack

- **Python 3.12** — [aiogram](https://docs.aiogram.dev/) 3.x, [aiohttp](https://docs.aiohttp.org/) (HTTP + Mini App API), [APScheduler](https://apscheduler.readthedocs.io/), [SQLAlchemy](https://www.sqlalchemy.org/) 2 + aiosqlite
- **Front** — static Mini App pages under `webapp/` (HTML/CSS/JS), E2E with Playwright (`npm run test:e2e`). Barcha CI qadamlari bir joyda: `npm run test:ci` (yoki `bash scripts/run-ci.sh`).

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

Bitta buyruq (Python venv + `npm ci` faollashtirilgan deb hisoblanadi):

```bash
pip install -r requirements-dev.txt
npm ci
npx playwright install --with-deps chromium   # birinchi marta
npm run test:ci    # = bash scripts/run-ci.sh
```

Qo‘lda qadamlar (xuddi GitHub Actions bilan):

```bash
pip install -r requirements-dev.txt
ruff check .
ruff format --check .
python -m compileall -q .
pytest tests/ -v
python -m unittest discover -s tests -p "test_*.py" -v
npm ci && npm run test:e2e
```

CI (`.github/workflows/ci.yml`) runs Ruff, compileall, both test suites, and Playwright e2e.

## Project layout (short)

| Path            | Role |
|-----------------|------|
| `main.py`       | Bot + dispatcher, scheduler, aiohttp app |
| `config.py`     | Environment |
| `database.py`   | Models and `DatabaseService` |
| `scheduler.py`  | Reminders, weekly leaderboard broadcast, etc. |
| `handlers/`     | Telegram handlers |
| `routes/`       | JSON API for Mini App |
| `webapp/`       | Mini App static assets |
| `e2e-tests/`    | Playwright |

More detail: `CLAUDE.md` and `CLAUDE-details.md` (maintainer notes).

## Deployment

- **Docker** — see repo `Dockerfile` / `render.yaml` / `railway.toml`
- Set `PORT` and `WEBAPP_URL` to your public URL; Mini App must be served over **HTTPS**

## License

Proprietary / internal — add a `LICENSE` file if you open-source or redistribute.
