"""
scheduler.py — APScheduler servisi va xabar shablonlari.

Ota-onalar va o'quvchilar uchun ALOHIDA xabar matnlari.
Yuborilgan xabar ID lari bazaga saqlanadi (keyinchalik o'chirish uchun).
"""

import asyncio
import html
import logging
import os
import random
import shutil
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytz
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from class_schedule import CLASS_END_SCHEDULE, CLASS_SCHEDULE, DEFAULT_LESSON_DURATION_MIN
from config import ADMIN_IDS, DATABASE_URL, SEND_HOUR, SEND_MINUTE
from database import AudienceType, DatabaseService, GroupType

# Scheduler global ref (reschedule uchun)
_scheduler_ref: "AsyncIOScheduler | None" = None

logger = logging.getLogger(__name__)
_job_runtime: dict[str, dict[str, str | bool | int]] = {}


def _mark_job(job_id: str, *, ok: bool, details: str = "") -> None:
    _job_runtime[job_id] = {
        "ok": ok,
        "details": details[:240],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def scheduler_health() -> dict[str, bool | str]:
    """Rejalashtiruvchi holati (admin / ready uchun)."""
    if _scheduler_ref is None:
        return {"configured": False, "running": False, "state": "not_configured"}
    try:
        running = bool(_scheduler_ref.running)
    except Exception:
        running = False
    return {
        "configured": True,
        "running": running,
        "state": "running" if running else "stopped",
        "jobs": _job_runtime,
    }


_WEEKDAYS_UZ = {
    0: "Dushanba",
    1: "Seshanba",
    2: "Chorshanba",
    3: "Payshanba",
    4: "Juma",
    5: "Shanba",
    6: "Yakshanba",
}


# ─── Ertangi kun ma'lumoti ────────────────────────────────────────────────────


@dataclass
class TomorrowInfo:
    date: datetime
    date_str: str
    weekday_uz: str
    day_number: int
    group_type: GroupType
    type_label: str


def get_tomorrow_info(timezone_str: str) -> TomorrowInfo:
    tz = pytz.timezone(timezone_str)
    tomorrow = datetime.now(tz) + timedelta(days=1)
    day = tomorrow.day
    # Weekday bo'yicha: 0,2,4 = Du,Ch,J = ODD; 1,3,5 = Se,Pa,Sh = EVEN
    # Yakshanba (6) — dars yo'q, is_odd=False (EVEN) qaytariladi,
    # lekin send_daily_reminders() Yakshanba uchun yubormasligi kerak.
    is_odd = tomorrow.weekday() in (0, 2, 4)
    return TomorrowInfo(
        date=tomorrow,
        date_str=tomorrow.strftime("%d.%m.%Y"),
        weekday_uz=_WEEKDAYS_UZ[tomorrow.weekday()],
        day_number=day,
        group_type=GroupType.ODD if is_odd else GroupType.EVEN,
        type_label="Toq" if is_odd else "Juft",
    )


# ─── Xabar shablonlari ────────────────────────────────────────────────────────

_MOTIVATSION_GAPLAR = [
    "Kod yozish — superqahramon bo'lish demak! 🦸",
    "Bugun yangi skill olib, levelingni oshir! 🎮",
    "Sen hali bitta bug'ni ham yengoching yo'q? Keling! 🐛💥",
    "Mars IT dagi eng zo'r dasturchi kim? Sen! 🚀",
    "Ctrl+S qilib qo'y — ertaga sening kuni! 💾⚡",
    "Kelajak senatorlari hozir kod yozyapti! 🌟",
    "O'yin o'ynab XP yig' — o'qib PRO bo'l! 🏆",
    "ERROR topding? Demak GROW qilding! 📈",
    "Bugun darsda nima o'rganasan? Surpriz! 🎁",
    "Dasturlash = cheksiz kreativlik! 🎨💻",
    "Hello World dan Hello Future gacha! 🌍✨",
    "Brain.exe yuklanmoqda... 99% tayyorsan! 🧠",
]

_WEEKDAY_EXTRA: dict[int, str] = {
    0: "Yangi hafta = yangi mission! Let's go! 🎯🔥",
    4: "Juma — hafta finali! Power mode ON! 🏆⚡",
    5: "Shanba darsi — 2x qiziqarli va foydali! 🎉🚀",
}


def build_reminder_message(info: TomorrowInfo, audience: AudienceType) -> str:
    """
    Auditoriyaga qarab turli xabar matnini qaytaradi:
      PARENT  — ota-onalarga yo'naltirilgan
      STUDENT — o'quvchilarga yo'naltirilgan
    """
    motiv = random.choice(_MOTIVATSION_GAPLAR)
    extra = _WEEKDAY_EXTRA.get(info.date.weekday(), "")
    extra_line = f"\n{extra}" if extra else ""

    if audience == AudienceType.PARENT:
        return (
            f"👨‍👩‍👧 <b>Assalomu alaykum!</b>\n\n"
            f"📅 Ertaga — <b>{info.weekday_uz}, {info.date_str}</b>{extra_line}\n\n"
            f"✅ Farzandingiz darsga tayyor ekanini tekshiring\n"
            f"📚 Uy vazifasi bajarilganmi?\n\n"
            f"💡 {motiv}"
        )
    else:  # STUDENT
        return (
            f"🚀 <b>Hey, dasturchi!</b>\n\n"
            f"📅 Ertaga — <b>{info.weekday_uz}, {info.date_str}</b>{extra_line}\n\n"
            f"📝 Vazifa qildingmi? Hozir qil!\n"
            f"⏰ Kechikma — dars kutmaydi!\n\n"
            f"🎮 {motiv}"
        )


_NO_MENTIONS_WARN = "⚠️ Belgilanadigan a'zolar topilmadi"


def _student_mentions(students: list) -> list[str]:
    """Guruh xabarida o'quvchilarni belgilash uchun mention ro'yxatini qaytaradi.

    Telegram username bo'lsa — `@username` ishlatiladi.
    Aks holda — HTML inline mention `<a href="tg://user?id=ID">Ism</a>` (parse_mode=HTML kerak).
    Bu format username'siz a'zolarni ham guruhda push-notification bilan ping qiladi.
    """
    out: list[str] = []
    seen: set[str] = set()
    for s in students:
        u = (getattr(s, "telegram_username", None) or "").strip().lstrip("@")
        if u:
            mention = f"@{u}"
        else:
            uid = getattr(s, "user_id", None)
            name = (getattr(s, "full_name", None) or "").strip() or "O'quvchi"
            if not uid:
                continue
            mention = f'<a href="tg://user?id={uid}">{html.escape(name)}</a>'
        if mention not in seen:
            seen.add(mention)
            out.append(mention)
    return out


async def _send_homework_group_and_dm_reminders(
    bot: Bot,
    db: DatabaseService,
    group_name: str,
    chat_id: int,
) -> tuple[int, int]:
    """Homework eslatmasini guruhga (mentions) va har bir o'quvchiga yuboradi."""
    students = await db.get_students_by_group(group_name)
    mentions = _student_mentions(students)
    max_mentions = 10
    shown_mentions = mentions[:max_mentions]
    remaining = max(0, len(mentions) - len(shown_mentions))
    mention_lines = "".join([f"{i + 1}) {u}\n" for i, u in enumerate(shown_mentions)])
    if remaining:
        mention_lines += f"... va yana {remaining} ta\n"
    dm_sent = 0

    group_text = (
        f"🔔 <b>Uy vazifa eslatmasi</b>\n\n"
        f"🏫 Guruh: <b>{group_name}</b>\n"
        f"👥 O'quvchilar soni: <b>{len(students)}</b>\n\n"
        f"{('<b>Belgilanganlar:</b>' + chr(10) + mention_lines) if mentions else _NO_MENTIONS_WARN}"
    )
    try:
        await bot.send_message(chat_id=chat_id, text=group_text, parse_mode="HTML")
    except Exception:
        pass

    for s in students:
        ok = await _safe_send_dm(
            bot,
            s.user_id,
            text=(
                f"📝 <b>Uy vazifa eslatmasi</b>\n\n"
                f"Guruh: <b>{group_name}</b>\n"
                f"Uy vazifani bajarib, belgilashni unutmang."
            ),
            parse_mode="HTML",
        )
        if ok:
            dm_sent += 1
    return (len(students), dm_sent)


def _admin_mini_hw_url(webapp_url: str, group_name: str) -> str:
    base = (webapp_url or "").strip()
    if not base:
        return ""
    if "admin-mini.html" in base:
        root = base
    else:
        root = base.rstrip("/") + "/admin-mini.html"
    sep = "&" if "?" in root else "?"
    return f"{root}{sep}hw_group={urllib.parse.quote(group_name)}"


# ─── Master toggle helper ────────────────────────────────────────────────────


async def is_auto_messages_disabled(db: DatabaseService) -> bool:
    """Master toggle: barcha avtohabarlarni o'chirish."""
    return (await db.get_setting("AUTO_MSG_MASTER", "1")) == "0"


# ─── Asosiy yuborish vazifasi ─────────────────────────────────────────────────


async def send_daily_reminders(
    bot: Bot,
    db: DatabaseService,
    timezone_str: str,
) -> None:
    """
    Har kuni 20:00 da ishga tushadi.
    - Ota-onalarga alohida xabar
    - O'quvchilarga alohida xabar
    - Yuborilgan message_id lar bazaga saqlanadi
    """
    if await is_auto_messages_disabled(db):
        logger.info("SCHEDULER: AUTO_MSG_MASTER o'chirilgan — barcha avtohabarlar to'xtatildi")
        return
    # Avto xabar o'chirilgan bo'lsa — to'xtatamiz
    if await db.get_setting("AUTO_MSG_GROUPS", "1") == "0":
        logger.info("SCHEDULER: AUTO_MSG_GROUPS o'chirilgan — guruh xabarlari yuborilmadi")
        return

    logger.info("=" * 55)
    logger.info("SCHEDULER: send_daily_reminders boshlandi")
    logger.info("=" * 55)

    try:
        info = get_tomorrow_info(timezone_str)

        # Ertangi kun Yakshanba bo'lsa — dars yo'q, yubormaymiz
        if info.date.weekday() == 6:
            logger.info(f"SCHEDULER: Ertangi kun Yakshanba ({info.date_str}) — dars yo'q, xabar yuborilmadi")
            return

        groups = await db.get_groups_by_type(info.group_type)

        # Toq/juft kun o'chirilgan bo'lsa — to'xtatamiz
        day_setting_key = "AUTO_MSG_ODD" if info.group_type == GroupType.ODD else "AUTO_MSG_EVEN"
        if await db.get_setting(day_setting_key, "1") == "0":
            logger.info(f"SCHEDULER: {day_setting_key} o'chirilgan — {info.type_label} kun xabarlari yuborilmadi")
            return

        logger.info(f"Ertangi kun: {info.date_str} ({info.type_label}) | Guruhlar soni: {len(groups)}")

        if not groups:
            logger.warning(f"Aktiv guruhlar topilmadi ({info.type_label} kun)")
            return

        ok, fail = 0, 0

        for group in groups:
            # Guruh uchun avto xabar o'chirilgan bo'lsa — o'tkazamiz
            if await db.get_setting(f"AUTO_MSG_GROUP:{group.name}", "1") == "0":
                logger.info(f"  ⏭ '{group.name}' guruhi avto xabari o'chirilgan")
                continue

            # Auditoriyaga mos xabarni tanlaymiz
            text = build_reminder_message(info, group.audience)
            audience_label = "Ota-ona" if group.audience == AudienceType.PARENT else "O'quvchi"

            try:
                sent = await bot.send_message(
                    chat_id=group.chat_id,
                    text=text,
                    parse_mode="HTML",
                )
                # Xabar ID sini saqlaymiz (keyinchalik o'chirish uchun)
                await db.save_message_id(group.chat_id, sent.message_id)
                ok += 1
                logger.info(f"  ✅ [{audience_label}] '{group.name}' ({group.chat_id}) → msg_id={sent.message_id}")

                # Uy vazifasi mavjud bo'lsa — alohida yuboramiz
                hw = await db.get_homework(group.name)
                if hw:
                    try:
                        await bot.copy_message(
                            chat_id=group.chat_id,
                            from_chat_id=hw.from_chat_id,
                            message_id=hw.message_id,
                        )
                        logger.info(f"  📝 Uy vazifasi yuborildi → '{group.name}'")
                        total_students, dm_sent = await _send_homework_group_and_dm_reminders(
                            bot, db, group.name, group.chat_id
                        )
                        logger.info(
                            "  🔔 Homework reminder yuborildi → '%s' | students=%s, dm=%s",
                            group.name,
                            total_students,
                            dm_sent,
                        )
                    except Exception as hw_err:
                        logger.warning(f"  Uy vazifasi yuborib bo'lmadi ({group.name}): {hw_err}")

            except Exception as e:
                fail += 1
                logger.error(f"  ❌ [{audience_label}] '{group.name}' ({group.chat_id}): {e}")

        logger.info(f"NATIJA: {ok} yuborildi, {fail} xato | {info.date_str} | {info.type_label} kun")
        # Shaxsiy davomat so'rovlari check_class_reminders() orqali yuboriladi

    except Exception as e:
        logger.exception(f"KRITIK XATO: {e}")

    logger.info("=" * 55)


# ─── Avto-xabar dedup (restartga chidamli) ──────────────────────────────────
#
# Eslatmalar takror yuborilmasligi uchun "yuborildi" holatini DB'da (BotSetting)
# saqlaymiz. Shu sababli process qayta ishga tushganda ham takroriy xabar
# yuborilmaydi. _dedup_cache — DB'ga ortiqcha so'rovni kamaytiruvchi tezkor kesh.
_dedup_cache: set[str] = set()


async def _dedup_seen(db: DatabaseService, key: str) -> bool:
    """Ushbu kalit bo'yicha amal allaqachon bajarilganmi (DB orqali tekshiriladi)."""
    if key in _dedup_cache:
        return True
    if await db.get_setting(f"sched_dedup:{key}", "") == "1":
        _dedup_cache.add(key)
        return True
    return False


async def _dedup_mark(db: DatabaseService, key: str) -> None:
    """Kalitni "bajarildi" deb belgilaydi (DB + kesh)."""
    _dedup_cache.add(key)
    await db.set_setting(f"sched_dedup:{key}", "1")


# Telegram ~30 msg/sek limiti — ko'p-DM yuboradiga sikllar uchun kichik pauza.
_DM_THROTTLE_SEC = 0.05


async def _safe_send_dm(bot: Bot, chat_id: int, **kwargs) -> bool:
    """Bitta DM yuboradi: flood throttle + TelegramRetryAfter (429) handling.

    Muvaffaqiyatda True, aks holda False qaytaradi. 429 bo'lsa e.retry_after
    soniya kutib BIR marta qayta urinadi. Boshqa xatolar log qilinib yutiladi
    ('except: pass' ostida jim ko'mma).
    """
    try:
        await bot.send_message(chat_id, **kwargs)
        await asyncio.sleep(_DM_THROTTLE_SEC)
        return True
    except TelegramRetryAfter as e:
        logger.warning("DM flood limit (429): chat=%s retry_after=%ss", chat_id, e.retry_after)
        await asyncio.sleep(e.retry_after + 1)
        try:
            await bot.send_message(chat_id, **kwargs)
            await asyncio.sleep(_DM_THROTTLE_SEC)
            return True
        except Exception as e2:
            logger.warning("DM qayta urinish ham xato: chat=%s err=%s", chat_id, e2)
            return False
    except Exception as e:
        logger.debug("DM yuborilmadi: chat=%s err=%s", chat_id, e)
        return False


# ─── Dars eslatmasi: har 10 daqiqada ────────────────────────────────────────

# 1-eslatma message_id lari — 2-eslatma yuborishda o'chirish uchun (ephemeral, dedup emas)
_first_reminder_msg_ids: dict[str, int] = {}


async def check_class_reminders(bot: Bot, db: DatabaseService, timezone_str: str) -> None:
    """
    Har 10 daqiqada ishga tushadi (06:00–19:30 Tashkent oralig'ida).
    Har guruh uchun dars vaqtidan 3 soat oldin faqat 2 marta eslatma yuboradi:
      1-eslatma: reminder_start dan 10 daqiqa ichida
      2-eslatma: reminder_start + 30 daqiqadan keyin (10 daqiqa oyna)
    """
    if await is_auto_messages_disabled(db):
        return
    # Avto xabar o'chirilgan bo'lsa — to'xtatamiz
    if await db.get_setting("AUTO_MSG_STUDENTS", "1") == "0":
        return

    from keyboards import kb_attendance

    tz = pytz.timezone(timezone_str)
    now = datetime.now(tz)

    # Faqat 06:00–19:30 oralig'ida ishlaydi
    if not (6 * 60 <= now.hour * 60 + now.minute <= 19 * 60 + 30):
        return

    weekday = now.weekday()
    if weekday == 6:  # Yakshanba — dars yo'q
        return

    day_type = "ODD" if weekday in (0, 2, 4) else "EVEN"

    # Toq/juft kun o'chirilgan bo'lsa — to'xtatamiz
    day_setting_key = "AUTO_MSG_ODD" if day_type == "ODD" else "AUTO_MSG_EVEN"
    if await db.get_setting(day_setting_key, "1") == "0":
        return

    schedule = CLASS_SCHEDULE.get(day_type, {})
    today_str = now.strftime("%Y-%m-%d")

    for group_name, class_time_str in schedule.items():
        # Guruh uchun avto xabar o'chirilgan bo'lsa — o'tkazamiz
        if await db.get_setting(f"AUTO_MSG_GROUP:{group_name}", "1") == "0":
            continue
        class_hour, class_min = map(int, class_time_str.split(":"))
        class_dt = now.replace(hour=class_hour, minute=class_min, second=0, microsecond=0)
        reminder_start = class_dt - timedelta(hours=3)

        # Umumiy oynadan tashqarida — o'tkazib yuboramiz
        if now < reminder_start or now >= class_dt:
            continue

        # "Quvlash" mantig'i: oynani aniq 10 daq kenglik bilan emas, balki dars
        # boshlanishigacha (class_dt) kengaytiramiz. Dedup (r1/r2) takror yuborishni
        # to'xtatgani uchun bu xavfsiz — har eslatma kuniga bir marta ketadi va
        # kechikkan/o'tkazib yuborilgan run'larda ham kafolatlanadi.
        #   1-eslatma: reminder_start <= now < class_dt (r1 dedup yo'q bo'lsa)
        #   2-eslatma: reminder_start+30daq <= now < class_dt (r2 dedup yo'q bo'lsa)
        in_first_window = reminder_start <= now < class_dt
        in_second_window = reminder_start + timedelta(minutes=30) <= now < class_dt

        # Hech bir oynada emasmiz — o'tkazib yuboramiz
        if not in_first_window and not in_second_window:
            continue

        # Guruh o'quvchilarini olamiz
        students = await db.get_students_by_group(group_name)
        if not students:
            continue

        for student in students:
            # Allaqon javob bergan bo'lsa — yubormaymiz
            rec = await db.get_student_attendance(student.user_id, today_str)
            if rec:
                continue

            key = f"{student.user_id}:{today_str}"

            r1_done = await _dedup_seen(db, f"r1:{key}")

            # 1-eslatma hali ketmagan bo'lsa — birinchi navbatda uni yuboramiz
            # (oyna class_dt gacha kengaytirilgan, kechikkan run'larda ham kafolat).
            if not r1_done and in_first_window:
                text = f"🎯 Bugun soat <b>{class_time_str}</b> da dars!\nTayyor bo'l, dasturchi! Kelasanmi? 💻"
                try:
                    sent = await bot.send_message(
                        student.user_id,
                        text,
                        reply_markup=kb_attendance(today_str),
                        parse_mode="HTML",
                    )
                    # MUHIM: mark faqat muvaffaqiyatli yuborishdan KEYIN (homework_prompt pattern)
                    await _dedup_mark(db, f"r1:{key}")
                    _first_reminder_msg_ids[key] = sent.message_id
                    await asyncio.sleep(_DM_THROTTLE_SEC)
                except TelegramRetryAfter as e:
                    logger.warning(
                        "check_class_reminders r1 flood (429): chat=%s retry_after=%ss",
                        student.user_id,
                        e.retry_after,
                    )
                    await asyncio.sleep(e.retry_after + 1)
                except Exception:
                    pass
                continue

            # 2-eslatma: r1 ketgan AND r2 hali yo'q AND 2-oynada (class_dt gacha)
            if r1_done and in_second_window and not await _dedup_seen(db, f"r2:{key}"):
                # Birinchi eslatmani o'chiramiz
                if key in _first_reminder_msg_ids:
                    try:
                        await bot.delete_message(student.user_id, _first_reminder_msg_ids.pop(key))
                    except Exception:
                        _first_reminder_msg_ids.pop(key, None)
                text = f"⚡ Hoy! Hali javob bermading!\nDars <b>{class_time_str}</b> da — qo'ldan boy berma! 🏃"
                try:
                    await bot.send_message(
                        student.user_id,
                        text,
                        reply_markup=kb_attendance(today_str),
                        parse_mode="HTML",
                    )
                    # MUHIM: mark faqat muvaffaqiyatli yuborishdan KEYIN
                    await _dedup_mark(db, f"r2:{key}")
                    await asyncio.sleep(_DM_THROTTLE_SEC)
                except TelegramRetryAfter as e:
                    logger.warning(
                        "check_class_reminders r2 flood (429): chat=%s retry_after=%ss",
                        student.user_id,
                        e.retry_after,
                    )
                    await asyncio.sleep(e.retry_after + 1)
                except Exception:
                    pass

    logger.debug(f"check_class_reminders: {today_str} {now.strftime('%H:%M')} ({day_type})")


# ─── Kurator davomat eslatmasi: dars boshlanganidan 20 daqiqa o'tgach ────────
#
# Quyidagi takror-yuborish holatlari endi DB orqali kuzatiladi (_dedup_seen/_dedup_mark):
#   davomat eslatmasi  → "davomat:{group_name}:{date_str}"
#   uy vazifasi prompt → "hwprompt:{group_name}:{date_str}"
#   uy vazifasi expire → "hwexpire:{group_name}:{date_str}"


def _group_end_time(day_type: str, group_name: str, class_time_str: str) -> str:
    """
    Guruhning dars tugash vaqtini qaytaradi.
    - Avval CLASS_END_SCHEDULE dan olinadi
    - Yo'q bo'lsa DEFAULT_LESSON_DURATION_MIN bo'yicha hisoblanadi
    """
    explicit = CLASS_END_SCHEDULE.get(day_type, {}).get(group_name)
    if explicit:
        return explicit
    class_hour, class_min = map(int, class_time_str.split(":"))
    start = datetime(2000, 1, 1, class_hour, class_min)
    end = start + timedelta(minutes=DEFAULT_LESSON_DURATION_MIN)
    return end.strftime("%H:%M")


async def check_davomat_notify(bot: Bot, db: DatabaseService, timezone_str: str) -> None:
    """
    Har 10 daqiqada tekshiradi: dars boshlanganidan 20-30 daqiqa o'tgan
    guruhlar uchun kuratorlarga davomat yuborish eslatmasi ketadi.
    """
    if await is_auto_messages_disabled(db):
        return
    # Avto xabar o'chirilgan bo'lsa — to'xtatamiz
    if await db.get_setting("AUTO_MSG_CURATORS", "1") == "0":
        return

    from sqlalchemy import select

    from database import CuratorSession
    from keyboards import kb_davomat_start

    tz = pytz.timezone(timezone_str)
    now = datetime.now(tz)

    if not (6 * 60 <= now.hour * 60 + now.minute <= 21 * 60):
        return

    weekday = now.weekday()
    if weekday == 6:  # Yakshanba — dars yo'q
        return

    day_type = "ODD" if weekday in (0, 2, 4) else "EVEN"

    # Toq/juft kun o'chirilgan bo'lsa — to'xtatamiz
    day_setting_key = "AUTO_MSG_ODD" if day_type == "ODD" else "AUTO_MSG_EVEN"
    if await db.get_setting(day_setting_key, "1") == "0":
        return

    schedule = CLASS_SCHEDULE.get(day_type, {})
    today_str = now.strftime("%Y-%m-%d")

    for group_name, class_time_str in schedule.items():
        notify_key = f"davomat:{group_name}:{today_str}"
        if await _dedup_seen(db, notify_key):
            continue

        class_hour, class_min = map(int, class_time_str.split(":"))
        class_dt = now.replace(hour=class_hour, minute=class_min, second=0, microsecond=0)
        # Oynani kengaytiramiz (20 daq dan dars tugashigacha taxminan +3 soat) —
        # dedup (notify_key) takror yuborishni to'xtatgani uchun bu xavfsiz va
        # kechikkan run'larda ham eslatma kafolatlanadi.
        window_start = class_dt + timedelta(minutes=20)
        window_end = class_dt + timedelta(hours=3)

        if not (window_start <= now < window_end):
            continue

        # Faol kurator sessiyalarini olamiz
        async with db.session_factory() as session:
            result = await session.execute(select(CuratorSession))
            curator_sessions = list(result.scalars().all())

        # SCH-003: kurator ulanmagan bo'lsa MARK QILMAYMIZ — keyingi run qayta urinsin
        # (aks holda kurator keyin ulansa ham eslatma olmaydi).
        if not curator_sessions:
            continue

        notify_text = (
            f"📋 <b>{group_name}</b> — dars boshlangan, 20 daq o'tdi!\n\n⏰ Davomatni ota-ona guruhiga yuboring."
        )
        sent_any = False
        for cs in curator_sessions:
            # Kurator uchun avto xabar o'chirilgan bo'lsa — o'tkazamiz
            if await db.get_setting(f"AUTO_MSG_CURATOR:{cs.telegram_id}", "1") == "0":
                continue
            if await _safe_send_dm(
                bot,
                cs.telegram_id,
                text=notify_text,
                reply_markup=kb_davomat_start(group_name, today_str),
            ):
                sent_any = True

        # Mark faqat kamida bitta yuborish urinishi bo'lganda
        if sent_any:
            await _dedup_mark(db, notify_key)
            logger.info(f"Davomat eslatmasi: {group_name} | {today_str}")


async def check_homework_prompt(
    bot: Bot,
    db: DatabaseService,
    timezone_str: str,
    webapp_url: str = "",
) -> None:
    """
    Har daqiqada tekshiradi:
    dars tugashiga 2 daqiqa qolgan guruh bo'lsa, adminga
    "Uyga vazifa bering" eslatmasini yuboradi.
    """
    if await is_auto_messages_disabled(db):
        return
    if await db.get_setting("AUTO_MSG_GROUPS", "1") == "0":
        return

    tz = pytz.timezone(timezone_str)
    now = datetime.now(tz)
    if now.weekday() == 6:  # Yakshanba
        return

    day_type = "ODD" if now.weekday() in (0, 2, 4) else "EVEN"
    day_setting_key = "AUTO_MSG_ODD" if day_type == "ODD" else "AUTO_MSG_EVEN"
    if await db.get_setting(day_setting_key, "1") == "0":
        return

    schedule = CLASS_SCHEDULE.get(day_type, {})
    today_str = now.strftime("%Y-%m-%d")

    for group_name, class_time_str in schedule.items():
        if await db.get_setting(f"AUTO_MSG_GROUP:{group_name}", "1") == "0":
            continue

        end_time_str = _group_end_time(day_type, group_name, class_time_str)
        end_hour, end_min = map(int, end_time_str.split(":"))
        end_dt = now.replace(hour=end_hour, minute=end_min, second=0, microsecond=0)
        prompt_dt = end_dt - timedelta(minutes=2)

        key = f"hwprompt:{group_name}:{today_str}"
        if await _dedup_seen(db, key):
            continue
        # 1 daqiqalik oynada bir marta yuboramiz
        if not (prompt_dt <= now < prompt_dt + timedelta(minutes=1)):
            continue

        text = (
            f"📝 <b>Uyga vazifa eslatmasi</b>\n\n"
            f"Guruh: <b>{group_name}</b>\n"
            f"Dars tugashi: <b>{end_time_str}</b>\n\n"
            f"⏰ Dars tugashiga 2 daqiqa qoldi.\n"
            f"Uyga vazifa bering va uyga vazifa qo'shing.\n\n"
            f"Eslatma: qo'shilgan vazifa ertangi dars eslatmasiga avtomatik qo'shiladi."
        )
        quick_url = _admin_mini_hw_url(webapp_url, group_name)
        kb = None
        if quick_url:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📝 Vazifani hozir qo'shish", web_app=WebAppInfo(url=quick_url))],
                ]
            )

        sent_any = False
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=kb)
                sent_any = True
            except Exception:
                continue

        if sent_any:
            await _dedup_mark(db, key)
            logger.info(f"Uy vazifasi eslatmasi yuborildi: {group_name} | {today_str} | {end_time_str}")
    _mark_job("homework_prompt_before_end", ok=True, details="checked")


async def send_lesson_topic_prompt(
    bot: Bot,
    db: DatabaseService,
    timezone_str: str,
) -> None:
    """
    Dars tugagach (tugash vaqtidan +1 daqiqa) adminga "Dars vazifasini yarat" tugmasini yuboradi.
    Tugma bosilsa handlers/lesson_topic.py oqimi ishga tushadi (modul → blok → dars → AI vazifa).
    """
    if await is_auto_messages_disabled(db):
        return
    if await db.get_setting("AUTO_MSG_GROUPS", "1") == "0":
        return
    # Bu avtohabarni alohida o'chirib qo'yish mumkin
    if await db.get_setting("AUTO_MSG_LESSON_TASK", "1") == "0":
        return

    tz = pytz.timezone(timezone_str)
    now = datetime.now(tz)
    if now.weekday() == 6:  # Yakshanba
        return

    day_type = "ODD" if now.weekday() in (0, 2, 4) else "EVEN"
    day_setting_key = "AUTO_MSG_ODD" if day_type == "ODD" else "AUTO_MSG_EVEN"
    if await db.get_setting(day_setting_key, "1") == "0":
        return

    schedule = CLASS_SCHEDULE.get(day_type, {})
    today_str = now.strftime("%Y-%m-%d")
    sent = 0

    for group_name, class_time_str in schedule.items():
        if await db.get_setting(f"AUTO_MSG_GROUP:{group_name}", "1") == "0":
            continue

        end_time_str = _group_end_time(day_type, group_name, class_time_str)
        end_hour, end_min = map(int, end_time_str.split(":"))
        end_dt = now.replace(hour=end_hour, minute=end_min, second=0, microsecond=0)
        prompt_dt = end_dt + timedelta(minutes=1)

        key = f"lessontask:{group_name}:{today_str}"
        if await _dedup_seen(db, key):
            continue
        # 2 daqiqalik oyna (scheduler 1 daqiqada ishlaydi)
        if not (prompt_dt <= now < prompt_dt + timedelta(minutes=2)):
            continue

        text = (
            f"📝 <b>Dars vazifasini yarataylik!</b>\n\n"
            f"🏫 Guruh: <b>{group_name}</b>\n"
            f"🕒 Dars tugadi: <b>{end_time_str}</b>\n\n"
            f"Bugun qaysi modul, qaysi blok mavzusini o'tdingiz?\n"
            f"Tanlang — AI o'sha mavzudan 10-16 yosh uchun vazifa tuzib beradi."
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📝 Vazifa yaratish", callback_data=f"lt:start:{group_name}")]]
        )
        sent_any = False
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=kb)
                sent_any = True
                sent += 1
            except Exception:
                continue
        if sent_any:
            await _dedup_mark(db, key)
            logger.info(f"Dars vazifa prompti yuborildi: {group_name} | {today_str}")

    _mark_job("lesson_topic_prompt", ok=True, details=f"sent={sent}")


async def send_topic_day_prompt(
    bot: Bot,
    db: DatabaseService,
    timezone_str: str,
) -> None:
    """
    Seshanba/Payshanba/Shanba 16:30 da adminga "Bugun qaysi mavzuni o'tdingiz?"
    xabarini yuboradi. Tugma bosilsa handlers/topic_day.py oqimi ishga tushadi:
    mavzu → kanal videosi → guruh tanlash → guruhga uyga vazifa.
    """
    if await is_auto_messages_disabled(db):
        return
    if await db.get_setting("AUTO_MSG_TOPIC_DAY", "1") == "0":
        return

    tz = pytz.timezone(timezone_str)
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    key = f"topicday:{today_str}"
    if await _dedup_seen(db, key):
        return

    text = (
        "📚 <b>Bugun qaysi mavzuni o'tdingiz?</b>\n\n"
        "Mavzuni tanlang — keyin kanaldagi video darsni va guruhni tanlaysiz, "
        "bot guruhga uyga vazifa xabarini yuboradi."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📖 Mavzu tanlash", callback_data="td:start")]]
    )
    sent = 0
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=kb)
            sent += 1
        except Exception:
            continue
    if sent:
        await _dedup_mark(db, key)
        logger.info(f"Bugungi mavzu prompti yuborildi: {sent} ta admin | {today_str}")
    _mark_job("topic_day_prompt", ok=True, details=f"sent={sent}")


async def expire_homeworks_at_class_start(
    bot: Bot,
    db: DatabaseService,
    timezone_str: str,
    webapp_url: str = "",
) -> None:
    """
    Yangi dars boshlangan momentda eski uy vazifasini o'chiradi va adminga
    "yangi vazifa qo'shing" eslatmasini yuboradi.

    Uy vazifasi `sent_at` < bugungi dars boshlanish vaqti bo'lsa — eski deb belgilanadi.
    Shu darsda admin yangi vazifa qo'shgan bo'lsa, u o'chirilmaydi.
    """
    if await is_auto_messages_disabled(db):
        return
    if await db.get_setting("AUTO_MSG_GROUPS", "1") == "0":
        return

    tz = pytz.timezone(timezone_str)
    now = datetime.now(tz)
    if now.weekday() == 6:
        return

    day_type = "ODD" if now.weekday() in (0, 2, 4) else "EVEN"
    schedule = CLASS_SCHEDULE.get(day_type, {})
    today_str = now.strftime("%Y-%m-%d")

    expired_total = 0
    for group_name, class_time_str in schedule.items():
        key = f"hwexpire:{group_name}:{today_str}"
        if await _dedup_seen(db, key):
            continue

        class_hour, class_min = map(int, class_time_str.split(":"))
        class_dt = now.replace(hour=class_hour, minute=class_min, second=0, microsecond=0)

        # Faqat dars boshlanganda 2 daqiqalik oynada ishlaymiz
        if not (class_dt <= now < class_dt + timedelta(minutes=2)):
            continue

        # sent_at — naive datetime (database.py da datetime.now() ishlatilgan),
        # shuning uchun cutoff ni ham naive qilamiz.
        cutoff = class_dt.replace(tzinfo=None)
        expired = await db.expire_homework_if_old(group_name, cutoff)
        await _dedup_mark(db, key)

        if not expired:
            continue
        expired_total += 1
        logger.info(f"Eski uy vazifasi o'chirildi: {group_name} | {today_str}")

        # Adminlarga eslatma — yangi vazifa qo'shing
        text = (
            f"🔄 <b>Yangi uyga vazifa qo'shing</b>\n\n"
            f"Guruh: <b>{group_name}</b>\n"
            f"Dars vaqti: <b>{class_time_str}</b>\n\n"
            f"✅ Eski uy vazifa avtomatik o'chirildi.\n"
            f"📝 Endi yangi uyga vazifa qo'shing — keyingi darsgacha amal qiladi."
        )
        quick_url = _admin_mini_hw_url(webapp_url, group_name)
        kb = None
        if quick_url:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📝 Yangi vazifa qo'shish", web_app=WebAppInfo(url=quick_url))],
                ]
            )
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=kb)
            except Exception:
                continue

    _mark_job("homework_expire_at_class_start", ok=True, details=f"expired={expired_total}")


async def send_homework_deadline_reminders(bot: Bot, db: DatabaseService, timezone_str: str) -> None:
    """
    Darsdan 4 soat oldin homework yo'q bo'lgan guruhlar uchun adminlarga deadline eslatmasi.
    """
    if await is_auto_messages_disabled(db):
        return
    tz = pytz.timezone(timezone_str)
    now = datetime.now(tz)
    if now.weekday() == 6:
        return
    day_type = "ODD" if now.weekday() in (0, 2, 4) else "EVEN"
    schedule = CLASS_SCHEDULE.get(day_type, {})
    today_str = now.strftime("%Y-%m-%d")
    sent = 0
    for group_name, class_time_str in schedule.items():
        class_hour, class_min = map(int, class_time_str.split(":"))
        class_dt = now.replace(hour=class_hour, minute=class_min, second=0, microsecond=0)
        deadline_dt = class_dt - timedelta(hours=4)
        key = f"hw_deadline:{group_name}:{today_str}"
        if await db.get_setting(key, "0") == "1":
            continue
        if not (deadline_dt <= now < deadline_dt + timedelta(minutes=1)):
            continue
        hw = await db.get_homework(group_name)
        if hw:
            await db.set_setting(key, "1")
            continue
        txt = (
            f"⏰ <b>Homework deadline</b>\n\n"
            f"Guruh: <b>{group_name}</b>\n"
            f"Dars: <b>{class_time_str}</b>\n\n"
            f"Uyga vazifa hali qo'shilmagan. Iltimos, hozir qo'shing."
        )
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, txt, parse_mode="HTML")
                sent += 1
            except Exception:
                pass
        await db.set_setting(key, "1")
    _mark_job("homework_deadline_reminders", ok=True, details=f"sent={sent}")


async def send_student_homework_reminders(bot: Bot, db: DatabaseService, timezone_str: str) -> None:
    """
    Dars kuni/vaqtiga qarab o'quvchilarga uy vazifa nazorat oqimi:
    1) Dars tugagandan 3 soat o'tib: "Uy vazifa qildingmi?"
    2) Agar javob bo'lmasa, ertasi kuni 20:00 da yana bir marta so'raladi.
    3) O'quvchi "Ha" bosib, 2 soat ichida "Vazifani yubordim" demasa: eslatma
    4) Eslatmadan keyin 30 daqiqa ichida ham yubormasa: qilmadi deb ota-ona/ustozga xabar
    """
    if await is_auto_messages_disabled(db):
        return
    from keyboards import kb_homework_check

    tz = pytz.timezone(timezone_str)
    now = datetime.now(tz)
    if now.weekday() == 6:
        return

    day_type = "ODD" if now.weekday() in (0, 2, 4) else "EVEN"
    day_setting_key = "AUTO_MSG_ODD" if day_type == "ODD" else "AUTO_MSG_EVEN"
    if await db.get_setting(day_setting_key, "1") == "0":
        return

    schedule = CLASS_SCHEDULE.get(day_type, {})
    today_str = now.strftime("%Y-%m-%d")
    yday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    # Kechagi kun turi (ODD/EVEN) alohida hisoblanadi — retry uchun to'g'ri jadval kerak
    yday_type = "ODD" if (now - timedelta(days=1)).weekday() in (0, 2, 4) else "EVEN"
    yday_schedule = CLASS_SCHEDULE.get(yday_type, {})
    all_groups = await db.get_all_groups()
    student_groups = {g.name: g for g in all_groups if g.is_active and g.audience == AudienceType.STUDENT}
    parent_groups = {g.name: g for g in all_groups if g.is_active and g.audience == AudienceType.PARENT}
    sent_ask = sent_retry = sent_late = sent_fail = 0

    for group_name, class_time_str in schedule.items():
        sg = student_groups.get(group_name)
        if not sg:
            continue

        if await db.get_setting(f"AUTO_MSG_GROUP:{group_name}", "1") == "0":
            continue

        hw = await db.get_homework(group_name)
        if not hw:
            continue

        end_time_str = _group_end_time(day_type, group_name, class_time_str)
        end_h, end_m = map(int, end_time_str.split(":"))
        end_dt = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
        ask_dt = end_dt + timedelta(hours=3)
        # 5 daqiqalik oyna — 1 daqiqalik oyna scheduler kechikishida miss bo'lardi
        ask_window = ask_dt <= now < ask_dt + timedelta(minutes=5)

        students = await db.get_students_by_group(group_name)
        for st in students:
            ask_key = f"hwflow:ask:{today_str}:{st.user_id}"
            yes_key = f"hwflow:yes:{today_str}:{st.user_id}"
            no_key = f"hwflow:no:{today_str}:{st.user_id}"
            submitted_key = f"hwflow:submitted:{today_str}:{st.user_id}"
            reminded_key = f"hwflow:reminded:{today_str}:{st.user_id}"
            fail_key = f"hwflow:failed:{today_str}:{st.user_id}"

            # 1) Bir martalik boshlang'ich so'rov
            if ask_window and await db.get_setting(ask_key, "0") != "1":
                try:
                    await bot.send_message(
                        st.user_id,
                        (f"📝 <b>Uy vazifa nazorati</b>\n\nGuruh: <b>{group_name}</b>\nUyga vazifa qildingmi?"),
                        parse_mode="HTML",
                        reply_markup=kb_homework_check(today_str),
                    )
                    await db.set_setting(ask_key, "1")
                    sent_ask += 1
                except Exception:
                    pass
                continue

            yes_ts_raw = await db.get_setting(yes_key, "")
            if not yes_ts_raw:
                continue
            if await db.get_setting(no_key, "0") == "1":
                continue
            if await db.get_setting(submitted_key, "0") == "1":
                continue
            if await db.get_setting(fail_key, "0") == "1":
                continue

            try:
                yes_dt = datetime.fromisoformat(yes_ts_raw)
            except ValueError:
                continue
            if yes_dt.tzinfo is None:
                yes_dt = tz.localize(yes_dt)

            # 2) "Ha" bosganidan 2 soat o'tib eslatma
            if now >= yes_dt + timedelta(hours=2) and await db.get_setting(reminded_key, "0") != "1":
                try:
                    await bot.send_message(
                        st.user_id,
                        (
                            "⏰ Siz hali menga uyga vazifani yubormadingiz.\n"
                            "Iltimos, vazifani shu botga yuboring va 'Vazifani yubordim' tugmasini bosing."
                        ),
                    )
                    await db.set_setting(reminded_key, "1")
                    sent_late += 1
                except Exception:
                    pass

            # 3) Eslatmadan 30 daqiqa o'tib ham yubormasa — qilmadi deb xabar
            if await db.get_setting(reminded_key, "0") == "1" and now >= yes_dt + timedelta(hours=2, minutes=30):
                warn_text = (
                    f"⚠️ <b>{st.full_name}</b> uy vazifani yubormadi.\n"
                    f"Guruh: <b>{group_name}</b>\n"
                    f"Sana: <b>{today_str}</b>\n\n"
                    "Status: <b>Uy vazifa qilmadi</b>"
                )
                try:
                    await bot.send_message(
                        st.user_id,
                        (
                            "❌ Siz uyga vazifani vaqtida yubormadingiz.\n"
                            "Bot sizni 'uyga vazifa qilmadi' deb belgilab, ota-onangiz va ustozingizga yubordi."
                        ),
                    )
                except Exception:
                    pass

                for admin_id in ADMIN_IDS:
                    try:
                        await bot.send_message(admin_id, warn_text, parse_mode="HTML")
                    except Exception:
                        pass

                pg = parent_groups.get(group_name)
                if pg:
                    try:
                        await bot.send_message(pg.chat_id, warn_text, parse_mode="HTML")
                    except Exception:
                        pass

                await db.set_setting(fail_key, "1")
                sent_fail += 1

    # Kecha javob bermagan o'quvchilarga bugun 20:00 da qayta so'rov.
    # MUHIM: kechagi kun turi (yday_schedule) ishlatiladi — bugungi emas.
    if now.hour == 20 and now.minute < 10:
        for group_name_y in yday_schedule:
            if await db.get_setting(f"AUTO_MSG_GROUP:{group_name_y}", "1") == "0":
                continue
            students_y = await db.get_students_by_group(group_name_y)
            for st in students_y:
                y_ask_key = f"hwflow:ask:{yday_str}:{st.user_id}"
                y_yes_key = f"hwflow:yes:{yday_str}:{st.user_id}"
                y_no_key = f"hwflow:no:{yday_str}:{st.user_id}"
                y_retry_key = f"hwflow:retry_ask:{yday_str}:{st.user_id}"
                if (
                    await db.get_setting(y_ask_key, "0") == "1"
                    and not await db.get_setting(y_yes_key, "")
                    and await db.get_setting(y_no_key, "0") != "1"
                    and await db.get_setting(y_retry_key, "0") != "1"
                ):
                    try:
                        await bot.send_message(
                            st.user_id,
                            (
                                "⏰ <b>Uy vazifa bo'yicha qayta so'rov</b>\n\n"
                                "Kecha yuborilgan savolga javob bermagansiz.\n"
                                "Uyga vazifa qildingmi?"
                            ),
                            parse_mode="HTML",
                            reply_markup=kb_homework_check(yday_str),
                        )
                        await db.set_setting(y_retry_key, "1")
                        sent_retry += 1
                    except Exception:
                        pass

    _mark_job(
        "student_homework_reminders",
        ok=True,
        details=f"ask={sent_ask}, retry={sent_retry}, late={sent_late}, failed={sent_fail}",
    )


async def send_lesson_auto_summary(bot: Bot, db: DatabaseService, timezone_str: str) -> None:
    """
    Dars tugagandan keyin (5 daqiqalik window) adminlarga qisqa summary.
    """
    if await is_auto_messages_disabled(db):
        return
    tz = pytz.timezone(timezone_str)
    now = datetime.now(tz)
    if now.weekday() == 6:
        return
    day_type = "ODD" if now.weekday() in (0, 2, 4) else "EVEN"
    schedule = CLASS_SCHEDULE.get(day_type, {})
    today_str = now.strftime("%Y-%m-%d")
    for group_name, class_time_str in schedule.items():
        end_str = _group_end_time(day_type, group_name, class_time_str)
        h, m = map(int, end_str.split(":"))
        end_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if not (end_dt + timedelta(minutes=5) <= now < end_dt + timedelta(minutes=10)):
            continue
        key = f"lesson_summary:{group_name}:{today_str}"
        if await db.get_setting(key, "0") == "1":
            continue
        students = await db.get_students_by_group(group_name)
        if not students:
            await db.set_setting(key, "1")
            continue
        present = absent = pending = 0
        hw = await db.get_homework(group_name)
        for st in students:
            rec = await db.get_student_attendance(st.user_id, today_str)
            if not rec:
                pending += 1
            elif rec.status == "yes":
                present += 1
            else:
                absent += 1
        txt = (
            f"📊 <b>Dars yakuni summary</b>\n\n"
            f"Guruh: <b>{group_name}</b>\n"
            f"✅ Keldi: <b>{present}</b>\n"
            f"❌ Kelmadi: <b>{absent}</b>\n"
            f"⏳ Kutilmoqda: <b>{pending}</b>\n"
            f"📝 Uy vazifa: <b>{'Bor' if hw else 'Yoʻq'}</b>"
        )
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, txt, parse_mode="HTML")
            except Exception:
                pass
        await db.set_setting(key, "1")
    _mark_job("lesson_auto_summary", ok=True, details="checked")


def _sqlite_path_from_url(url: str) -> str | None:
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        return None
    raw = url[len(prefix) :]
    if not raw:
        return None
    return raw.lstrip("/")


async def run_sqlite_backup_job(bot: Bot, db: DatabaseService, timezone_str: str) -> None:
    """
    Har kuni lokal SQLite backup (backups/).
    """
    src_rel = _sqlite_path_from_url(DATABASE_URL)
    if not src_rel:
        _mark_job("sqlite_backup_daily", ok=False, details="non-sqlite")
        return
    src = os.path.abspath(src_rel)
    if not os.path.isfile(src):
        _mark_job("sqlite_backup_daily", ok=False, details="db_missing")
        return
    out_dir = os.path.abspath("backups")
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(out_dir, f"bot_{stamp}.db")
    try:
        shutil.copy2(src, dst)
        _mark_job("sqlite_backup_daily", ok=True, details=f"saved:{os.path.basename(dst)}")
    except Exception as e:
        _mark_job("sqlite_backup_daily", ok=False, details=f"err:{e}")


# ─── 7 kun nofaol o'quvchilarni o'chirish ────────────────────────────────────


async def check_inactive_students(bot: Bot, db: DatabaseService, timezone_str: str = "Asia/Tashkent") -> None:
    """
    Har kuni 21:00 da ishga tushadi.
    Ro'yxatdan o'tganiga 7 kundan oshgan va 7 kun davomida faol bo'lmagan
    o'quvchilarni o'chirib, ularga ogohlantirish xabari yuboradi.
    """
    # Toshkent vaqti bo'yicha cutoff — UTC da ishlayotgan serverlarda xato bo'lmasligi uchun
    tz = pytz.timezone(timezone_str)
    cutoff = datetime.now(tz).replace(tzinfo=None) - timedelta(days=7)
    students = await db.get_inactive_students(days=7)

    deleted = 0
    for student in students:
        # Ro'yxatdan o'tganiga 7 kundan kam bo'lsa — o'tkazib yuboramiz
        if student.registered_at and student.registered_at > cutoff:
            continue
        try:
            await bot.send_message(
                student.user_id,
                "⚠️ <b>Akkaunt o'chirildi!</b>\n\n"
                "7 kun kirmagansan 😔\n\n"
                "Qaytmoqchimisan? 👇\n"
                "/start — qayta ro'yxatdan o't!",
                parse_mode="HTML",
            )
        except Exception:
            pass
        await db.delete_student(student.user_id)
        deleted += 1

    if deleted:
        logger.info(f"check_inactive_students: {deleted} ta o'quvchi o'chirildi")


# ─── Streak reminder: 19:00 da kirmagan o'quvchilarga ────────────────────────


async def send_streak_reminders(bot: Bot, db: DatabaseService, timezone_str: str) -> None:
    """
    Har kuni 19:00 da: bugun hali Mini App ga kirmagan o'quvchilarga
    streak yo'qolishi haqida ogohlantirish yuboradi.
    """
    if await is_auto_messages_disabled(db):
        return
    tz = pytz.timezone(timezone_str)
    today_str = datetime.now(tz).strftime("%Y-%m-%d")

    try:
        students = await db.get_students_without_checkin_today(today_str)
        sent_count = 0
        for student in students:
            if not student.user_id:
                continue
            streak = student.streak_days or 0
            if streak < 1:
                continue  # Streak yo'q — eslatish shart emas
            try:
                await bot.send_message(
                    student.user_id,
                    f"🔥 <b>Streak yonmoqda — o'chirma!</b>\n\n"
                    f"Senda <b>{streak} kunlik streak</b> bor! 💪\n"
                    f"Bugun kirmading — hozir kir, yo'qotma! ⏳\n\n"
                    f"🎮 Kir → XP ol → Streak saqla!",
                    parse_mode="HTML",
                )
                sent_count += 1
            except Exception:
                pass
        logger.info(f"STREAK REMINDER: {sent_count} ta o'quvchiga yuborildi | {today_str}")
    except Exception as e:
        logger.exception(f"STREAK REMINDER: Xato: {e}")


# ─── Reschedule helper ───────────────────────────────────────────────────────


# Admin tomonidan vaqtini boshqarish mumkin bo'lgan cron-jadvalli ishlar.
# Settings keys: SCHED:{job_id}:HOUR, SCHED:{job_id}:MINUTE, SCHED:{job_id}:DOW
SCHEDULED_JOBS_REGISTRY: dict[str, dict[str, object]] = {
    "daily_lesson_reminder": {
        "name": "Kunlik dars eslatmasi (ota-ona/o'quvchi guruhlar)",
        "default_hour": SEND_HOUR,
        "default_minute": SEND_MINUTE,
        "default_dow": "",  # bo'sh = har kuni
    },
    "streak_reminder": {
        "name": "Streak eslatmasi (kirmaganlarga)",
        "default_hour": 19,
        "default_minute": 0,
        "default_dow": "",
    },
    "inactive_students_cleanup": {
        "name": "Nofaol o'quvchilarni o'chirish",
        "default_hour": 21,
        "default_minute": 0,
        "default_dow": "",
    },
    "sqlite_backup_daily": {
        "name": "SQLite kunlik backup",
        "default_hour": 23,
        "default_minute": 50,
        "default_dow": "",
    },
    "topic_day_prompt": {
        "name": "Bugungi mavzu prompti (Se/Pa/Sh 16:30)",
        "default_hour": 16,
        "default_minute": 30,
        "default_dow": "tue,thu,sat",
    },
}

_VALID_DOWS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


# Barcha 13 avtohabar — to'liq metadata. Admin panel uchun.
# `editable=True` bo'lsa, vaqtni o'zgartirish mumkin (faqat cron jobs).
# `toggle_key` mavjud bo'lsa, alohida o'chirib qo'yish mumkin.
ALL_AUTO_JOBS_META: dict[str, dict[str, object]] = {
    "daily_lesson_reminder": {
        "name": "Kunlik dars eslatmasi",
        "what": "Ota-ona va o'quvchi guruhlariga kunlik dars eslatma xabari",
        "schedule_human": f"Har kuni {SEND_HOUR:02d}:{SEND_MINUTE:02d}",
        "frequency_per_day": "1 marta (kuniga)",
        "trigger_type": "cron",
        "editable": True,
        "toggle_key": "AUTO_MSG_GROUPS",
        "audience": "guruhlar",
    },
    "class_attendance_reminder": {
        "name": "Dars davomat eslatmasi",
        "what": "Dars vaqti yaqinlashganda o'quvchilarga davomat tugmasi DM",
        "schedule_human": "Har 10 daqiqada (06:00–19:30)",
        "frequency_per_day": "~80 marta (kuniga)",
        "trigger_type": "interval",
        "editable": False,
        "toggle_key": "AUTO_MSG_STUDENTS",
        "audience": "o'quvchilar",
    },
    "davomat_curator_notify": {
        "name": "Kurator davomat eslatmasi",
        "what": "Dars boshlanganidan 20–30 daqiqa o'tgach kuratorga DM",
        "schedule_human": "Har 10 daqiqada",
        "frequency_per_day": "~144 marta (kuniga)",
        "trigger_type": "interval",
        "editable": False,
        "toggle_key": "AUTO_MSG_CURATORS",
        "audience": "kuratorlar",
    },
    "homework_prompt_before_end": {
        "name": "Uy vazifa eslatmasi (admin)",
        "what": "Dars tugashidan 2 daqiqa oldin adminga 'Uy vazifa bering' DM",
        "schedule_human": "Har 1 daqiqada",
        "frequency_per_day": "~1440 marta (kuniga)",
        "trigger_type": "interval",
        "editable": False,
        "toggle_key": "AUTO_MSG_GROUPS",
        "audience": "adminlar",
    },
    "lesson_topic_prompt": {
        "name": "Dars vazifasi prompti (admin)",
        "what": "Dars tugagach adminga 'Dars vazifasini yarat' tugmasi — AI mavzudan vazifa tuzadi",
        "schedule_human": "Har 1 daqiqada (dars tugashi +1 daq)",
        "frequency_per_day": "~1440 marta (kuniga)",
        "trigger_type": "interval",
        "editable": False,
        "toggle_key": "AUTO_MSG_LESSON_TASK",
        "audience": "adminlar",
    },
    "homework_expire_at_class_start": {
        "name": "Eski uy vazifani o'chirish",
        "what": "Yangi dars boshlanganda eski uy vazifani arxivga ko'chiradi",
        "schedule_human": "Har 1 daqiqada",
        "frequency_per_day": "~1440 marta (kuniga)",
        "trigger_type": "interval",
        "editable": False,
        "toggle_key": "AUTO_MSG_GROUPS",
        "audience": "tizim",
    },
    "inactive_students_cleanup": {
        "name": "Nofaol o'quvchilarni o'chirish",
        "what": "7+ kun faol bo'lmagan o'quvchilarni avtomatik o'chirish",
        "schedule_human": "Har kuni 21:00",
        "frequency_per_day": "1 marta (kuniga)",
        "trigger_type": "cron",
        "editable": True,
        "toggle_key": None,
        "audience": "tizim",
    },
    "streak_reminder": {
        "name": "Streak eslatmasi",
        "what": "Bugun Mini Appga kirmagan o'quvchilarga streak yo'qolish ogohlantirishi",
        "schedule_human": "Har kuni 19:00",
        "frequency_per_day": "1 marta (kuniga)",
        "trigger_type": "cron",
        "editable": True,
        "toggle_key": None,
        "audience": "o'quvchilar",
    },
    "homework_deadline_reminders": {
        "name": "Uy vazifa deadline eslatmasi",
        "what": "Darsdan 4 soat oldin uy vazifa yo'q bo'lsa adminga DM",
        "schedule_human": "Har 1 daqiqada",
        "frequency_per_day": "~1440 marta (kuniga)",
        "trigger_type": "interval",
        "editable": False,
        "toggle_key": None,
        "audience": "adminlar",
    },
    "student_homework_reminders": {
        "name": "Student uy vazifa nazorat oqimi",
        "what": "O'quvchilarga 'Uy vazifa qildingmi?' va eslatma flow",
        "schedule_human": "Har 1 daqiqada",
        "frequency_per_day": "~1440 marta (kuniga)",
        "trigger_type": "interval",
        "editable": False,
        "toggle_key": None,
        "audience": "o'quvchilar",
    },
    "lesson_auto_summary": {
        "name": "Dars summary (admin)",
        "what": "Dars tugagach adminlarga qisqa statistika",
        "schedule_human": "Har 5 daqiqada",
        "frequency_per_day": "~288 marta (kuniga)",
        "trigger_type": "interval",
        "editable": False,
        "toggle_key": None,
        "audience": "adminlar",
    },
    "sqlite_backup_daily": {
        "name": "SQLite kunlik backup",
        "what": "DB faylni avtomatik backup qilish",
        "schedule_human": "Har kuni 23:50",
        "frequency_per_day": "1 marta (kuniga)",
        "trigger_type": "cron",
        "editable": True,
        "toggle_key": None,
        "audience": "tizim",
    },
    "topic_day_prompt": {
        "name": "Bugungi mavzu prompti (admin)",
        "what": "Adminga 'Bugun qaysi mavzuni o'tdingiz?' — mavzu, kanal videosi va guruh tanlanadi",
        "schedule_human": "Se/Pa/Sh 16:30",
        "frequency_per_day": "Haftada 3 marta",
        "trigger_type": "cron",
        "editable": True,
        "toggle_key": "AUTO_MSG_TOPIC_DAY",
        "audience": "adminlar",
    },
}


async def get_job_schedule(db: DatabaseService, job_id: str) -> tuple[int, int, str]:
    """Berilgan job uchun (hour, minute, dow) qaytaradi (DB sozlamasini, yo'q bo'lsa default)."""
    cfg = SCHEDULED_JOBS_REGISTRY.get(job_id)
    if not cfg:
        raise KeyError(f"Unknown job_id: {job_id}")
    h = int(await db.get_setting(f"SCHED:{job_id}:HOUR", str(cfg["default_hour"])))
    m = int(await db.get_setting(f"SCHED:{job_id}:MINUTE", str(cfg["default_minute"])))
    dow = await db.get_setting(f"SCHED:{job_id}:DOW", str(cfg.get("default_dow", "")))
    return h, m, (dow or "")


def reschedule_job_by_id(job_id: str, hour: int, minute: int, dow: str = "") -> bool:
    """Cron-jadvalli scheduled jobni dinamik qayta sozlaydi."""
    global _scheduler_ref
    if _scheduler_ref is None:
        logger.warning("reschedule_job_by_id: scheduler hali sozlanmagan!")
        return False
    if dow:
        trigger = CronTrigger(day_of_week=dow, hour=hour, minute=minute)
    else:
        trigger = CronTrigger(hour=hour, minute=minute)
    try:
        _scheduler_ref.reschedule_job(job_id=job_id, trigger=trigger)
        logger.info(f"Scheduler qayta sozlandi: {job_id} → {dow + ' ' if dow else ''}{hour:02d}:{minute:02d}")
        return True
    except Exception as e:
        logger.warning(f"reschedule_job_by_id({job_id}) xato: {e}")
        return False


async def apply_db_schedule_overrides(db: DatabaseService) -> None:
    """Setup-dan keyin DB-dagi user-set vaqtlarni barcha registryda registratsiyadan o'tkaziladi."""
    for job_id in SCHEDULED_JOBS_REGISTRY:
        try:
            h, m, dow = await get_job_schedule(db, job_id)
            cfg = SCHEDULED_JOBS_REGISTRY[job_id]
            # Default qiymatlardan farq bo'lsa qayta sozlaymiz
            if (
                h != cfg["default_hour"]
                or m != cfg["default_minute"]
                or (dow or "") != (cfg.get("default_dow", "") or "")
            ):
                reschedule_job_by_id(job_id, h, m, dow)
        except Exception as e:
            logger.warning(f"apply_db_schedule_overrides({job_id}) xato: {e}")


def reschedule_reminder(hour: int, minute: int) -> None:
    """Eski API: kunlik dars eslatmasi vaqtini o'zgartiradi (legacy chaqiruvlar uchun)."""
    reschedule_job_by_id("daily_lesson_reminder", hour, minute, "")


# ─── Minutlik ishlar dispatcheri ─────────────────────────────────────────────


async def run_minute_jobs(
    bot: Bot,
    db: DatabaseService,
    timezone_str: str,
    webapp_url: str = "",
) -> None:
    """
    Har 1 daqiqada ishlaydigan barcha ishlar — bitta jobda.
    Alohida 5 ta interval job o'rniga bitta trigger: DB va scheduler yuki kamayadi.
    Har bir ish alohida try/except da — biri yiqilsa qolganlari ishlayveradi.
    """
    for func, args in (
        (check_homework_prompt, (bot, db, timezone_str, webapp_url)),
        (send_lesson_topic_prompt, (bot, db, timezone_str)),
        (expire_homeworks_at_class_start, (bot, db, timezone_str, webapp_url)),
        (send_homework_deadline_reminders, (bot, db, timezone_str)),
        (send_student_homework_reminders, (bot, db, timezone_str)),
    ):
        try:
            await func(*args)
        except Exception as e:
            logger.exception(f"minute_jobs: {func.__name__} xato: {e}")


# ─── Scheduler setup ─────────────────────────────────────────────────────────


def setup_scheduler(
    bot: Bot,
    db: DatabaseService,
    timezone_str: str,
    webapp_url: str = "",
) -> AsyncIOScheduler:
    global _scheduler_ref
    scheduler = AsyncIOScheduler(timezone=timezone_str)

    # Kunlik eslatma (20:00)
    scheduler.add_job(
        func=send_daily_reminders,
        trigger=CronTrigger(hour=SEND_HOUR, minute=SEND_MINUTE, timezone=timezone_str),
        args=[bot, db, timezone_str],
        id="daily_lesson_reminder",
        name="Kunlik dars eslatmasi",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Dars vaqti eslatmasi (har 10 daqiqada)
    scheduler.add_job(
        func=check_class_reminders,
        trigger=IntervalTrigger(minutes=10, timezone=timezone_str),
        args=[bot, db, timezone_str],
        id="class_attendance_reminder",
        name="Dars vaqti davomat eslatmasi",
        replace_existing=True,
        misfire_grace_time=60,
    )

    # Kurator davomat eslatmasi (har 10 daqiqada)
    scheduler.add_job(
        func=check_davomat_notify,
        trigger=IntervalTrigger(minutes=10, timezone=timezone_str),
        args=[bot, db, timezone_str],
        id="davomat_curator_notify",
        name="Kurator davomat eslatmasi",
        replace_existing=True,
        misfire_grace_time=60,
    )

    # Minutlik ishlar — 5 ta ish bitta jobda (har 1 daqiqada)
    scheduler.add_job(
        func=run_minute_jobs,
        trigger=IntervalTrigger(minutes=1, timezone=timezone_str),
        args=[bot, db, timezone_str, webapp_url],
        id="minute_jobs",
        name="Minutlik ishlar dispatcheri",
        replace_existing=True,
        misfire_grace_time=60,
    )

    # 7 kun nofaol o'quvchilarni o'chirish (har kuni 21:00)
    scheduler.add_job(
        func=check_inactive_students,
        trigger=CronTrigger(hour=21, minute=0, timezone=timezone_str),
        args=[bot, db, timezone_str],
        id="inactive_students_cleanup",
        name="Nofaol o'quvchilarni tozalash",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Streak eslatmasi (har kuni 19:00)
    scheduler.add_job(
        func=send_streak_reminders,
        trigger=CronTrigger(hour=19, minute=0, timezone=timezone_str),
        args=[bot, db, timezone_str],
        id="streak_reminder",
        name="Streak eslatmasi (19:00)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Lesson summary to admins
    scheduler.add_job(
        func=send_lesson_auto_summary,
        trigger=IntervalTrigger(minutes=5, timezone=timezone_str),
        args=[bot, db, timezone_str],
        id="lesson_auto_summary",
        name="Lesson auto summary",
        replace_existing=True,
        misfire_grace_time=60,
    )

    # Daily backup
    scheduler.add_job(
        func=run_sqlite_backup_job,
        trigger=CronTrigger(hour=23, minute=50, timezone=timezone_str),
        args=[bot, db, timezone_str],
        id="sqlite_backup_daily",
        name="SQLite backup daily",
        replace_existing=True,
        misfire_grace_time=1200,
    )

    # Bugungi mavzu prompti (Seshanba/Payshanba/Shanba 16:30)
    scheduler.add_job(
        func=send_topic_day_prompt,
        trigger=CronTrigger(day_of_week="tue,thu,sat", hour=16, minute=30, timezone=timezone_str),
        args=[bot, db, timezone_str],
        id="topic_day_prompt",
        name="Bugungi mavzu prompti (Se/Pa/Sh 16:30)",
        replace_existing=True,
        misfire_grace_time=600,
    )

    _scheduler_ref = scheduler
    logger.info(
        f"Scheduler sozlandi: "
        f"har kuni {SEND_HOUR:02d}:{SEND_MINUTE:02d} (dars eslatmasi) + "
        f"har 10 daqiqada dars/davomat eslatmasi ({timezone_str})"
    )
    return scheduler
