"""
handlers/homework_ai.py — Guruhda AI uy vazifa tekshiruvi.

Oqim:
  1. O'quvchi guruhga rasm/kod/zip/havola/matn + #vazifa hashtag yuboradi.
  2. Bot materialni yig'adi (rasm albomlari ham qo'llab-quvvatlanadi).
  3. Claude AI professional tahlil qiladi → xato-kamchiliklarni 2 tilda (UZ+RU) topadi.
  4. Bot natijani o'quvchining xabariga REPLY qilib, guruhga yozadi.

⚠️ ESLATMA: Bot guruhdagi xabarlarni KO'RISHI uchun BotFather'da
   "Group Privacy" rejimi O'CHIRILGAN bo'lishi shart (/setprivacy → Disable).

Bu router commands_router'dan OLDIN ulanadi — aks holda commands.py'dagi
auto_save_group barcha guruh xabarlarini "yutib", bu yerga yetib kelmaydi.
"""

import asyncio
import html
import logging
from datetime import date

from aiogram import Bot, Router
from aiogram.types import Message

import ai_service
from config import (
    AI_HOMEWORK_DAILY_LIMIT,
    AI_HOMEWORK_ENABLED,
    AI_HOMEWORK_TRIGGERS,
)
from database import DatabaseService
from homework_extract import build_homework_payload

logger = logging.getLogger(__name__)
router = Router()

# Albom (media group) buferi: media_group_id → {"messages": [...], "task": Task}
_albums: dict[str, dict] = {}
_ALBUM_DELAY = 1.5  # albom xabarlarini yig'ish uchun kutish (sekund)

# Kunlik limit hisoblagichi: (chat_id, user_id, sana) → soni
_usage: dict[tuple, int] = {}

# Telegram bitta xabar uzunligi chegarasi
_TG_LIMIT = 3900


# ─── Yordamchilar ─────────────────────────────────────────────────────────────


def _has_trigger(message: Message) -> bool:
    text = ((message.text or "") + " " + (message.caption or "")).lower()
    return any(trig in text for trig in AI_HOMEWORK_TRIGGERS)


def _strip_triggers(text: str) -> str:
    out = text
    for trig in AI_HOMEWORK_TRIGGERS:
        # registrga bog'liq bo'lmagan almashtirish
        idx = out.lower().find(trig)
        while idx != -1:
            out = out[:idx] + out[idx + len(trig):]
            idx = out.lower().find(trig)
    return out.strip()


def _check_limit(chat_id: int, user_id: int) -> bool:
    if AI_HOMEWORK_DAILY_LIMIT <= 0:
        return True
    key = (chat_id, user_id, date.today().isoformat())
    return _usage.get(key, 0) < AI_HOMEWORK_DAILY_LIMIT


def _incr_usage(chat_id: int, user_id: int) -> None:
    key = (chat_id, user_id, date.today().isoformat())
    _usage[key] = _usage.get(key, 0) + 1


def _chunk(text: str, limit: int = _TG_LIMIT) -> list[str]:
    """Uzun matnni Telegram chegarasiga mos bo'laklarga ajratadi (qatorlar bo'yicha)."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    cur = ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            if cur:
                chunks.append(cur)
            # juda uzun bitta qator bo'lsa — majburan kesamiz
            while len(line) > limit:
                chunks.append(line[:limit])
                line = line[limit:]
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


# ─── Filtr: faqat guruhdagi nomzod xabarlar ──────────────────────────────────


async def _candidate(message: Message) -> bool:
    """Guruhdagi xabar AI tekshiruvga nomzodmi? (albom yoki #vazifa)."""
    if not AI_HOMEWORK_ENABLED:
        return False
    if message.chat.type not in ("group", "supergroup"):
        return False
    # Albom bo'laklarini har doim buferlash kerak (trigger boshqa bo'lakda bo'lishi mumkin)
    if message.media_group_id:
        return True
    return _has_trigger(message)


# ─── Albom buferi ─────────────────────────────────────────────────────────────


def _buffer_album(message: Message, bot: Bot, db: DatabaseService) -> None:
    mgid = message.media_group_id
    entry = _albums.get(mgid)
    if entry is None:
        entry = {"messages": [], "task": None}
        _albums[mgid] = entry
    entry["messages"].append(message)
    if entry["task"]:
        entry["task"].cancel()
    entry["task"] = asyncio.create_task(_flush_album(mgid, bot, db))


async def _flush_album(mgid: str, bot: Bot, db: DatabaseService) -> None:
    try:
        await asyncio.sleep(_ALBUM_DELAY)
    except asyncio.CancelledError:
        return  # yangi xabar keldi — keyinroq qayta rejalashtiriladi
    entry = _albums.pop(mgid, None)
    if not entry or not entry["messages"]:
        return
    msgs = entry["messages"]
    # Guruhni saqlaymiz (auto_save_group o'rniga, chunki propagation to'xtagan)
    try:
        await db.save_bot_chat(msgs[0].chat.id, msgs[0].chat.title or str(msgs[0].chat.id))
    except Exception:
        pass
    if not any(_has_trigger(m) for m in msgs):
        return  # albom vazifa emas — tegmaymiz
    trigger_msg = next((m for m in msgs if _has_trigger(m)), msgs[0])
    await _process(msgs, trigger_msg, bot, db)


# ─── Asosiy handler ───────────────────────────────────────────────────────────


@router.message(_candidate)
async def on_homework(message: Message, bot: Bot, db: DatabaseService) -> None:
    if message.media_group_id:
        _buffer_album(message, bot, db)
        return
    # Yakka xabar (rasm/fayl/matn + #vazifa)
    try:
        await db.save_bot_chat(message.chat.id, message.chat.title or str(message.chat.id))
    except Exception:
        pass
    if not _has_trigger(message):  # xavfsizlik
        return
    await _process([message], message, bot, db)


async def _process(
    messages: list[Message], trigger_msg: Message, bot: Bot, db: DatabaseService
) -> None:
    """Materialni yig'ib, AI tahlilini guruhga reply qiladi."""
    user = trigger_msg.from_user

    if not ai_service.is_configured():
        await trigger_msg.reply(
            "⚙️ AI tekshiruvi hali sozlanmagan (admin ANTHROPIC_API_KEY ni o'rnatishi kerak).\n"
            "⚙️ Проверка ИИ ещё не настроена."
        )
        logger.warning("AI homework: ANTHROPIC_API_KEY o'rnatilmagan.")
        return

    if not _check_limit(trigger_msg.chat.id, user.id):
        await trigger_msg.reply(
            f"⏳ Bugungi AI tekshiruv limiti tugadi ({AI_HOMEWORK_DAILY_LIMIT} ta). Ertaga qayta urinib ko'ring.\n"
            "⏳ Дневной лимит проверок исчерпан. Попробуйте завтра."
        )
        return

    # O'quvchi ismi/guruhi (DB'dan, bo'lmasa Telegram'dan)
    name = user.full_name
    group = trigger_msg.chat.title or ""
    try:
        student = await db.get_student(user.id)
        if student:
            if getattr(student, "full_name", None):
                name = student.full_name
            if getattr(student, "group_name", None):
                group = student.group_name
    except Exception:
        pass

    status = await trigger_msg.reply(
        "🔍 <b>Vazifangiz AI tomonidan tekshirilmoqda...</b>\n"
        "<i>🇷🇺 Идёт проверка работы искусственным интеллектом...</i>"
    )

    try:
        blocks, notes = await build_homework_payload(messages, bot, strip_triggers=_strip_triggers)
        if not blocks:
            await status.edit_text(
                "⚠️ Tekshirish uchun material topilmadi. Kod, rasm, ZIP yoki havola yuboring.\n"
                "⚠️ Не найден материал для проверки. Отправьте код, фото, ZIP или ссылку."
            )
            return
        feedback = await ai_service.analyze_homework(blocks, name, group, notes)
    except Exception:
        logger.exception("AI homework tahlil xatosi")
        await status.edit_text(
            "❌ AI tahlilda xatolik yuz berdi. Birozdan keyin qayta urinib ko'ring.\n"
            "❌ Произошла ошибка при анализе ИИ. Попробуйте позже."
        )
        return

    _incr_usage(trigger_msg.chat.id, user.id)

    # Sarlavha + tahlil. feedback toza matn → HTML xavfsizligi uchun escape qilamiz.
    header = f"📋 <b>{html.escape(name)}</b> — AI tahlil natijasi:\n\n"
    body = html.escape(feedback)
    parts = _chunk(header + body)

    try:
        await status.edit_text(parts[0])
        for extra in parts[1:]:
            await trigger_msg.reply(extra)
    except Exception:
        logger.exception("AI homework natijani yuborishda xato")
