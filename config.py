"""
config.py — Barcha muhit o'zgaruvchilari shu yerda joylashgan.
.env faylidan yuklanadi, default qiymatlar bilan.
"""

import os
import urllib.parse

from dotenv import load_dotenv

# .env faylini yuklaymiz
load_dotenv()


def _get_required(key: str) -> str:
    """Majburiy o'zgaruvchi yo'q bo'lsa — xato ko'taramiz."""
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Muhim muhit o'zgaruvchisi topilmadi: {key}\nIltimos .env faylini tekshiring.")
    return value


def _parse_admin_ids(raw: str) -> list[int]:
    """'123456,789012' ko'rinishidagi stringni int ro'yxatiga aylantiradi."""
    if not raw.strip():
        return []
    return [int(uid.strip()) for uid in raw.split(",") if uid.strip().isdigit()]


# ─── Bot sozlamalari ─────────────────────────────────────────────────────────
BOT_TOKEN: str = _get_required("BOT_TOKEN")

# Admin Telegram ID lari, vergul bilan ajratilgan: "123456789,987654321"
ADMIN_IDS: list[int] = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))

# Mini Admin ID lari — faqat admin-mini.html ga kirish huquqi
# ADMIN_IDS ro'yxatidagilar ham avtomatik mini-admin hisoblanadi
_mini_raw = os.getenv("MINI_ADMIN_IDS", "")
MINI_ADMIN_IDS: list[int] = list(set(ADMIN_IDS + _parse_admin_ids(_mini_raw)))


# Mini Admin parol logini — "username:password,username2:password2" formatida
# Faqat admin-mini.html uchun (Telegram bo'lmasa ham kirish mumkin)
#
# XAVFSIZLIK: parolni plaintext o'rniga hash qilib qo'yish tavsiya etiladi.
# Hash generatsiya: `python -c "from utils import hash_secret; print(hash_secret('parol'))"`
# Hash formati `pbkdf2_sha256$iter$salt$derived` — `$` ajratuvchi ishlatadi, `:` emas,
# shuning uchun split(":", 1) hash qiymatini buzmaydi (faqat birinchi `:` username/parolni
# ajratadi). verify_secret() (utils.py) ham hash, ham legacy plaintext'ni qabul qiladi.
def _parse_logins(raw: str) -> dict[str, str]:
    result = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" in pair:
            # Faqat birinchi ':' bo'yicha ajratamiz — parol/hash ichidagi belgilar buzilmaydi.
            u, p = pair.split(":", 1)
            if u.strip():
                result[u.strip()] = p.strip()
    return result


MINI_ADMIN_LOGINS: dict[str, str] = _parse_logins(os.getenv("MINI_ADMIN_LOGINS", ""))

# ─── Ma'lumotlar bazasi ───────────────────────────────────────────────────────
# aiosqlite uchun: "sqlite+aiosqlite:///bot.db"
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db")

# ─── Vaqt va rejalashtirish ───────────────────────────────────────────────────
# O'zbekiston: Asia/Tashkent (UTC+5)
TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Tashkent")

# Xabar yuborish vaqti (24-soatlik format)
SEND_HOUR: int = int(os.getenv("SEND_HOUR", "20"))
SEND_MINUTE: int = int(os.getenv("SEND_MINUTE", "0"))

# ─── Web-server (keep-alive) ──────────────────────────────────────────────────
# Render/Koyeb uchun port (ular PORT muhit o'zgaruvchisini avtomatik o'rnatadi)
PORT: int = int(os.getenv("PORT", "8080"))

# ─── O'quvchilar kanali ───────────────────────────────────────────────────────
# Frontend darslari kanali havolasi (.env da CHANNEL_LINK=https://t.me/...)
CHANNEL_LINK: str = os.getenv("CHANNEL_LINK", "https://t.me/sunnatbee_lessons")

# ─── Guruhga kirish arizasi (join request gate) ───────────────────────────────
# Yangi a'zo guruhga kirishdan oldin bot DM da ism/yosh/qiziqishlarni so'raydi
# va majburiy kanallarga obunani tekshiradi. Faqat guruhda "Approve new members"
# yoqilgan va bot admin bo'lsa ishlaydi.
JOIN_GATE_ENABLED: bool = os.getenv("JOIN_GATE_ENABLED", "1").lower() in ("1", "true", "yes")

# "Bot orqali kirish" (Yo'l B) — anketa tugagach bot shu guruhga bir martalik
# taklif havolasi yuboradi. Bo'sh bo'lsa, bot a'zo bo'lgan yagona guruh ishlatiladi.
def _parse_int_or_none(raw: str) -> int | None:
    raw = (raw or "").strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


JOIN_TARGET_CHAT_ID: int | None = _parse_int_or_none(os.getenv("JOIN_TARGET_CHAT_ID", ""))

# Anketadan keyin majburiy kanal obunasini talab qilishmi? (hozircha o'chiq)
JOIN_REQUIRE_SUBSCRIPTION: bool = os.getenv("JOIN_REQUIRE_SUBSCRIPTION", "0").lower() in ("1", "true", "yes")


def _parse_required_channels(raw: str) -> list[dict]:
    """Majburiy obuna kanallarini ajratadi.

    Format: "chat::Label::link;chat2::Label2::link2"
      chat  — tekshirish uchun @username yoki -100... chat_id.
              Bo'sh bo'lsa (masalan yopiq invite havola) — obuna TEKSHIRILMAYDI,
              faqat tugma ko'rsatiladi.
      Label — tugma matni
      link  — bosiladigan havola (https://t.me/... yoki instagram)
    """
    items: list[dict] = []
    for part in (raw or "").split(";"):
        part = part.strip()
        if not part:
            continue
        seg = [s.strip() for s in part.split("::")]
        items.append(
            {
                "chat": seg[0] if len(seg) > 0 else "",
                "label": seg[1] if len(seg) > 1 else "Kanal",
                "link": seg[2] if len(seg) > 2 else "",
            }
        )
    return items


# Default — foydalanuvchi bergan havolalar (yopiq guruhni faqat chat_id bilan
# tekshirish mumkin, shuning uchun u tugma sifatida qoladi).
_DEFAULT_CHANNELS = (
    "@aidevix::AIDEVIX kanal::https://t.me/aidevix;"
    "::AIDEVIX yopiq guruh::https://t.me/+SRuA2QBbLmo3MDgy"
)
REQUIRED_CHANNELS: list[dict] = _parse_required_channels(os.getenv("REQUIRED_CHANNELS", _DEFAULT_CHANNELS))

# Instagram (Telegram bot orqali TEKSHIRIB BO'LMAYDI — faqat tugma)
INSTAGRAM_LINK: str = os.getenv("INSTAGRAM_LINK", "https://www.instagram.com/aidevix/")

# ─── Telegram Mini App (WebApp) ───────────────────────────────────────────────
# Render/Koyeb HTTPS URL: "https://your-app.onrender.com"
# Bo'sh bo'lsa — WebApp tugmasi ko'rinmaydi
WEBAPP_URL: str = os.getenv("WEBAPP_URL", "")


def _http_origin(url: str) -> str | None:
    u = (url or "").strip()
    if not u:
        return None
    p = urllib.parse.urlparse(u)
    if p.scheme and p.netloc:
        return f"{p.scheme}://{p.netloc}"
    return None


def _parse_comma_list(raw: str) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


# CORS: vergul bilan bir nechta origin ko'rsatiladi (allowlist).
# WEBAPP_URL bo'lsa, uning origin'i avtomatik ro'yxatga qo'shiladi (prod buzilmasligi uchun).
# Xavfsizlik: allowlist bo'sh bo'lsa avtomatik wildcard YO'Q (fail-closed).
# Wildcard ("*") faqat CORS_ALLOW_WILDCARD=1 aniq o'rnatilganda yoqiladi (lokal dev uchun).
_cors_env = _parse_comma_list(os.getenv("CORS_ALLOW_ORIGINS", ""))
_cors_list = list(_cors_env)
_o = _http_origin(WEBAPP_URL)
if _o and _o not in _cors_list:
    _cors_list.append(_o)
# Telegram ichidagi WebApp (ixtiyoriy, default yoqilgan)
if (
    os.getenv("CORS_ALLOW_TELEGRAM_WEB", "1").lower() in ("1", "true", "yes")
    and _cors_list
    and "https://web.telegram.org" not in _cors_list
):
    _cors_list.append("https://web.telegram.org")

CORS_USE_WILDCARD: bool = os.getenv("CORS_ALLOW_WILDCARD", "").lower() in ("1", "true", "yes")
CORS_ORIGINS: frozenset[str] = frozenset(_cors_list)

# Versiya / deploy (monitoring uchun)
APP_VERSION: str = os.getenv("APP_VERSION", "dev")
GIT_COMMIT_SHA: str = (os.getenv("GIT_COMMIT_SHA") or os.getenv("RENDER_GIT_COMMIT") or "")[:48]

# Reverse proxy orqali haqiqiy IP
TRUST_X_FORWARDED_FOR: bool = os.getenv("TRUST_X_FORWARDED_FOR", "").lower() in ("1", "true", "yes")

# Mini-admin login tezligi (bir IP uchun sliding window)
RATE_LIMIT_LOGIN_MAX: int = int(os.getenv("RATE_LIMIT_LOGIN_MAX", "30"))
RATE_LIMIT_LOGIN_WINDOW_SEC: float = float(os.getenv("RATE_LIMIT_LOGIN_WINDOW_SEC", "60"))

# JSON qatorli log (stdout)
LOG_JSON: bool = os.getenv("LOG_JSON", "").lower() in ("1", "true", "yes")
