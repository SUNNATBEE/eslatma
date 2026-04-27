"""
handlers/attendance.py — Darsga boraman / kela olmayman tugmalari.

attend:yes:DATE  → darhol "boraman" saqlanadi
attend:no:DATE   → FSM: sabab so'raladi → admin + kurator + ota-onalar guruhiga yuboriladi
"""

import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS
from database import DatabaseService

logger = logging.getLogger(__name__)
router = Router()


# ─── FSM ──────────────────────────────────────────────────────────────────────


class AbsenceReasonFSM(StatesGroup):
    waiting_reason = State()


# ─── attend:yes ───────────────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("attend:yes:"))
async def handle_attendance_yes(cb: CallbackQuery, db: DatabaseService, bot: Bot) -> None:
    """attend:yes:2026-03-17"""
    date_str = cb.data.split(":")[2]

    student = await db.get_student(cb.from_user.id)
    if not student:
        await cb.answer("❌ Avval ro'yxatdan o'ting!", show_alert=True)
        return

    await db.save_attendance(cb.from_user.id, date_str, "yes")
    await db.update_last_active(cb.from_user.id)

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass

    await cb.answer("✅ Javobingiz qabul qilindi!")

    time_str = datetime.now().strftime("%H:%M")
    notify_text = (
        f"✅ <b>{student.full_name}</b> — Boraman\n"
        f"📚 Guruh: <b>{student.group_name}</b>\n"
        f"📅 Kun: {date_str} | 🕐 {time_str}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, notify_text)
        except Exception:
            pass

    # Faol kuratorlarga ham bildiramiz
    try:
        from sqlalchemy import select

        from database import CuratorSession

        async with db.session_factory() as db_sess:
            result = await db_sess.execute(select(CuratorSession))
            curator_sessions = list(result.scalars().all())
        for cs in curator_sessions:
            if cs.telegram_id not in ADMIN_IDS:
                try:
                    await bot.send_message(cs.telegram_id, notify_text)
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Kuratorgа bildirishnoma yuborishda xato: {e}")

    logger.info(f"Davomat: {student.full_name} — Boraman | {date_str}")


# ─── attend:no → sabab so'rash ────────────────────────────────────────────────


@router.callback_query(F.data.startswith("attend:no:"))
async def handle_attendance_no(cb: CallbackQuery, db: DatabaseService, state: FSMContext) -> None:
    """attend:no:2026-03-17 — sabab so'raladi"""
    date_str = cb.data.split(":")[2]

    student = await db.get_student(cb.from_user.id)
    if not student:
        await cb.answer("❌ Avval ro'yxatdan o'ting!", show_alert=True)
        return

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass

    await cb.answer()
    await state.set_state(AbsenceReasonFSM.waiting_reason)
    await state.update_data(date_str=date_str)

    await cb.message.answer(
        "⚠️ <b>Diqqat!</b> Bu habar <b>ota-onangizga, ustozingizga va kuratorigizga</b> yuboriladi!\n\n"
        "Iltimos, kela olmasligingiz <b>sababini</b> yozing:\n"
        "<i>(Masalan: Kasal, Safarda, Oilaviy sabab...)</i>",
        parse_mode="HTML",
    )

    logger.info(f"Davomat: {student.full_name} → sabab so'raldi | {date_str}")


# ─── Sabab qabul qilish ────────────────────────────────────────────────────────


@router.message(StateFilter(AbsenceReasonFSM.waiting_reason))
async def handle_absence_reason(msg: Message, db: DatabaseService, bot: Bot, state: FSMContext) -> None:
    """O'quvchi sababini yozadi."""
    data = await state.get_data()
    date_str = data.get("date_str", datetime.now().strftime("%Y-%m-%d"))
    reason = msg.text.strip() if msg.text else "Sabab ko'rsatilmagan"

    student = await db.get_student(msg.from_user.id)
    if not student:
        await state.clear()
        return

    # Attendanceni sabab bilan saqlaymiz
    await db.save_attendance(msg.from_user.id, date_str, "no", reason=reason)
    await db.update_last_active(msg.from_user.id)
    await state.clear()

    await msg.answer("✅ Sababingiz qabul qilindi. Tezroq tuzalib keling! 💪")

    # Bildirishnoma matni
    time_str = datetime.now().strftime("%H:%M")
    notify_text = (
        f"📌 <b>{student.full_name}</b> — <b>{student.group_name}</b>\n"
        f"Kela olmayman sababi: {reason}\n"
        f"📅 Kun: {date_str} | 🕐 {time_str}"
    )

    # Adminlarga
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, notify_text, parse_mode="HTML")
        except Exception:
            pass

    # Faol kuratorlarga
    try:
        from sqlalchemy import select

        from database import CuratorSession

        async with db.session_factory() as session:
            result = await session.execute(select(CuratorSession))
            curator_sessions = list(result.scalars().all())
        for cs in curator_sessions:
            if cs.telegram_id not in ADMIN_IDS:  # Adminga ikki marta yubormaslik
                try:
                    await bot.send_message(cs.telegram_id, notify_text, parse_mode="HTML")
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Kuratorgа bildirishnoma yuborishda xato: {e}")

    logger.info(f"Davomat: {student.full_name} — Kelmaydi | {date_str} | Sabab: {reason}")
