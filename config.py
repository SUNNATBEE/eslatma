"""
config.py — Barcha muhit o'zgaruvchilari shu yerda joylashgan.
.env faylidan yuklanadi, default qiymatlar bilan.
"""

import os
from dotenv import load_dotenv

# .env faylini yuklaymiz
load_dotenv()


def _get_required(key: str) -> str:
    """Majburiy o'zgaruvchi yo'q bo'lsa — xato ko'taramiz."""
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Muhim muhit o'zgaruvchisi topilmadi: {key}\n"
                         f"Iltimos .env faylini tekshiring.")
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
