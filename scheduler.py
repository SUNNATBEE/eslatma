"""
scheduler.py — APScheduler servisi va xabar shablonlari.

Ota-onalar va o'quvchilar uchun ALOHIDA xabar matnlari.
Yuborilgan xabar ID lari bazaga saqlanadi (keyinchalik o'chirish uchun).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytz
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from class_schedule import CLASS_SCHEDULE
from config import SEND_HOUR, SEND_MINUTE, TIMEZONE
from database import AudienceType, DatabaseService, GroupType

# Scheduler global ref (reschedule uchun)
_scheduler_ref: "AsyncIOScheduler | None" = None

logger = logging.getLogger(__name__)

_WEEKDAYS_UZ = {
    0: "Dushanba", 1: "Seshanba", 2: "Chorshanba",
    3: "Payshanba", 4: "Juma", 5: "Shanba", 6: "Yakshanba",
}


# ─── Ertangi kun ma'lumoti ────────────────────────────────────────────────────

@dataclass
class TomorrowInfo:
    date:       datetime
    date_str:   str
    weekday_uz: str
    day_number: int
    group_type: GroupType
    type_label: str


def get_tomorrow_info(timezone_str: str) -> TomorrowInfo:
    tz       = pytz.timezone(timezone_str)
    tomorrow = datetime.now(tz) + timedelta(days=1)
    day      = tomorrow.day
    # Weekday bo'yicha: 0,2,4 = Du,Ch,J = ODD; 1,3,5 = Se,Pa,Sh = EVEN
    is_odd   = tomorrow.weekday() in (0, 2, 4)
    return TomorrowInfo(
        date       = tomorrow,
        date_str   = tomorrow.strftime("%d.%m.%Y"),
        weekday_uz = _WEEKDAYS_UZ[tomorrow.weekday()],
        day_number = day,
        group_type = GroupType.ODD if is_odd else GroupType.EVEN,
        type_label = "Toq" if is_odd else "Juft",
    )


# ─── Xabar shablonlari ────────────────────────────────────────────────────────

def build_reminder_message(info: TomorrowInfo, audience: AudienceType) -> str:
    """
    Auditoriyaga qarab turli xabar matnini qaytaradi:
      PARENT  — ota-onalarga yo'naltirilgan
      STUDENT — o'quvchilarga yo'naltirilgan
    """
    if audience == AudienceType.PARENT:
        return (
            f"👨‍👩‍👧 Assalomu alaykum ertaga farzandlaringiz uyga vazifasini tekshiraman iltimos uyga vazifa qilishini nazoratga olishigiz so'rayman"
        )
    else:  # STUDENT
        return (
            f"📚 Bolalar ertaga darsga kechikib kemanglar uy vazifani hammadan soriyman !"
        )


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
    logger.info("=" * 55)
    logger.info("SCHEDULER: send_daily_reminders boshlandi")
    logger.info("=" * 55)

    try:
        info   = get_tomorrow_info(timezone_str)
        groups = await db.get_groups_by_type(info.group_type)

        logger.info(
            f"Ertangi kun: {info.date_str} ({info.type_label}) | "
            f"Guruhlar soni: {len(groups)}"
        )

        if not groups:
            logger.warning(f"Aktiv guruhlar topilmadi ({info.type_label} kun)")
            return

        ok, fail = 0, 0

        for group in groups:
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
                logger.info(
                    f"  ✅ [{audience_label}] '{group.name}' ({group.chat_id}) "
                    f"→ msg_id={sent.message_id}"
                )

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
                    except Exception as hw_err:
                        logger.warning(f"  Uy vazifasi yuborib bo'lmadi ({group.name}): {hw_err}")

            except Exception as e:
                fail += 1
                logger.error(
                    f"  ❌ [{audience_label}] '{group.name}' ({group.chat_id}): {e}"
                )

        logger.info(
            f"NATIJA: {ok} yuborildi, {fail} xato | "
            f"{info.date_str} | {info.type_label} kun"
        )
        # Shaxsiy davomat so'rovlari check_class_reminders() orqali yuboriladi

    except Exception as e:
        logger.exception(f"KRITIK XATO: {e}")

    logger.info("=" * 55)


# ─── Dars eslatmasi: har 10 daqiqada ────────────────────────────────────────

# 1-eslatma va 2-eslatma yuborilgan foydalanuvchilarni kuzatish
# Key: "user_id:date_str" — restart bo'lsa reset bo'ladi (normal holat)
_sent_first_reminder:  set[str] = set()
_sent_second_reminder: set[str] = set()


async def check_class_reminders(bot: Bot, db: DatabaseService, timezone_str: str) -> None:
    """
    Har 10 daqiqada ishga tushadi (06:00–19:30 Tashkent oralig'ida).
    Har guruh uchun dars vaqtidan 3 soat oldin faqat 2 marta eslatma yuboradi:
      1-eslatma: reminder_start dan 10 daqiqa ichida
      2-eslatma: reminder_start + 30 daqiqadan keyin (10 daqiqa oyna)
    """
    from keyboards import kb_attendance

    tz  = pytz.timezone(timezone_str)
    now = datetime.now(tz)

    # Faqat 06:00–19:30 oralig'ida ishlaydi
    if not (6 * 60 <= now.hour * 60 + now.minute <= 19 * 60 + 30):
        return

    weekday = now.weekday()
    if weekday == 6:  # Yakshanba — dars yo'q
        return

    day_type  = "ODD" if weekday in (0, 2, 4) else "EVEN"
    schedule  = CLASS_SCHEDULE.get(day_type, {})
    today_str = now.strftime("%Y-%m-%d")

    for group_name, class_time_str in schedule.items():
        class_hour, class_min = map(int, class_time_str.split(":"))
        class_dt       = now.replace(hour=class_hour, minute=class_min, second=0, microsecond=0)
        reminder_start = class_dt - timedelta(hours=3)

        # Umumiy oynadan tashqarida — o'tkazib yuboramiz
        if now < reminder_start or now >= class_dt:
            continue

        # Qaysi eslatma oynasida ekanligini aniqlaymiz
        in_first_window  = now < reminder_start + timedelta(minutes=10)
        in_second_window = (
            reminder_start + timedelta(minutes=30) <= now <
            reminder_start + timedelta(minutes=40)
        )

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
                text = (
                    f"📚 Bugun soat <b>{class_time_str}</b> da dars bor!\n"
                    f"Kelasizmi?"
                )
            else:  # in_second_window
                if key in _sent_second_reminder:
                    continue
                _sent_second_reminder.add(key)
                text = (
                    f"⏰ Hali javob bermagansiz!\n"
                    f"Dars <b>{class_time_str}</b> da boshlanadi."
                )

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


async def check_davomat_notify(bot: Bot, db: DatabaseService, timezone_str: str) -> None:
    """
    Har 10 daqiqada tekshiradi: dars boshlanganidan 20-30 daqiqa o'tgan
    guruhlar uchun kuratorlarga davomat yuborish eslatmasi ketadi.
    """
    from sqlalchemy import select
    from database import CuratorSession
    from keyboards import kb_davomat_start

    tz  = pytz.timezone(timezone_str)
    now = datetime.now(tz)

    if not (6 * 60 <= now.hour * 60 + now.minute <= 21 * 60):
        return

    weekday = now.weekday()
    if weekday == 6:  # Yakshanba — dars yo'q
        return

    day_type  = "ODD" if weekday in (0, 2, 4) else "EVEN"
    schedule  = CLASS_SCHEDULE.get(day_type, {})
    today_str = now.strftime("%Y-%m-%d")

    for group_name, class_time_str in schedule.items():
        notify_key = f"{group_name}:{today_str}"
        if notify_key in _sent_davomat_notify:
            continue

        class_hour, class_min = map(int, class_time_str.split(":"))
        class_dt     = now.replace(hour=class_hour, minute=class_min, second=0, microsecond=0)
        window_start = class_dt + timedelta(minutes=20)
        window_end   = class_dt + timedelta(minutes=30)

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
            f"📋 <b>{group_name}</b> guruhi dars boshlangandan "
            f"<b>20 daqiqa</b> o'tdi!\n\n"
            f"Davomat yoqlamasini ota-ona guruhiga yuborishingiz mumkin."
        )
        for cs in curator_sessions:
            try:
                await bot.send_message(
                    cs.telegram_id,
                    notify_text,
                    reply_markup=kb_davomat_start(group_name, today_str),
                )
            except Exception:
                pass

        logger.info(f"Davomat eslatmasi: {group_name} | {today_str}")


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

def setup_scheduler(bot: Bot, db: DatabaseService, timezone_str: str) -> AsyncIOScheduler:
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

    _scheduler_ref = scheduler
    logger.info(
        f"Scheduler sozlandi: har kuni {SEND_HOUR:02d}:{SEND_MINUTE:02d} + "
        f"har 10 daqiqada dars/davomat eslatmasi ({timezone_str})"
    )
    return scheduler
