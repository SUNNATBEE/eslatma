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
def _parse_logins(raw: str) -> dict[str, str]:
    result = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" in pair:
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


# CORS: vergul bilan bir nechta origin yoki bo'sh (wildcard "*", lokal dev uchun).
# WEBAPP_URL bo'lsa, uning origin'i ro'yxatga qo'shiladi.
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

CORS_USE_WILDCARD: bool = len(_cors_list) == 0
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
