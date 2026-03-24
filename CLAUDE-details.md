# CLAUDE-details.md — Batafsil arxitektura

Faqat kerak bo'lganda o'qing. Asosiy qoidalar: `CLAUDE.md`

## Environment Variables
| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | — | required |
| `ADMIN_IDS` | — | comma-separated Telegram IDs |
| `MINI_ADMIN_IDS` | — | admin-mini.html access |
| `MINI_ADMIN_LOGINS` | — | `user:pass,user2:pass2` |
| `WEBAPP_URL` | — | public HTTPS URL for Mini Apps |
| `DATABASE_URL` | `sqlite+aiosqlite:///bot.db` | |
| `SEND_HOUR/MINUTE` | `20:00` | daily reminder time |
| `CHANNEL_LINK` | — | shown in student panel |

## DB Models (22 ta)
```
Group, BotChat
Student              — xp, level, streak_days, mars_id, xp_notice_seen
StudentCredential    — mars_id, password, name, group_name
Homework, HomeworkHistory, HomeworkConfirmation
AttendanceRecord, Schedule
Question
BotSetting           — key/value runtime settings
CuratorSession, ActiveCuratorChat
DailyMood, ChatMessage
GameScore, GameRoom, GamePlayCount
ReferralStudent      — status: pending/approved/rejected, referrer_user_id=0=direct
AdminProfile, ButtonStat
```

## BotSetting Keys
```
SEND_HOUR, SEND_MINUTE
AUTO_MSG_GROUPS, AUTO_MSG_ODD, AUTO_MSG_EVEN
AUTO_MSG_GROUP:{name}, AUTO_MSG_CURATOR:{telegram_id}
```

## Gamification
- Game types: `typing quiz chess 2048 memory block_blast`
- Quiz topics: `quiz_html quiz_css quiz_js quiz_tailwind quiz_react`
- Daily limit: 3 plays/12h window — `_window_key() = str(int(unix_ts//43200))`
- XP modal: `showXpModal()` — never toast for XP events
- Monthly LB: filter `GameScore.created_at` (NOT `played_at`)

## Referral Flow
1. Admin shares `t.me/bot?start=ref_{user_id}`
2. `/start ref_{id}` → Mini App link yuboriladi
3. `POST /api/referral/register` → `ReferralStudent` (status=pending)
4. Admin approves → `approve_and_register()`:
   - Mars ID: `P{id:06d}`, MD5 password
   - `StudentCredential` + `Student` yaratiladi
   - Student DM ga xabar + Mini App button
   - Referrer: +500 XP (agar `referrer_user_id != 0`)

## Middleware
- `DatabaseMiddleware` → `data["db"]`
- `CallbackAnswerMiddleware` → auto-answer callbacks
- `ButtonTrackingMiddleware` → `ButtonStat` yozadi
- `TypingMiddleware` → "typing..." indicator

## Scheduler
- APScheduler CronTrigger, Asia/Tashkent
- **Ertangi** sanani tekshiradi (ODD/EVEN)
- PARENT vs STUDENT audience uchun har xil matn
- Admin runtime da o'zgartirishi mumkin (bot restart kerak emas)

## Curator System
- `curator_credentials.py`: `CURATORS = {"user": {"password":"..","name":"..","groups":[..]}}`
- FSM: `/curator` → username → password → `CuratorSession` DB ga
- Relay: `ActiveCuratorChat` curator↔student bog'laydi
- `curator.html` Bearer token (API auth) va bot relay (`CuratorSession`) — alohida mexanizm

## Mini Apps Auth
```javascript
headers: { 'Content-Type':'application/json', 'X-Init-Data': Telegram.WebApp.initData }
// admin-mini.html ham:
if (token) headers['Authorization'] = `Bearer ${token}`;
```

## AbsenceReasonFSM
- "Kela olmayman" → sabab so'raydi → admins + aktiv kuratorlar + PARENT guruhlariga
- FSM aktiv bo'lsa `curator.py` relay o'tkazib yuboradi
