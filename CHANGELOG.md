# O'zgarishlar jurnali

Barcha muhim o'zgarishlar shu faylda qayd etiladi (Keep a Changelog uslubi).

## [Unreleased]

### Qo'shildi

- CORS: `WEBAPP_URL` / `CORS_ALLOW_ORIGINS` bo'yicha ruxsat etilgan originlar (devda ro'yxat bo'sh bo'lsa `*`)
- `GET /ready` — DB + scheduler holati (503 agar tayyor emas)
- `GET /api/meta/version` — `APP_VERSION`, `GIT_COMMIT_SHA`
- `GET /api/admin/system-status` — mini-admin uchun holat
- Mini-admin login uchun IP bo'yicha tezlik cheklovi (`RATE_LIMIT_LOGIN_*`)
- Barcha asosiy API route fayllarida xato javoblari: `routes.api_json.json_err` — `ok`, `error`, `code` (`admin_routes`, `student_routes`, `curator_routes`, `game_routes`)
- `LOG_JSON=1` — stdout uchun JSON qatorli log
- `scripts/backup_sqlite.py` — SQLite nusxa olish
- `.pre-commit-config.yaml`, `CONTRIBUTING.md`, issue shabloni

### O'zgartirildi

- `database.DatabaseService.check_db_live()` — readiness uchun
- `scheduler.scheduler_health()` — monitoring uchun
