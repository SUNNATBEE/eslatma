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
    # Yakshanba (6) — dars yo'q, is_odd=False (EVEN) qaytariladi,
    # lekin send_daily_reminders() Yakshanba uchun yubormasligi kerak.
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
            logger.info(
                f"SCHEDULER: Ertangi kun Yakshanba ({info.date_str}) — "
                f"dars yo'q, xabar yuborilmadi"
            )
            return

        groups = await db.get_groups_by_type(info.group_type)

        # Toq/juft kun o'chirilgan bo'lsa — to'xtatamiz
        day_setting_key = "AUTO_MSG_ODD" if info.group_type == GroupType.ODD else "AUTO_MSG_EVEN"
        if await db.get_setting(day_setting_key, "1") == "0":
            logger.info(
                f"SCHEDULER: {day_setting_key} o'chirilgan — "
                f"{info.type_label} kun xabarlari yuborilmadi"
            )
            return

        logger.info(
            f"Ertangi kun: {info.date_str} ({info.type_label}) | "
            f"Guruhlar soni: {len(groups)}"
        )

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
            result = await session.execute(
                select(Group).where(Group.name == group_name)
            )
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
        logger.info(
            f"TEST SEND: '{group_name}' ({group.chat_id}) → msg_id={sent.message_id}"
        )

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
            except Exception as hw_err:
                logger.warning(f"TEST SEND: Uy vazifasi yuborib bo'lmadi: {hw_err}")

        return (sent.message_id, group.chat_id)

    except Exception as e:
        logger.exception(f"TEST SEND: Xato: {e}")
        return None


# ─── Dars eslatmasi: har 10 daqiqada ────────────────────────────────────────

# 1-eslatma va 2-eslatma yuborilgan foydalanuvchilarni kuzatish
# Key: "user_id:date_str" — restart bo'lsa reset bo'ladi (normal holat)
_sent_first_reminder:  set[str] = set()
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

    tz  = pytz.timezone(timezone_str)
    now = datetime.now(tz)

    # Faqat 06:00–19:30 oralig'ida ishlaydi
    if not (6 * 60 <= now.hour * 60 + now.minute <= 19 * 60 + 30):
        return

    weekday = now.weekday()
    if weekday == 6:  # Yakshanba — dars yo'q
        return

    day_type  = "ODD" if weekday in (0, 2, 4) else "EVEN"

    # Toq/juft kun o'chirilgan bo'lsa — to'xtatamiz
    day_setting_key = "AUTO_MSG_ODD" if day_type == "ODD" else "AUTO_MSG_EVEN"
    if await db.get_setting(day_setting_key, "1") == "0":
        return

    schedule  = CLASS_SCHEDULE.get(day_type, {})
    today_str = now.strftime("%Y-%m-%d")

    for group_name, class_time_str in schedule.items():
        # Guruh uchun avto xabar o'chirilgan bo'lsa — o'tkazamiz
        if await db.get_setting(f"AUTO_MSG_GROUP:{group_name}", "1") == "0":
            continue
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
                try:
                    sent = await bot.send_message(
                        student.user_id, text,
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
                        await bot.delete_message(
                            student.user_id, _first_reminder_msg_ids.pop(key)
                        )
                    except Exception:
                        _first_reminder_msg_ids.pop(key, None)
                text = (
                    f"⏰ Hali javob bermagansiz!\n"
                    f"Dars <b>{class_time_str}</b> da boshlanadi."
                )
                try:
                    await bot.send_message(
                        student.user_id, text,
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
    # Avto xabar o'chirilgan bo'lsa — to'xtatamiz
    if await db.get_setting("AUTO_MSG_CURATORS", "1") == "0":
        return

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

    # Toq/juft kun o'chirilgan bo'lsa — to'xtatamiz
    day_setting_key = "AUTO_MSG_ODD" if day_type == "ODD" else "AUTO_MSG_EVEN"
    if await db.get_setting(day_setting_key, "1") == "0":
        return

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


# ─── Kunlik global reyting broadcast ─────────────────────────────────────────

_RANK_ICONS = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣"}


async def send_leaderboard_broadcast(
    bot: Bot,
    db: DatabaseService,
    webapp_url: str,
    timezone_str: str,
) -> None:
    """
    Har 3 kunda bir marta barcha aktiv o'quvchi guruhlariga global top-5 reyting yuboradi.
    Faqat AudienceType.STUDENT guruhlarga yuboriladi (PARENT guruhlar o'tkazib yuboriladi).
    Xabarda Mini App tugmasi bo'ladi (WebAppInfo — brauzerda emas, Mini App da ochiladi).
    """
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

    if not webapp_url:
        logger.warning("LEADERBOARD BROADCAST: WEBAPP_URL sozlanmagan — o'tkazib yuborildi")
        return

    tz       = pytz.timezone(timezone_str)
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
        icon  = _RANK_ICONS.get(i, f"{i}.")
        group = f" ({s.group_name})" if s.group_name else ""
        xp    = s.xp or 0
        rows.append(f"{icon} <b>{s.full_name}</b>{group} — <b>{xp} XP</b>")

    total = await db.get_students_count() if hasattr(db, "get_students_count") else len(leaders)
    top_line = "\n".join(rows)

    text = (
        f"🏆 <b>Kunlik Global Reyting</b> — {date_str}\n\n"
        f"{top_line}\n\n"
        f"👥 Jami o'quvchilar: <b>{total}</b> ta\n\n"
        f"💪 Siz ham yetib oling! Har kuni XP to'plang va birinchi o'ringa chiqing! 🚀\n"
        f"👇 Reyting va Mini App haqida to'liq ma'lumot uchun tugmani bosing."
    )

    # WebAppInfo ishlatiladi — oddiy brauzer emas, Telegram Mini App sifatida ochiladi
    student_url = webapp_url.rstrip("/") + "/student.html"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📊 Reytingni ko'rish / Посмотреть рейтинг",
            web_app=WebAppInfo(url=student_url),
        )],
    ])

    # Faqat aktiv O'QUVCHI guruhlariga yuboramiz (ota-ona guruhlar emas)
    groups = await db.get_all_groups()
    ok, fail = 0, 0
    for group in groups:
        if not group.is_active:
            continue
        if group.audience != AudienceType.STUDENT:
            logger.debug(
                f"LEADERBOARD BROADCAST: '{group.name}' — PARENT guruh, o'tkazib yuborildi"
            )
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
                "⚠️ <b>Akkountingiz o'chirildi!</b>\n\n"
                "Botda <b>7 kun</b> davomida faollik kuzatilmadi.\n\n"
                "Akkountingizni qayta faollashtirish uchun:\n"
                "/start → ro'yxatdan qayta o'ting.",
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
                    f"🔥 <b>Streak xavf ostida!</b>\n\n"
                    f"Sizda hozirda <b>{streak} kunlik streak</b> bor!\n"
                    f"Bugun Mini App ga kirmadingiz — streak yo'qolmasligi uchun hoziroq kiring.\n\n"
                    f"💡 Har kun kirish = ko'proq XP + bonus!",
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
                    f"🎉 <b>Haftalik Streak Bonus!</b>\n\n"
                    f"Ajoyib! Siz <b>7 kun ketma-ket</b> Mini App ga kirdingiz!\n"
                    f"<b>+{XP_WEEKLY_BONUS} XP</b> bonus berildi 🚀\n\n"
                    f"Jami XP: <b>{updated.xp if updated else '?'}</b>",
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

    # Global reyting broadcast (har 3 kunda bir marta, 21:05 da)
    # IntervalTrigger(days=3) — har 3 kunda bir marta ishga tushadi.
    # Birinchi ishga tushish: start_date ko'rsatilmasa botni qayta ishga
    # tushirgan vaqtdan boshlanadi, shu bois misfire_grace_time=300 (5 daqiqa).
    scheduler.add_job(
        func=send_leaderboard_broadcast,
        trigger=IntervalTrigger(days=3, timezone=timezone_str),
        args=[bot, db, webapp_url, timezone_str],
        id="daily_leaderboard_broadcast",
        name="3 kunlik global reyting xabari",
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
        f"Scheduler sozlandi: har kuni {SEND_HOUR:02d}:{SEND_MINUTE:02d} + "
        f"har 10 daqiqada dars/davomat eslatmasi + har 3 kunda reyting broadcast ({timezone_str})"
    )
    return scheduler
