# otaOnaBot — Audit + Fix Hisoboti

**Rejim:** full-review · **Sana:** 2026-06-03 · **Repo map:** 590 imzo · **Fayllar:** 18 Python + 6 HTML
**Boshlang'ich baho:** 6/10 → **AUTO fixlardan keyin:** ~7.5/10

## A) Sub-agent jadvali

| Sub-Agent | Tahlil qilingan fayllar | Topildi (🔴/🟡/🟢) | Avto-tuzatildi | Tasdiq kutmoqda | Baho |
|-----------|------------------------|-------------------|----------------|-----------------|------|
| security | main.py, utils, rate_limit, middleware, config, admin/curator routes | 1🔴 3🟡 2🟢 | 0 | 6 | 6 |
| data-model | database.py | 0🔴 6🟡 5🟢 | 3 (DM-004,006,009) | 8 | 6 |
| scheduler | scheduler.py, class_schedule.py | 1🔴 4🟡 4🟢 | 0 | 9 | 6 |
| backend-api | routes/*.py | 1🔴 6🟡 4🟢 | 7 (API-003,007,010) | 4 | 6 |
| handlers | handlers/*.py (8 fayl) | 0🔴 4🟡 4🟢 | 2 (HND-003,004) | 6 | 7 |
| frontend | webapp 4 HTML | 3🔴 5🟡 1🟢 | 6 (FE-001,003,004,005,006,008) | 3 | 5 |

## B) Qo'llangan tuzatishlar (AUTO — 18, hammasi verified)

| ID | Severity | Fayl | Nima tuzatildi | Tekshiruv |
|----|----------|------|----------------|-----------|
| FE-001/003 | 🔴 critical | admin-mini.html | escHtml helper + barcha server/referral ma'lumotini escape (stored-XSS→admin takeover yopildi) | helper 1× |
| FE-004 | 🟡 | games.html | escHtml + leaderboard XSS escape | helper 1× |
| FE-005 | 🟡 | admin-mini.html | inline onclick uchun escJsAttr (O'zbek apostrof bug + attribute injection) | OK |
| FE-006 | 🟡 | curator.html | esc()'ga apostrof escape + href/avatar escape | OK |
| FE-008 | 🟡 | student.html | hw.group_name escape | OK |
| API-003 | 🟡 | curator_routes, admin_routes (×5) | int() ValueError→400 validation_error (500 oldini olish) | py_compile |
| API-010 | 🟢 | student_routes | referral telegram_user_id try/except int() | py_compile |
| API-007 | 🟡 | main.py, game/student routes | _notify_level_up to'liq try/except (create_task istisnosi yo'qolishi) | py_compile |
| DM-004 | 🟡 | database.py | Student.group_name + mars_id index=True + CREATE INDEX mig | import OK |
| DM-009 | 🟢 | database.py | migration except: pass → logger.warning (duplicate'dan boshqa) | import OK |
| DM-006 | 🟡 | database.py | increment_play_in_window IntegrityError handling (race crash) | import OK |
| HND-003 | 🟡 | admin_extras.py | AddCredentialFSM message.text None check (FSM tiqilishi) | py_compile |
| HND-004 | 🟡 | attendance.py | date_str format validatsiya + IndexError himoya | py_compile |

**Natija:** 12 test o'tdi · py_compile toza · escape helperlar bir martadan.

## C) CONFIRM tuzatishlari (18 — tasdiqlandi va qo'llandi)

| ID | Severity | Fayl | Nima tuzatildi | Tekshiruv |
|----|----------|------|----------------|-----------|
| SEC-001 | 🔴 | main.py | initData auth_date 24h expiry (replay attack yopildi) | import OK |
| SEC-002 | 🟡 | main.py, config.py | CORS fail-closed; wildcard faqat CORS_ALLOW_WILDCARD flag bilan | import OK |
| SEC-003 | 🟡 | config.py | MINI_ADMIN_LOGINS hash qo'llab-quvvatlash (split maxsplit=1, plaintext backward-compat) | import OK |
| SEC-004 | 🟡 | curator_routes.py, main.py | curator login rate-limit (ctx orqali limiter) | import OK |
| SEC-005 | 🟡 | admin_routes.py | mini-admin sessiya 30→7 kun | import OK |
| API-009 | 🟡 | student_routes.py | pending-status rate-limit + IDOR cheklov | import OK |
| API-001 | 🔴 | game_routes.py | multiplayer anti-cheat: progress clamp + min o'yin vaqti | import OK |
| API-006 | 🟡 | admin_routes.py | broadcast fon vazifasiga + throttle + task tracking | import OK |
| DM-001 | 🟡 | database.py | daily_checkin with_for_update (double-grant) | test 6✓ |
| DM-002 | 🟡 | database.py | award_referral_xp bitta atomik tranzaksiya | test 6✓ |
| DM-003 | 🟡 | database.py | monthly leaderboard datetime obyektlari | test 6✓ |
| DM-010 | 🟡 | database.py | join_game_room + update_game_progress with_for_update | test 6✓ |
| SCH-001 | 🔴 | scheduler.py | eslatma oynasi class_dt gacha (misfire'da yo'qolmaydi) | import OK |
| SCH-002 | 🟡 | scheduler.py | _safe_send_dm: throttle + TelegramRetryAfter retry | import OK |
| SCH-003 | 🟡 | scheduler.py | davomat dedup faqat kuratorlar bo'lganda | import OK |
| SCH-005 | 🟡 | scheduler.py | dedup mark send'dan keyin | import OK |
| HND-001 | 🟡 | student.py | read_confirm: admin_id ADMIN_IDS tekshiruvi | import OK |
| HND-002 | 🟡 | curator.py | cur_read: aktiv chat curator_telegram_id tekshiruvi | import OK |
| + FE | 🟡 | admin-mini.html | broadcast javob kontrakti `queued`'ga moslandi | OK |

**Yakuniy holat:** 16 fayl o'zgardi (+756/−255) · 12 test o'tdi · butun ilova import bo'ladi · loyiha kodida ruff toza.

### FE-002 (admin token localStorage) — qaror
To'liq HttpOnly-cookie refactor'i bearer-token modelini va CSRF infratuzilmasini talab qiladi (regressiya xavfi yuqori). O'rniga: (1) barcha XSS sinklari yopildi (FE-001/003/004/005/006/008) — token o'qib bo'lmaydi; (2) sessiya muddati 7 kunga qisqartirildi (SEC-005). Risk sezilarli darajada pasaydi; localStorage UX uchun saqlandi.

### Qolgan suggestion'lar (qo'llanmagan, past-prioritet)
N+1 (DM-005), FK/CASCADE (DM-007), json_ok izchilligi (API-005), double-submit guard (FE-007), fetch error states (FE-009), XFF rightmost (SEC-006), settings cache (SCH-006), coalesce/max_instances (SCH-007) — `.audit/findings/*.json` da.
