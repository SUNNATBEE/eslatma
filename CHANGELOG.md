# O'zgarishlar jurnali

Barcha muhim o'zgarishlar shu faylda qayd etiladi (Keep a Changelog uslubi).

## [Unreleased]

### Qo'shildi

- **AI uy vazifa tekshiruvi (`#vazifa`)** — o'quvchi guruhga rasm / kod / `.zip` /
  havola / matn + `#vazifa` yuborsa, bot materialni yig'ib **Anthropic Claude**
  orqali professional tahlil qiladi va xato-kamchiliklarni 2 tilda (🇺🇿 + 🇷🇺)
  o'quvchining xabariga reply qiladi.
  - Yangi fayllar: `ai_service.py`, `homework_extract.py`, `handlers/homework_ai.py`
  - Qo'llab-quvvatlanadi: rasm/albom (vision), kod-fayl, ZIP (kod fayllarni ajratadi),
    havola (GitHub→raw, SSRF himoyasi), matn
  - `homework_ai_router` `commands_router`dan **oldin** ulanadi (`auto_save_group`
    xabarni yutmasligi uchun)
  - Sozlamalar (`config.py`, `AI_*`): `ANTHROPIC_API_KEY` (majburiy),
    `AI_MODEL` (default `claude-sonnet-4-6`), `AI_HOMEWORK_TRIGGERS`,
    `AI_HOMEWORK_DAILY_LIMIT` (har o'quvchiga kunlik limit), material chegaralari
  - Yangi bog'liqlik: `anthropic>=0.69`
  - Sozlash: BotFather'da guruh maxfiyligini o'chirish + `ANTHROPIC_API_KEY`.
    Batafsil: `docs/AI_HOMEWORK.md`
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
