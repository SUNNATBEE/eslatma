"""
handlers/student.py — O'quvchi paneli + admin amallar:
  • O'quvchilar ro'yxati, detail, bot orqali xabar, o'chirish
  • Uy vazifasi yuborish (FSM) — har qanday kontent (video/fayl/link/matn)
"""

import logging
import re
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS
from credentials import MARS_GROUPS
from database import DatabaseService
from keyboards import (
    kb_admin_students,
    kb_back_to_panel,
    kb_confirm_remove_student,
    kb_hw_delete_confirm,
    kb_hw_groups,
    kb_hw_manage,
    kb_hw_menu,
    kb_read_confirm,
    kb_student_detail,
    kb_student_menu,
)

logger = logging.getLogger(__name__)
router = Router()


# ════════════════════════════════════════════════════════════════════════════════
# O'QUVCHI PANELI
# ════════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "student:homework")
async def student_view_homework(cb: CallbackQuery, db: DatabaseService, bot: Bot) -> None:
    student = await db.get_student(cb.from_user.id)
    if not student:
        await cb.answer("❌ Avval ro'yxatdan o'ting!", show_alert=True)
        return

    hw = await db.get_homework(student.group_name)
    if not hw:
        await cb.answer("📭 Hozircha uy vazifasi yo'q.", show_alert=True)
        return

    date_str = hw.sent_at.strftime("%d.%m.%Y %H:%M")
    await cb.message.answer(
        f"📚 <b>Uy vazifasi — {student.group_name}</b>\n"
        f"🕐 {date_str}\n\n"
        f"⬇️ Vazifa:",
    )
    try:
        await bot.copy_message(
            chat_id=cb.from_user.id,
            from_chat_id=hw.from_chat_id,
            message_id=hw.message_id,
        )
    except TelegramBadRequest as e:
        await cb.message.answer(f"⚠️ Vazifani yuklashda xato: <code>{e}</code>")
    await cb.answer()


# ── O'quvchi "O'qidim" tugmasini bosdi ────────────────────────────────────────

@router.callback_query(F.data.startswith("read_confirm:"))
async def student_read_confirm(
    cb: CallbackQuery,
    db: DatabaseService,
    bot: Bot,
) -> None:
    admin_id = int(cb.data.split(":")[1])
    student  = await db.get_student(cb.from_user.id)
    name     = student.full_name if student else cb.from_user.full_name
    group    = student.group_name if student else "—"
    time_str = datetime.now().strftime("%H:%M")

    # Adminga bildirishnoma
    try:
        await bot.send_message(
            admin_id,
            f"👁 <b>{name}</b> xabaringizni o'qidi\n"
            f"📚 Guruh: <b>{group}</b>\n"
            f"🕐 {time_str}",
        )
    except Exception:
        logger.warning(
            "Read receipt admin notify yuborilmadi | admin_id=%s user_id=%s",
            admin_id,
            cb.from_user.id,
            exc_info=True,
        )

    # Tugmani o'chiramiz
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass

    await cb.answer("✅ Tasdiqlandi!", show_alert=False)


# ════════════════════════════════════════════════════════════════════════════════
# ADMIN: O'QUVCHILAR RO'YXATI
# ════════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("admin:students:"))
async def admin_view_students(cb: CallbackQuery, db: DatabaseService) -> None:
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("❌ Faqat adminlar uchun!", show_alert=True)
        return

    active_group = cb.data.split(":", 2)[2]
    students     = await db.get_all_students()
    count        = len(students)

    header = (
        f"👥 <b>Ro'yxatdan o'tgan o'quvchilar: {count} ta</b>\n\n"
        f"<i>Ismiga bosing — batafsil ma'lumot va amallar</i>"
    )
    markup = kb_admin_students(students, MARS_GROUPS, active_group)
    try:
        await cb.message.edit_text(header, reply_markup=markup)
    except TelegramBadRequest:
        await cb.message.answer(header, reply_markup=markup)
    await cb.answer()


# ── O'quvchi detail sahifasi ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:student_detail:"))
async def admin_student_detail(cb: CallbackQuery, db: DatabaseService) -> None:
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("❌ Faqat adminlar uchun!", show_alert=True)
        return

    user_id = int(cb.data.split(":", 2)[2])
    student = await db.get_student(user_id)
    if not student:
        await cb.answer("❌ O'quvchi topilmadi (o'chirilgan bo'lishi mumkin).", show_alert=True)
        return

    tg = student.telegram_username or f"ID: {student.user_id}"
    reg_date = student.registered_at.strftime("%d.%m.%Y %H:%M") if student.registered_at else "—"
    phone = student.phone_number or "—"

    text = (
        f"👤 <b>{student.full_name}</b>\n\n"
        f"📚 Guruh: <b>{student.group_name}</b>\n"
        f"🆔 Mars ID: <code>{student.mars_id}</code>\n"
        f"📱 Telefon: <code>{phone}</code>\n"
        f"💬 Telegram: {tg}\n"
        f"🔗 User ID: <code>{student.user_id}</code>\n"
        f"📅 Ro'yxatdan: {reg_date}"
    )
    try:
        await cb.message.edit_text(text, reply_markup=kb_student_detail(student))
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=kb_student_detail(student))
    await cb.answer()


# ── Bot orqali o'quvchiga xabar yuborish ──────────────────────────────────────

class MessageStudentFSM(StatesGroup):
    waiting_message = State()


@router.callback_query(F.data.startswith("admin:msg_student:"))
async def admin_msg_student_start(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("❌ Faqat adminlar uchun!", show_alert=True)
        return

    target_id = int(cb.data.split(":", 2)[2])
    await state.update_data(target_id=target_id)
    await state.set_state(MessageStudentFSM.waiting_message)
    await cb.message.edit_text(
        "📩 <b>O'quvchiga xabar yuborish</b>\n\n"
        "Xabaringizni yuboring (matn, rasm, video, fayl — istalgan narsa):\n\n"
        "<i>Bekor qilish uchun /start yozing</i>"
    )
    await cb.answer()


@router.message(StateFilter(MessageStudentFSM.waiting_message))
async def admin_msg_student_send(
    message: Message,
    state: FSMContext,
    bot: Bot,
    db: DatabaseService,
) -> None:
    data      = await state.get_data()
    target_id = data.get("target_id")
    student   = await db.get_student(target_id)
    await state.clear()

    try:
        await bot.copy_message(
            chat_id=target_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=kb_read_confirm(message.from_user.id),
        )
        name = student.full_name if student else str(target_id)
        await message.answer(
            f"✅ Xabar yuborildi → <b>{name}</b>\n"
            f"<i>O'quvchi 'O'qidim' bosganida sizga xabar keladi.</i>",
            reply_markup=kb_back_to_panel(),
        )
    except Exception as e:
        name = student.full_name if student else str(target_id)
        err  = str(e).lower()
        if "blocked" in err or "deactivated" in err or "not found" in err or "chat not found" in err:
            reason = "O'quvchi botni bloklagan yoki o'chirgan"
        elif "forbidden" in err:
            reason = "O'quvchi botga ruxsat bermagan"
        else:
            reason = f"Texnik xato: {e}"

        await message.answer(
            f"❌ <b>{name}</b> ga xabar yetmadi\n\n"
            f"📌 Sabab: {reason}\n\n"
            f"💡 O'quvchi botni qayta ishga tushirishi kerak.",
            reply_markup=kb_back_to_panel(),
        )


# ── O'quvchini ro'yxatdan o'chirish ───────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:remove_student:"))
async def admin_remove_student_ask(cb: CallbackQuery, db: DatabaseService) -> None:
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("❌ Faqat adminlar uchun!", show_alert=True)
        return

    user_id = int(cb.data.split(":", 2)[2])
    student = await db.get_student(user_id)
    name    = student.full_name if student else str(user_id)

    try:
        await cb.message.edit_text(
            f"⚠️ <b>Tasdiqlash</b>\n\n"
            f"<b>{name}</b> ni ro'yxatdan o'chirmoqchimisiz?\n\n"
            f"<i>O'chirilgandan so'ng o'quvchi qaytadan ro'yxatdan o'tishi kerak bo'ladi.</i>",
            reply_markup=kb_confirm_remove_student(user_id),
        )
    except TelegramBadRequest:
        pass
    await cb.answer()


@router.callback_query(F.data.startswith("admin:remove_confirm:"))
async def admin_remove_student_do(cb: CallbackQuery, db: DatabaseService) -> None:
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("❌ Faqat adminlar uchun!", show_alert=True)
        return

    user_id = int(cb.data.split(":", 2)[2])
    student = await db.get_student(user_id)
    name    = student.full_name if student else str(user_id)

    deleted = await db.delete_student(user_id)
    if deleted:
        await cb.message.edit_text(
            f"✅ <b>{name}</b> ro'yxatdan o'chirildi.\n\n"
            f"<i>O'quvchi qaytadan /start bossa, ro'yxatdan o'tishi so'raladi.</i>",
            reply_markup=kb_back_to_panel(),
        )
        await cb.answer()
    else:
        await cb.answer("❌ O'quvchi topilmadi.", show_alert=True)


# ════════════════════════════════════════════════════════════════════════════════
# ADMIN: UY VAZIFASI YUBORISH (FSM)
# ════════════════════════════════════════════════════════════════════════════════

class HomeworkFSM(StatesGroup):
    waiting_group   = State()
    waiting_content = State()


# ─── Uy vazifasi bosh menyusi ─────────────────────────────────────────────────

@router.callback_query(F.data == "admin:hw_menu")
async def admin_hw_menu(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("❌", show_alert=True)
        return
    await state.clear()
    try:
        await cb.message.edit_text(
            "📝 <b>Uy vazifasi</b>\n\nAmal tanlang:",
            reply_markup=kb_hw_menu(),
        )
    except TelegramBadRequest:
        await cb.message.answer("📝 <b>Uy vazifasi</b>", reply_markup=kb_hw_menu())
    await cb.answer()


@router.callback_query(F.data == "admin:hw_list")
async def admin_hw_list(cb: CallbackQuery, db: DatabaseService) -> None:
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("❌", show_alert=True)
        return

    homeworks = {}
    for g in MARS_GROUPS:
        hw = await db.get_homework(g)
        if hw:
            homeworks[g] = hw

    try:
        await cb.message.edit_text(
            "📋 <b>Guruhlar bo'yicha uy vazifalari</b>\n\n"
            "Vazifani o'zgartirish yoki o'chirish uchun tanlang:",
            reply_markup=kb_hw_manage(MARS_GROUPS, homeworks),
        )
    except TelegramBadRequest:
        await cb.message.answer(
            "📋 <b>Uy vazifalari ro'yxati</b>",
            reply_markup=kb_hw_manage(MARS_GROUPS, homeworks),
        )
    await cb.answer()


@router.callback_query(F.data.startswith("hw:delete_ask:"))
async def admin_hw_delete_ask(cb: CallbackQuery) -> None:
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("❌", show_alert=True)
        return
    group = cb.data.split(":", 2)[2]
    try:
        await cb.message.edit_text(
            f"🗑 <b>{group}</b> guruhining uy vazifasini o'chirasizmi?\n\n"
            f"Bu amal qaytarib bo'lmaydi.",
            reply_markup=kb_hw_delete_confirm(group),
        )
    except TelegramBadRequest:
        await cb.message.answer(
            f"🗑 O'chirasizmi? <b>{group}</b>",
            reply_markup=kb_hw_delete_confirm(group),
        )
    await cb.answer()


@router.callback_query(F.data.startswith("hw:delete_yes:"))
async def admin_hw_delete_yes(cb: CallbackQuery, db: DatabaseService) -> None:
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("❌", show_alert=True)
        return
    group = cb.data.split(":", 2)[2]
    deleted = await db.delete_homework(group)
    msg = f"✅ <b>{group}</b> uy vazifasi o'chirildi." if deleted else f"📭 <b>{group}</b> da vazifa yo'q edi."
    try:
        await cb.message.edit_text(msg, reply_markup=kb_hw_menu())
    except TelegramBadRequest:
        await cb.message.answer(msg, reply_markup=kb_hw_menu())
    await cb.answer()


@router.callback_query(F.data.startswith("hw:edit:"))
async def admin_hw_edit_start(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("❌", show_alert=True)
        return
    group = cb.data.split(":", 2)[2]
    await state.update_data(group=group)
    await state.set_state(HomeworkFSM.waiting_content)
    try:
        await cb.message.edit_text(
            f"✏️ <b>{group}</b> uchun yangi uy vazifasi:\n\n"
            f"Vazifani yuboring (video, rasm, matn, fayl — istalgan):\n\n"
            f"<i>Bekor qilish: /start</i>",
        )
    except TelegramBadRequest:
        await cb.message.answer(
            f"✏️ <b>{group}</b> uchun yangi uy vazifasini yuboring:"
        )
    await cb.answer()


# ─── Yangi uy vazifasi ────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:send_hw")
async def admin_send_hw_start(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("❌ Bu amal faqat adminlar uchun!", show_alert=True)
        return
    await state.set_state(HomeworkFSM.waiting_group)
    await cb.message.edit_text(
        "📝 <b>Uy vazifasi yuborish</b>\n\n"
        "Guruhni tanlang:",
        reply_markup=kb_hw_groups(MARS_GROUPS),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("hw:group:"), StateFilter(HomeworkFSM.waiting_group))
async def admin_hw_group_selected(cb: CallbackQuery, state: FSMContext) -> None:
    group = cb.data.split(":", 2)[2]
    await state.update_data(group=group)
    await state.set_state(HomeworkFSM.waiting_content)
    await cb.message.edit_text(
        f"📚 Guruh: <b>{group}</b>\n\n"
        f"Uy vazifasini yuboring:\n"
        f"<i>Matn, havola (Figma, YouTube...), rasm, video, fayl —\n"
        f"istalgan narsani yuboring, bot o'z vaqtida guruhga yuboradi.</i>\n\n"
        f"<i>Bekor qilish: /start</i>",
    )
    await cb.answer()


@router.message(StateFilter(HomeworkFSM.waiting_content))
async def admin_hw_content(
    message: Message,
    state: FSMContext,
    db: DatabaseService,
) -> None:
    data  = await state.get_data()
    group = data.get("group", "")

    # Xabar ma'lumotini saqlaymiz (copy_message uchun)
    await db.set_homework(
        group_name=group,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )
    await state.clear()

    await message.answer(
        f"✅ <b>Uy vazifasi saqlandi!</b>\n\n"
        f"📚 Guruh: <b>{group}</b>\n\n"
        f"⏰ Bugungi <b>20:00</b> da kunlik eslatma bilan birga\n"
        f"   guruh chatiga avtomatik yuboriladi.",
        reply_markup=kb_back_to_panel(),
    )


# ════════════════════════════════════════════════════════════════════════════════
# O'QUVCHI: TELEFON RAQAMNI O'ZGARTIRISH
# ════════════════════════════════════════════════════════════════════════════════

class ChangePhoneFSM(StatesGroup):
    waiting_phone = State()


def _valid_phone(phone: str) -> bool:
    return bool(re.fullmatch(r"\+998\d{9}", phone))


@router.callback_query(F.data == "student:change_phone")
async def student_change_phone_start(cb: CallbackQuery, state: FSMContext, db: DatabaseService) -> None:
    student = await db.get_student(cb.from_user.id)
    if not student:
        await cb.answer("❌ Avval ro'yxatdan o'ting!", show_alert=True)
        return
    current = student.phone_number or "kiritilmagan"
    await state.set_state(ChangePhoneFSM.waiting_phone)
    await cb.message.answer(
        f"📱 <b>Telefon raqamni o'zgartirish</b>\n\n"
        f"Hozirgi raqam: <code>{current}</code>\n\n"
        f"Yangi raqamni kiriting:\n"
        f"Namuna: <code>+998901234567</code>\n"
        f"<i>(+998 dan boshlang, jami 12 raqam)</i>\n\n"
        f"<i>Bekor qilish: /start</i>",
    )
    await cb.answer()


@router.callback_query(F.data == "student:report")
async def student_report_issue(cb: CallbackQuery, db: DatabaseService, bot: Bot) -> None:
    """O'quvchi bot muammosi haqida admin ga xabar yuboradi."""
    student = await db.get_student(cb.from_user.id)
    name    = student.full_name if student else cb.from_user.full_name
    group   = student.group_name if student else "—"
    tg      = cb.from_user.username or str(cb.from_user.id)

    notify = (
        f"⚠️ <b>Bot muammosi haqida xabar</b>\n\n"
        f"👤 O'quvchi: <b>{name}</b>\n"
        f"📚 Guruh: <b>{group}</b>\n"
        f"💬 Telegram: @{tg}\n\n"
        f"📌 O'quvchi botda muammo borligini bildirmoqda."
    )
    sent = 0
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, notify)
            sent += 1
        except Exception:
            pass

    if sent:
        await cb.answer("✅ Xabar adminga yuborildi! Tez orada hal qilinadi.", show_alert=True)
    else:
        await cb.answer("⚠️ Xabar yuborib bo'lmadi. Keyinroq urinib ko'ring.", show_alert=True)


@router.message(StateFilter(ChangePhoneFSM.waiting_phone))
async def student_change_phone_save(
    message: Message,
    state: FSMContext,
    db: DatabaseService,
    bot: Bot,
) -> None:
    phone = message.text.strip() if message.text else ""

    if not _valid_phone(phone):
        await message.answer(
            "❌ <b>Noto'g'ri format!</b>\n\n"
            "Format: <code>+998901234567</code>\n"
            "<i>+998 dan boshlang, keyin 9 ta raqam (jami 12 raqam).</i>\n\n"
            "Qayta kiriting:"
        )
        return

    await db.update_student_phone(message.from_user.id, phone)
    await state.clear()

    student = await db.get_student(message.from_user.id)
    name = student.full_name if student else str(message.from_user.id)

    await message.answer(
        f"✅ <b>Telefon raqam yangilandi!</b>\n\n"
        f"📱 Yangi raqam: <code>{phone}</code>",
        reply_markup=kb_student_menu(),
    )

    # Adminga bildirishnoma
    from config import ADMIN_IDS
    tg = student.telegram_username if student else str(message.from_user.id)
    group = student.group_name if student else "—"
    admin_text = (
        f"📱 <b>O'quvchi telefon raqamini o'zgartirdi</b>\n\n"
        f"👤 Ism: <b>{name}</b>\n"
        f"📚 Guruh: <b>{group}</b>\n"
        f"📱 Yangi raqam: <code>{phone}</code>\n"
        f"💬 Telegram: {tg}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text)
        except Exception:
            pass
