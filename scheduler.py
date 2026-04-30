"""
scheduler.py — APScheduler servisi va xabar shablonlari.

Ota-onalar va o'quvchilar uchun ALOHIDA xabar matnlari.
Yuborilgan xabar ID lari bazaga saqlanadi (keyinchalik o'chirish uchun).
"""

import logging
import os
import random
import shutil
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytz
from aiogram import Bot
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


def _student_mentions(students: list) -> list[str]:
    usernames: list[str] = []
    for s in students:
        u = (getattr(s, "telegram_username", None) or "").strip().lstrip("@")
        if u:
            usernames.append(f"@{u}")
    return sorted(set(usernames))


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
        f"{('<b>Belgilanganlar:</b>\n' + mention_lines) if mentions else '⚠️ Username topilmadi'}"
    )
    try:
        await bot.send_message(chat_id=chat_id, text=group_text, parse_mode="HTML")
    except Exception:
        pass

    for s in students:
        try:
            await bot.send_message(
                chat_id=s.user_id,
                text=(
                    f"📝 <b>Uy vazifa eslatmasi</b>\n\n"
                    f"Guruh: <b>{group_name}</b>\n"
                    f"Uy vazifani bajarib, belgilashni unutmang."
                ),
                parse_mode="HTML",
            )
            dm_sent += 1
        except Exception:
            continue
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


# ─── Test: bitta guruhga dars eslatmasi ──────────────────────────────────────


async def send_daily_reminder_to_group(
    bot: Bot,
    db: DatabaseService,
    timezone_str: str,
    group_name: str,
) -> tuple[int, int] | None:
    """Admin mini app orqali bitta guruhga test yuborish.
    Returns (message_id, chat_id) on success, None on failure."""
    from sqlalchemy import select

    from database import Group

    try:
        info = get_tomorrow_info(timezone_str)

        # Guruhni nomiga qarab topamiz
        async with db.session_factory() as session:
            result = await session.execute(select(Group).where(Group.name == group_name))
            group = result.scalar_one_or_none()

        if not group:
            logger.warning(f"TEST SEND: Guruh topilmadi: '{group_name}'")
            return None

        text = build_reminder_message(info, group.audience)
        sent = await bot.send_message(
            chat_id=group.chat_id,
            text=f"🧪 <b>TEST</b>\n\n{text}",
            parse_mode="HTML",
        )
        # Xabar ID sini saqlaymiz (keyinchalik o'chirish uchun)
        await db.save_message_id(group.chat_id, sent.message_id)
        logger.info(f"TEST SEND: '{group_name}' ({group.chat_id}) → msg_id={sent.message_id}")

        # Uy vazifasi mavjud bo'lsa ham yuboramiz
        hw = await db.get_homework(group.name)
        if hw:
            try:
                await bot.copy_message(
                    chat_id=group.chat_id,
                    from_chat_id=hw.from_chat_id,
                    message_id=hw.message_id,
                )
                logger.info(f"TEST SEND: Uy vazifasi yuborildi → '{group_name}'")
                total_students, dm_sent = await _send_homework_group_and_dm_reminders(
                    bot, db, group.name, group.chat_id
                )
                logger.info(f"TEST SEND: Homework reminder → students={total_students}, dm={dm_sent}")
            except Exception as hw_err:
                logger.warning(f"TEST SEND: Uy vazifasi yuborib bo'lmadi: {hw_err}")

        return (sent.message_id, group.chat_id)

    except Exception as e:
        logger.exception(f"TEST SEND: Xato: {e}")
        return None


# ─── Dars eslatmasi: har 10 daqiqada ────────────────────────────────────────

# 1-eslatma va 2-eslatma yuborilgan foydalanuvchilarni kuzatish
# Key: "user_id:date_str" — restart bo'lsa reset bo'ladi (normal holat)
_sent_first_reminder: set[str] = set()
_sent_second_reminder: set[str] = set()
# 1-eslatma message_id lari — 2-eslatma yuborishda o'chirish uchun
_first_reminder_msg_ids: dict[str, int] = {}


async def check_class_reminders(bot: Bot, db: DatabaseService, timezone_str: str) -> None:
    """
    Har 10 daqiqada ishga tushadi (06:00–19:30 Tashkent oralig'ida).
    Har guruh uchun dars vaqtidan 3 soat oldin faqat 2 marta eslatma yuboradi:
      1-eslatma: reminder_start dan 10 daqiqa ichida
      2-eslatma: reminder_start + 30 daqiqadan keyin (10 daqiqa oyna)
    """
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

        # Qaysi eslatma oynasida ekanligini aniqlaymiz
        in_first_window = now < reminder_start + timedelta(minutes=10)
        in_second_window = reminder_start + timedelta(minutes=30) <= now < reminder_start + timedelta(minutes=40)

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

            if in_first_window:
                if key in _sent_first_reminder:
                    continue
                _sent_first_reminder.add(key)
                text = f"🎯 Bugun soat <b>{class_time_str}</b> da dars!\nTayyor bo'l, dasturchi! Kelasanmi? 💻"
                try:
                    sent = await bot.send_message(
                        student.user_id,
                        text,
                        reply_markup=kb_attendance(today_str),
                        parse_mode="HTML",
                    )
                    _first_reminder_msg_ids[key] = sent.message_id
                except Exception:
                    pass
            else:  # in_second_window
                if key in _sent_second_reminder:
                    continue
                _sent_second_reminder.add(key)
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
                except Exception:
                    pass

    logger.debug(f"check_class_reminders: {today_str} {now.strftime('%H:%M')} ({day_type})")


# ─── Kurator davomat eslatmasi: dars boshlanganidan 20 daqiqa o'tgach ────────

_sent_davomat_notify: set[str] = set()  # {group_name:date_str} — qayta yubormaslik

# Uy vazifasi eslatmasi: {group_name:date_str} — qayta yubormaslik
_sent_homework_prompt: set[str] = set()


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
        notify_key = f"{group_name}:{today_str}"
        if notify_key in _sent_davomat_notify:
            continue

        class_hour, class_min = map(int, class_time_str.split(":"))
        class_dt = now.replace(hour=class_hour, minute=class_min, second=0, microsecond=0)
        window_start = class_dt + timedelta(minutes=20)
        window_end = class_dt + timedelta(minutes=30)

        if not (window_start <= now < window_end):
            continue

        # Faol kurator sessiyalarini olamiz
        async with db.session_factory() as session:
            result = await session.execute(select(CuratorSession))
            curator_sessions = list(result.scalars().all())

        _sent_davomat_notify.add(notify_key)  # Belgilaymiz (kuratorlar bo'lmasa ham)

        if not curator_sessions:
            continue

        notify_text = (
            f"📋 <b>{group_name}</b> — dars boshlangan, 20 daq o'tdi!\n\n⏰ Davomatni ota-ona guruhiga yuboring."
        )
        for cs in curator_sessions:
            # Kurator uchun avto xabar o'chirilgan bo'lsa — o'tkazamiz
            if await db.get_setting(f"AUTO_MSG_CURATOR:{cs.telegram_id}", "1") == "0":
                continue
            try:
                await bot.send_message(
                    cs.telegram_id,
                    notify_text,
                    reply_markup=kb_davomat_start(group_name, today_str),
                )
            except Exception:
                pass

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

        key = f"{group_name}:{today_str}"
        if key in _sent_homework_prompt:
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
            _sent_homework_prompt.add(key)
            logger.info(f"Uy vazifasi eslatmasi yuborildi: {group_name} | {today_str} | {end_time_str}")
    _mark_job("homework_prompt_before_end", ok=True, details="checked")


async def send_homework_deadline_reminders(bot: Bot, db: DatabaseService, timezone_str: str) -> None:
    """
    Darsdan 4 soat oldin homework yo'q bo'lgan guruhlar uchun adminlarga deadline eslatmasi.
    """
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
                        (
                            "📝 <b>Uy vazifa nazorati</b>\n\n"
                            f"Guruh: <b>{group_name}</b>\n"
                            "Uyga vazifa qildingmi?"
                        ),
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


# ─── Kunlik reyting (Top-10) — rejalashtiruvchida alohida ishga tushirilmaydi;
#     avtomatik xabar: send_leaderboard_broadcast (haftalik).

_RANK_ICONS = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣"}


async def send_daily_leaderboard(
    bot: Bot,
    db: DatabaseService,
    timezone_str: str,
) -> None:
    """
    (Qo'lda/chaqiruv uchun) Top 10 o'quvchiga reyting xabari.
    Avtomatik reja: `send_leaderboard_broadcast` (haftasiga 1 marta) ishlatiladi.
    Barcha aktiv STUDENT guruhlarga yuboriladi (ota-ona guruhlari o'tkazib yuboriladi).
    """
    tz = pytz.timezone(timezone_str)
    date_str = datetime.now(tz).strftime("%d.%m.%Y")

    try:
        leaders = await db.get_global_leaderboard(limit=10)
    except Exception as e:
        logger.error(f"DAILY LEADERBOARD: leaderboard xatosi: {e}")
        return

    if not leaders:
        logger.info("DAILY LEADERBOARD: o'quvchilar yo'q — o'tkazib yuborildi")
        return

    # Top-10 satrlarini qurish
    rows = []
    for i, s in enumerate(leaders[:10], start=1):
        icon = _RANK_ICONS.get(i, f"{i}.")
        group = f" ({s.group_name})" if s.group_name else ""
        xp = s.xp or 0
        rows.append(f"{icon} <b>{s.full_name}</b>{group} — <b>{xp} XP</b>")

    top_line = "\n".join(rows)

    text = (
        f"🏆 <b>TOP 10 — Global reyting</b>\n"
        f"📅 {date_str}\n\n"
        f"{top_line}\n\n"
        f"🔥 Sen ham bu ro'yxatda bo'lishing mumkin!\n"
        f"💪 XP yig' va tepaga chiq! 🚀"
    )

    # Faqat aktiv O'QUVCHI guruhlariga yuboramiz (ota-ona guruhlar emas)
    groups = await db.get_all_groups()
    ok, fail = 0, 0
    for group in groups:
        if not group.is_active:
            continue
        if group.audience != AudienceType.STUDENT:
            logger.debug(f"DAILY LEADERBOARD: '{group.name}' — PARENT guruh, o'tkazib yuborildi")
            continue
        try:
            await bot.send_message(
                chat_id=group.chat_id,
                text=text,
                parse_mode="HTML",
            )
            ok += 1
        except Exception as e:
            fail += 1
            logger.warning(f"DAILY LEADERBOARD: '{group.name}' ({group.chat_id}): {e}")

    logger.info(f"DAILY LEADERBOARD: {ok} guruhga yuborildi, {fail} xato | {date_str}")


# ─── Haftalik global reyting broadcast ──────────────────────────────────────


async def send_leaderboard_broadcast(
    bot: Bot,
    db: DatabaseService,
    webapp_url: str,
    timezone_str: str,
) -> None:
    """
    Haftasiga 1 marta barcha aktiv o'quvchi guruhlariga global top-5 reyting yuboradi
    (reja: dushanba 21:05, TIMEZONE).
    Faqat AudienceType.STUDENT guruhlarga yuboriladi (PARENT guruhlar o'tkazib yuboriladi).
    Xabarda botga o'tish tugmasi bo'ladi.
    """
    tz = pytz.timezone(timezone_str)
    date_str = datetime.now(tz).strftime("%d.%m.%Y")

    try:
        leaders = await db.get_global_leaderboard(limit=10)
    except Exception as e:
        logger.error(f"LEADERBOARD BROADCAST: leaderboard xatosi: {e}")
        return

    if not leaders:
        logger.info("LEADERBOARD BROADCAST: o'quvchilar yo'q — o'tkazib yuborildi")
        return

    # Top-5 satrlarini qurish
    rows = []
    for i, s in enumerate(leaders[:5], start=1):
        icon = _RANK_ICONS.get(i, f"{i}.")
        group = f" ({s.group_name})" if s.group_name else ""
        xp = s.xp or 0
        rows.append(f"{icon} <b>{s.full_name}</b>{group} — <b>{xp} XP</b>")

    total = await db.get_students_count() if hasattr(db, "get_students_count") else len(leaders)
    top_line = "\n".join(rows)
    leader = leaders[0]
    leader_xp = leader.xp or 0
    runner_up_xp = leaders[1].xp if len(leaders) > 1 and leaders[1].xp is not None else 0
    gap_text = (
        f"⚔️ 1-o'rin uchun farq atigi <b>{leader_xp - runner_up_xp} XP</b>!"
        if len(leaders) > 1
        else f"⚔️ Taxtda faqat <b>{leader.full_name}</b> — sen qo'rqitolasan!"
    )
    challenge_lines = "⚡ XP formula:\n• Har kuni kir ✅\n• Davomat belgila 📋\n• Vazifani bajir 📝\n• O'yin o'yna 🎮"

    text = (
        f"🚀 <b>Haftalik reyting challenge</b> — {date_str}\n\n"
        f"{top_line}\n\n"
        f"👑 Lider: <b>{leader.full_name}</b> — <b>{leader_xp} XP</b>\n"
        f"{gap_text}\n"
        f"👥 {total} ta o'quvchi\n\n"
        f"{challenge_lines}\n\n"
        f"🏁 TOP ga chiq — botda o'rningni tekshir! 👇"
    )

    bot_info = await bot.get_me()
    bot_url = f"https://t.me/{bot_info.username}?start=leaderboard"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤖 Botga o'tish va o'rnimni ko'rish",
                    url=bot_url,
                )
            ],
        ]
    )

    # Faqat aktiv O'QUVCHI guruhlariga yuboramiz (ota-ona guruhlar emas)
    groups = await db.get_all_groups()
    ok, fail = 0, 0
    for group in groups:
        if not group.is_active:
            continue
        if group.audience != AudienceType.STUDENT:
            logger.debug(f"LEADERBOARD BROADCAST: '{group.name}' — PARENT guruh, o'tkazib yuborildi")
            continue
        try:
            await bot.send_message(
                chat_id=group.chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=kb,
            )
            ok += 1
        except Exception as e:
            fail += 1
            logger.warning(f"LEADERBOARD BROADCAST: '{group.name}' ({group.chat_id}): {e}")

    logger.info(f"LEADERBOARD BROADCAST: {ok} guruhga yuborildi, {fail} xato | {date_str}")


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


# ─── Haftalik 7-kun streak bonusi: Dushanba 09:00 ────────────────────────────


async def send_weekly_streak_bonus(bot: Bot, db: DatabaseService, webapp_url: str) -> None:
    """
    Har Dushanba 09:00 da: 7+ kun ketma-ket streak bo'lgan
    o'quvchilarga +100 XP bonus beradi.
    """
    from database import XP_WEEKLY_BONUS

    try:
        students = await db.get_students_with_7day_streak()
        awarded = 0
        for student in students:
            if not student.user_id:
                continue
            try:
                await db.add_xp(student.user_id, XP_WEEKLY_BONUS, "weekly_streak_bonus")
                updated = await db.get_student(student.user_id)
                await bot.send_message(
                    student.user_id,
                    f"🎉 <b>7 kun streak — BONUS!</b>\n\n"
                    f"Zo'rsan! 7 kun ketma-ket kirding! 🔥\n"
                    f"<b>+{XP_WEEKLY_BONUS} XP</b> oldin! 🚀\n\n"
                    f"⭐ Jami: <b>{updated.xp if updated else '?'} XP</b>",
                    parse_mode="HTML",
                )
                awarded += 1
            except Exception:
                pass
        logger.info(f"WEEKLY BONUS: {awarded} ta o'quvchiga +{XP_WEEKLY_BONUS} XP berildi")
    except Exception as e:
        logger.exception(f"WEEKLY BONUS: Xato: {e}")


# ─── Reschedule helper ───────────────────────────────────────────────────────


def reschedule_reminder(hour: int, minute: int) -> None:
    """Scheduler vaqtini dinamik o'zgartiradi (admin paneldan chaqiriladi)."""
    global _scheduler_ref
    if _scheduler_ref is None:
        logger.warning("reschedule_reminder: scheduler hali sozlanmagan!")
        return
    _scheduler_ref.reschedule_job(
        job_id="daily_lesson_reminder",
        trigger=CronTrigger(hour=hour, minute=minute),
    )
    logger.info(f"Scheduler qayta sozlandi: {hour:02d}:{minute:02d}")


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

    # Uy vazifasi qo'shish eslatmasi (har 1 daqiqada)
    scheduler.add_job(
        func=check_homework_prompt,
        trigger=IntervalTrigger(minutes=1, timezone=timezone_str),
        args=[bot, db, timezone_str, webapp_url],
        id="homework_prompt_before_end",
        name="Dars tugashidan 2 daqiqa oldin uy vazifasi eslatmasi",
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

    # Global reyting broadcast — haftasiga 1 marta (dushanba 21:05)
    scheduler.add_job(
        func=send_leaderboard_broadcast,
        trigger=CronTrigger(day_of_week="mon", hour=21, minute=5, timezone=timezone_str),
        args=[bot, db, webapp_url, timezone_str],
        id="weekly_leaderboard_broadcast",
        name="Haftalik global reyting (TOP-5)",
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

    # Homework deadline reminder (har 1 daqiqa)
    scheduler.add_job(
        func=send_homework_deadline_reminders,
        trigger=IntervalTrigger(minutes=1, timezone=timezone_str),
        args=[bot, db, timezone_str],
        id="homework_deadline_reminders",
        name="Homework deadline reminder",
        replace_existing=True,
        misfire_grace_time=60,
    )

    # Student homework nazorat flow (dars vaqtiga bog'liq)
    scheduler.add_job(
        func=send_student_homework_reminders,
        trigger=IntervalTrigger(minutes=1, timezone=timezone_str),
        args=[bot, db, timezone_str],
        id="student_homework_reminders",
        name="Student homework flow reminders",
        replace_existing=True,
        misfire_grace_time=60,
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

    # Haftalik streak bonusi (har Dushanba 09:00)
    scheduler.add_job(
        func=send_weekly_streak_bonus,
        trigger=CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=timezone_str),
        args=[bot, db, webapp_url],
        id="weekly_streak_bonus",
        name="Haftalik 7-kun streak bonusi",
        replace_existing=True,
        misfire_grace_time=600,
    )

    _scheduler_ref = scheduler
    logger.info(
        f"Scheduler sozlandi: "
        f"har kuni {SEND_HOUR:02d}:{SEND_MINUTE:02d} (dars eslatmasi) + "
        f"har 10 daqiqada dars/davomat eslatmasi + "
        f"har Dushanba 21:05 haftalik global reyting ({timezone_str})"
    )
    return scheduler
