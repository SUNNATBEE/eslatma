"""
handlers/attendance.py — Darsga boraman / kela olmayman tugmalari.
"""
import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from config import ADMIN_IDS
from database import DatabaseService

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data.startswith("attend:"))
async def handle_attendance(cb: CallbackQuery, db: DatabaseService, bot: Bot) -> None:
    """attend:yes:2026-03-17  yoki  attend:no:2026-03-17"""
    parts    = cb.data.split(":")
    status   = parts[1]   # "yes" / "no"
    date_str = parts[2]   # "2026-03-17"

    student = await db.get_student(cb.from_user.id)
    if not student:
        await cb.answer("❌ Avval ro'yxatdan o'ting!", show_alert=True)
        return

    await db.save_attendance(cb.from_user.id, date_str, status)
    await db.update_last_active(cb.from_user.id)

    label = "✅ Boraman" if status == "yes" else "❌ Kela olmayman"
    emoji = "✅" if status == "yes" else "❌"

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass

    await cb.answer(f"{emoji} Javobingiz qabul qilindi!")

    # Adminga bildirishnoma
    time_str = datetime.now().strftime("%H:%M")
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"{emoji} <b>{student.full_name}</b> — {label}\n"
                f"📚 Guruh: <b>{student.group_name}</b>\n"
                f"📅 Kun: {date_str} | 🕐 {time_str}",
            )
        except Exception:
            pass

    logger.info(f"Davomat: {student.full_name} — {label} | {date_str}")
