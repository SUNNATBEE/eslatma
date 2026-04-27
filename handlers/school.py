"""
handlers/school.py — Dars jadvali + Ustozga savol yuborish.
"""

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS
from credentials import MARS_GROUPS
from database import DatabaseService
from keyboards import kb_back_to_panel, kb_hw_groups, kb_student_menu

logger = logging.getLogger(__name__)
router = Router()


# ════════════════════════════════════════════════════════════════════════════════
# O'QUVCHI: DARS JADVALINI KO'RISH
# ════════════════════════════════════════════════════════════════════════════════


@router.callback_query(F.data == "student:schedule")
async def student_view_schedule(cb: CallbackQuery, db: DatabaseService, bot: Bot) -> None:
    student = await db.get_student(cb.from_user.id)
    if not student:
        await cb.answer("❌ Avval ro'yxatdan o'ting!", show_alert=True)
        return

    await db.update_last_active(cb.from_user.id)
    sched = await db.get_schedule(student.group_name)
    if not sched:
        await cb.answer("📭 Jadval hali qo'yilmagan.", show_alert=True)
        return

    try:
        await bot.copy_message(
            chat_id=cb.from_user.id,
            from_chat_id=sched.from_chat_id,
            message_id=sched.message_id,
        )
    except TelegramBadRequest as e:
        await cb.message.answer(f"⚠️ Jadvalni yuklashda xato: <code>{e}</code>")
    await cb.answer()


# ════════════════════════════════════════════════════════════════════════════════
# O'QUVCHI: USTOZGA SAVOL YUBORISH
# ════════════════════════════════════════════════════════════════════════════════


class QuestionFSM(StatesGroup):
    waiting_question = State()


@router.callback_query(F.data == "student:ask")
async def student_ask_start(cb: CallbackQuery, state: FSMContext, db: DatabaseService) -> None:
    student = await db.get_student(cb.from_user.id)
    if not student:
        await cb.answer("❌ Avval ro'yxatdan o'ting!", show_alert=True)
        return

    await state.update_data(student_user_id=cb.from_user.id)
    await state.set_state(QuestionFSM.waiting_question)
    try:
        await cb.message.edit_text(
            "❓ <b>Ustozga savol</b>\n\n"
            "Savolingizni yuboring (matn, rasm, ovoz — istalgan):\n\n"
            "<i>Bekor qilish: /start</i>",
        )
    except TelegramBadRequest:
        await cb.message.answer(
            "❓ <b>Ustozga savol</b>\n\nSavolingizni yuboring:\n\n<i>Bekor qilish: /start</i>",
        )
    await cb.answer()


@router.message(StateFilter(QuestionFSM.waiting_question))
async def student_ask_send(message: Message, state: FSMContext, db: DatabaseService, bot: Bot) -> None:
    student = await db.get_student(message.from_user.id)
    if not student:
        await state.clear()
        return

    q = await db.save_question(
        user_id=message.from_user.id,
        student_name=student.full_name,
        group_name=student.group_name,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )
    await state.clear()
    await db.update_last_active(message.from_user.id)

    await message.answer(
        "✅ Savolingiz ustozga yuborildi!\nJavob bot orqali keladi.",
        reply_markup=kb_student_menu(),
    )

    # Adminga yuborish
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📩 Javob berish",
            callback_data=f"admin:answer_q:{message.from_user.id}:{q.id}",
        )
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"❓ <b>Yangi savol!</b>\n\n👤 {student.full_name} | 📚 {student.group_name}",
                reply_markup=builder.as_markup(),
            )
            await bot.copy_message(
                chat_id=admin_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
        except Exception as e:
            logger.warning(f"Admin {admin_id}: {e}")


# ─── Admin: savolga javob berish ──────────────────────────────────────────────


class AnswerFSM(StatesGroup):
    waiting_answer = State()


@router.callback_query(F.data.startswith("admin:answer_q:"))
async def admin_answer_start(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("❌ Faqat admin!", show_alert=True)
        return
    parts = cb.data.split(":")
    student_id = int(parts[2])
    q_id = int(parts[3])
    await state.update_data(student_id=student_id, q_id=q_id)
    await state.set_state(AnswerFSM.waiting_answer)
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await cb.message.answer(
        "📝 Javobingizni yuboring (matn, rasm, video — istalgan):\n\n<i>Bekor qilish: /start</i>",
    )
    await cb.answer()


@router.message(StateFilter(AnswerFSM.waiting_answer))
async def admin_answer_send(message: Message, state: FSMContext, db: DatabaseService, bot: Bot) -> None:
    data = await state.get_data()
    student_id = data.get("student_id")
    q_id = data.get("q_id")
    await state.clear()

    try:
        await bot.copy_message(
            chat_id=student_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        await db.mark_question_answered(q_id)
        await message.answer("✅ Javob o'quvchiga yuborildi!", reply_markup=kb_back_to_panel())
    except Exception as e:
        await message.answer(
            f"❌ Yuborib bo'lmadi: <code>{e}</code>",
            reply_markup=kb_back_to_panel(),
        )


# ════════════════════════════════════════════════════════════════════════════════
# ADMIN: DARS JADVALINI O'RNATISH
# ════════════════════════════════════════════════════════════════════════════════


class ScheduleFSM(StatesGroup):
    waiting_group = State()
    waiting_content = State()


@router.callback_query(F.data == "admin:set_schedule")
async def admin_schedule_start(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("❌ Faqat admin!", show_alert=True)
        return
    await state.set_state(ScheduleFSM.waiting_group)
    await cb.message.edit_text(
        "📅 <b>Dars jadvali o'rnatish</b>\n\nGuruhni tanlang:",
        reply_markup=kb_hw_groups(MARS_GROUPS, prefix="sched"),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sched:group:"), StateFilter(ScheduleFSM.waiting_group))
async def admin_schedule_group(cb: CallbackQuery, state: FSMContext) -> None:
    group = cb.data.split(":", 2)[2]
    await state.update_data(group=group)
    await state.set_state(ScheduleFSM.waiting_content)
    await cb.message.edit_text(
        f"📅 Guruh: <b>{group}</b>\n\n"
        "Jadvalni yuboring:\n"
        "<i>(Rasm, matn, jadval faylini yuboring)</i>\n\n"
        "<i>Bekor qilish: /start</i>",
    )
    await cb.answer()


@router.message(StateFilter(ScheduleFSM.waiting_content))
async def admin_schedule_content(message: Message, state: FSMContext, db: DatabaseService) -> None:
    data = await state.get_data()
    group = data.get("group", "")
    await db.set_schedule(group, message.chat.id, message.message_id)
    await state.clear()
    await message.answer(
        f"✅ <b>{group}</b> guruhi uchun jadval saqlandi!\nO'quvchilar 'Dars jadvali' tugmasidan ko'ra oladi.",
        reply_markup=kb_back_to_panel(),
    )
