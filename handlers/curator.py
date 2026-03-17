"""
handlers/curator.py — Kurator paneli va o'quvchi bilan relaye chat.

Muhim: kurator relay handlerlari faqat BaseFilter orqali ishlaydi —
        oddiy o'quvchi xabarlari bu handlerga HECH QACHON tushmaydi.
"""

import logging
from datetime import datetime

import pytz
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from class_schedule import CLASS_SCHEDULE
from config import ADMIN_IDS, TIMEZONE
from credentials import MARS_GROUPS
from curator_credentials import CURATORS
from database import AudienceType, DatabaseService
from keyboards import (
    kb_curator_active_chat,
    kb_curator_confirm_end,
    kb_curator_contact,
    kb_curator_panel,
    kb_curator_read,
    kb_curator_students,
    kb_davomat_mark,
    kb_select_parent_group,
)

logger = logging.getLogger(__name__)
router = Router()


# ════════════════════════════════════════════════════════════════════════════════
# FILTRLAR
# ════════════════════════════════════════════════════════════════════════════════

class _CuratorHasActiveChat(BaseFilter):
    """Faqat kurator sessiyasi + faol chati bo'lganda True."""
    async def __call__(self, message: Message, db: DatabaseService) -> bool:
        s = await db.get_curator_session(message.from_user.id)
        if not s:
            return False
        return await db.get_active_curator_chat_by_curator(message.from_user.id) is not None


class _StudentInCuratorChat(BaseFilter):
    """Faqat o'quvchi faol kurator chatida bo'lganda True (kuratorlar bundan mustasno)."""
    async def __call__(self, message: Message, db: DatabaseService) -> bool:
        if await db.get_curator_session(message.from_user.id):
            return False   # kurator — uning uchun alohida filter
        return await db.get_active_curator_chat_by_student(message.from_user.id) is not None


# ════════════════════════════════════════════════════════════════════════════════
# YORDAMCHI
# ════════════════════════════════════════════════════════════════════════════════

def _cinfo(key: str) -> dict:
    return CURATORS.get(key, {})

def _cheader(key: str) -> str:
    info = _cinfo(key)
    name = info.get("full_name", "Kurator")
    tg   = info.get("telegram_username", "")
    return f"<b>Kurator {name}{' ' + tg if tg else ''}</b>"


# ════════════════════════════════════════════════════════════════════════════════
# LOGIN FSM
# ════════════════════════════════════════════════════════════════════════════════

class CuratorLoginFSM(StatesGroup):
    waiting_login    = State()
    waiting_password = State()


@router.message(Command("curator"))
async def cmd_curator(message: Message, state: FSMContext, db: DatabaseService) -> None:
    await state.clear()
    session = await db.get_curator_session(message.from_user.id)
    if session:
        cname = _cinfo(session.curator_key).get("full_name", session.curator_key)
        await message.answer(
            f"👋 Xush kelibsiz, <b>Kurator {cname}</b>!\n\nPanel:",
            reply_markup=kb_curator_panel(),
        )
        return
    await state.set_state(CuratorLoginFSM.waiting_login)
    await message.answer("🔐 <b>Kurator paneli</b>\n\nLoginni kiriting:")


@router.message(StateFilter(CuratorLoginFSM.waiting_login))
async def curator_enter_login(message: Message, state: FSMContext) -> None:
    login = message.text.strip().lower() if message.text else ""
    if login not in CURATORS:
        await message.answer("❌ Bunday login topilmadi. Qayta kiriting:")
        return
    await state.update_data(curator_login=login)
    await state.set_state(CuratorLoginFSM.waiting_password)
    await message.answer("🔑 Parolni kiriting:")


@router.message(StateFilter(CuratorLoginFSM.waiting_password))
async def curator_enter_password(
    message: Message, state: FSMContext, db: DatabaseService
) -> None:
    data     = await state.get_data()
    login    = data.get("curator_login", "")
    password = message.text.strip() if message.text else ""
    cred     = CURATORS.get(login, {})

    if cred.get("password") != password:
        await message.answer("❌ Parol noto'g'ri. Qayta kiriting:")
        return

    await state.clear()
    await db.set_curator_session(message.from_user.id, login)
    await db.update_curator_last_active(message.from_user.id)
    cname = cred.get("full_name", login)
    await message.answer(
        f"✅ <b>Xush kelibsiz, Kurator {cname}!</b>\n\nPanel:",
        reply_markup=kb_curator_panel(),
    )
    logger.info(f"Kurator login: {cname} (TG {message.from_user.id})")


# ════════════════════════════════════════════════════════════════════════════════
# PANEL TUGMALARI
# ════════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "cur:panel")
async def cur_panel(cb: CallbackQuery, state: FSMContext, db: DatabaseService) -> None:
    session = await db.get_curator_session(cb.from_user.id)
    if not session:
        await cb.answer("❌ Avval /curator bilan kiring!", show_alert=True); return
    await db.update_curator_last_active(cb.from_user.id)
    await state.clear()
    cname = _cinfo(session.curator_key).get("full_name", session.curator_key)
    try:
        await cb.message.edit_text(
            f"👋 <b>Kurator {cname}</b> — Panel:", reply_markup=kb_curator_panel()
        )
    except TelegramBadRequest:
        await cb.message.answer(
            f"👋 <b>Kurator {cname}</b> — Panel:", reply_markup=kb_curator_panel()
        )
    await cb.answer()


@router.callback_query(F.data == "cur:logout")
async def cur_logout(cb: CallbackQuery, db: DatabaseService) -> None:
    await db.remove_curator_session(cb.from_user.id)
    try:
        await cb.message.edit_text("👋 Paneldan chiqdingiz. Qayta kirish: /curator")
    except TelegramBadRequest:
        await cb.message.answer("👋 Paneldan chiqdingiz. Qayta kirish: /curator")
    await cb.answer()


@router.callback_query(F.data == "cur:report")
async def cur_report_issue(cb: CallbackQuery, db: DatabaseService, bot: Bot) -> None:
    """Kurator bot muammosi haqida adminga xabar yuboradi."""
    session = await db.get_curator_session(cb.from_user.id)
    curator_key = session.curator_key if session else "—"
    tg = cb.from_user.username or str(cb.from_user.id)

    notify = (
        f"⚠️ <b>Bot muammosi — Kurator xabari</b>\n\n"
        f"👩‍💼 Kurator: <b>{curator_key}</b>\n"
        f"💬 Telegram: @{tg}\n\n"
        f"📌 Kurator botda muammo borligini bildirmoqda."
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
        await cb.answer("⚠️ Xabar yuborib bo'lmadi.", show_alert=True)


# ════════════════════════════════════════════════════════════════════════════════
# DAVOMAT MENYUSI — MANUAL START
# ════════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "cur:davomat_menu")
async def cur_davomat_menu(
    cb: CallbackQuery, db: DatabaseService, state: FSMContext
) -> None:
    """Kurator paneldan manual davomat boshlash — bugungi guruhlar ro'yxati."""
    session = await db.get_curator_session(cb.from_user.id)
    if not session:
        await cb.answer("❌ Avval /curator bilan kiring!", show_alert=True)
        return

    tz        = pytz.timezone(TIMEZONE)
    now       = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    weekday   = now.weekday()

    if weekday == 6:
        await cb.answer("Yakshanba — dars yo'q!", show_alert=True)
        return

    day_type = "ODD" if weekday in (0, 2, 4) else "EVEN"
    schedule = CLASS_SCHEDULE.get(day_type, {})

    if not schedule:
        await cb.answer("Bugun uchun jadval topilmadi!", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for group_name in sorted(schedule.keys()):
        builder.row(InlineKeyboardButton(
            text=f"📚 {group_name}  ({schedule[group_name]})",
            callback_data=f"cur:davomat:{group_name}:{today_str}",
        ))
    builder.row(InlineKeyboardButton(text="◀️ Panel", callback_data="cur:panel"))

    day_label = "Toq" if day_type == "ODD" else "Juft"
    try:
        await cb.message.edit_text(
            f"📋 <b>Davomat yoqlama</b>\n\n"
            f"📅 Sana: {today_str.replace('-', '.')} ({day_label} kun)\n\n"
            f"Guruhni tanlang:",
            reply_markup=builder.as_markup(),
        )
    except TelegramBadRequest:
        await cb.message.answer(
            f"📋 Davomat yoqlama — guruhni tanlang:",
            reply_markup=builder.as_markup(),
        )
    await cb.answer()


# ════════════════════════════════════════════════════════════════════════════════
# O'QUVCHILAR RO'YXATI
# ════════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("cur:list:"))
async def cur_list(cb: CallbackQuery, db: DatabaseService) -> None:
    session = await db.get_curator_session(cb.from_user.id)
    if not session:
        await cb.answer("❌ Avval /curator bilan kiring!", show_alert=True); return

    active_group = cb.data.split(":", 2)[2]
    students     = await db.get_all_students()
    try:
        await cb.message.edit_text(
            "👥 <b>O'quvchilar ro'yxati</b>\n\nO'quvchini tanlang:",
            reply_markup=kb_curator_students(students, MARS_GROUPS, active_group),
        )
    except TelegramBadRequest:
        await cb.message.answer(
            "👥 <b>O'quvchilar ro'yxati</b>",
            reply_markup=kb_curator_students(students, MARS_GROUPS, active_group),
        )
    await cb.answer()


# ════════════════════════════════════════════════════════════════════════════════
# O'QUVCHI BILAN BOG'LANISH
# ════════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("cur:contact:"))
async def cur_contact(cb: CallbackQuery, db: DatabaseService) -> None:
    session = await db.get_curator_session(cb.from_user.id)
    if not session:
        await cb.answer("❌ Avval /curator bilan kiring!", show_alert=True); return

    student_id = int(cb.data.split(":")[2])
    student    = await db.get_student(student_id)
    if not student:
        await cb.answer("❌ O'quvchi topilmadi!", show_alert=True); return

    existing = await db.get_active_curator_chat_by_curator(cb.from_user.id)
    has_chat = existing is not None and existing.student_user_id == student_id
    last = student.last_active.strftime("%d.%m.%Y %H:%M") if student.last_active else "Noma'lum"

    phone = student.phone_number or "—"
    text = (
        f"👤 <b>{student.full_name}</b>\n"
        f"📚 Guruh: <b>{student.group_name}</b>\n"
        f"📱 Telefon: <code>{phone}</code>\n"
        f"💬 Telegram: {student.telegram_username or '—'}\n"
        f"🕐 So'nggi faollik: {last}\n\n"
        f"Bog'lanish usulini tanlang:"
    )
    try:
        await cb.message.edit_text(text, reply_markup=kb_curator_contact(student, has_chat))
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=kb_curator_contact(student, has_chat))
    await cb.answer()


# ════════════════════════════════════════════════════════════════════════════════
# CHAT BOSHLASH
# ════════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("cur:chat_start:"))
async def cur_chat_start(
    cb: CallbackQuery, db: DatabaseService, bot: Bot
) -> None:
    session = await db.get_curator_session(cb.from_user.id)
    if not session:
        await cb.answer("❌ Avval /curator bilan kiring!", show_alert=True); return

    student_id = int(cb.data.split(":")[2])

    # Kuratorning o'zida allaqon faol chat bormi?
    existing = await db.get_active_curator_chat_by_curator(cb.from_user.id)
    if existing:
        other = await db.get_student(existing.student_user_id)
        oname = other.full_name if other else str(existing.student_user_id)
        await cb.answer(
            f"⚠️ Sizda faol chat bor: {oname}\nAvval uni yakunlang.",
            show_alert=True,
        ); return

    # O'quvchi boshqa kurator chatidami?
    if await db.get_active_curator_chat_by_student(student_id):
        await cb.answer("⚠️ Bu o'quvchi hozir boshqa kurator bilan chatda.", show_alert=True)
        return

    student = await db.get_student(student_id)
    if not student:
        await cb.answer("❌ O'quvchi topilmadi!", show_alert=True); return

    await db.start_curator_chat(cb.from_user.id, student_id, session.curator_key)

    cname = _cinfo(session.curator_key).get("full_name", session.curator_key)
    ctg   = _cinfo(session.curator_key).get("telegram_username", "")
    label = f"Kurator {cname}{' ' + ctg if ctg else ''}"

    # O'quvchiga kirish xabari
    try:
        await bot.send_message(
            student_id,
            f"📞 <b>{label}</b> siz bilan aloqaga chiqmoqda.\n"
            f"<i>Mars IT o'quv markazi</i>\n\n"
            f"Javoblaringizni yuboring. Kurator kerakli ma'lumotni olgach chat yopiladi.",
        )
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        await db.end_curator_chat_by_curator(cb.from_user.id)
        await cb.message.answer(
            f"❌ <b>{student.full_name}</b> ga xabar yetkazib bo'lmadi.\n"
            f"O'quvchi botni bloklagan yoki o'chirgan bo'lishi mumkin.\n"
            f"<code>{e}</code>",
        )
        await cb.answer(); return

    try:
        await cb.message.edit_text(
            f"✅ <b>{student.full_name}</b> bilan chat ochildi!\n\n"
            f"📚 Guruh: {student.group_name}\n\n"
            f"Xabarlaringizni yuboring — o'quvchiga boradi.\n\n"
            f"⚠️ <b>Diqqat:</b> «Javobni oldim» tugmasini bossangiz\n"
            f"o'quvchidan boshqa xabar ololmaysiz.\n"
            f"Barcha kerakli ma'lumotni olgach bosing.",
            reply_markup=kb_curator_active_chat(student_id),
        )
    except TelegramBadRequest:
        await cb.message.answer(
            f"✅ Chat ochildi: <b>{student.full_name}</b>",
            reply_markup=kb_curator_active_chat(student_id),
        )
    await cb.answer()
    logger.info(f"Curator chat: {cname} ↔ {student.full_name}")


@router.callback_query(F.data.startswith("cur:resume:"))
async def cur_resume(cb: CallbackQuery, db: DatabaseService) -> None:
    student_id = int(cb.data.split(":")[2])
    student    = await db.get_student(student_id)
    if not student:
        await cb.answer(); return
    try:
        await cb.message.edit_text(
            f"💬 <b>{student.full_name}</b> bilan chat davom etmoqda.\n\nXabarlaringizni yuboring.",
            reply_markup=kb_curator_active_chat(student_id),
        )
    except TelegramBadRequest:
        await cb.message.answer(
            f"💬 Xabarlaringizni yuboring.",
            reply_markup=kb_curator_active_chat(student_id),
        )
    await cb.answer()


# ════════════════════════════════════════════════════════════════════════════════
# RELAY: KURATOR → O'QUVCHI
# (Faqat kuratorda faol chat bo'lganda ishlaydi)
# ════════════════════════════════════════════════════════════════════════════════

@router.message(_CuratorHasActiveChat(), F.chat.type == "private")
async def curator_relay_to_student(
    message: Message, db: DatabaseService, bot: Bot
) -> None:
    session = await db.get_curator_session(message.from_user.id)
    chat    = await db.get_active_curator_chat_by_curator(message.from_user.id)
    student = await db.get_student(chat.student_user_id)
    if not student:
        return

    cname = _cinfo(session.curator_key).get("full_name", session.curator_key)
    ctg   = _cinfo(session.curator_key).get("telegram_username", "")
    label = f"Kurator {cname}{' ' + ctg if ctg else ''}"

    try:
        await bot.send_message(chat.student_user_id, f"💬 <b>{label}:</b>")
        await bot.copy_message(
            chat_id=chat.student_user_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=kb_curator_read(message.from_user.id),
        )
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        await message.answer(
            f"❌ <b>{student.full_name}</b> ga xabar yetkazib bo'lmadi.\n"
            f"O'quvchi botni bloklagan bo'lishi mumkin.\n<code>{e}</code>",
            reply_markup=kb_curator_active_chat(chat.student_user_id),
        )
        return

    await message.answer(
        f"✉️ Xabar <b>{student.full_name}</b> ga yuborildi.",
        reply_markup=kb_curator_active_chat(chat.student_user_id),
    )


# ════════════════════════════════════════════════════════════════════════════════
# RELAY: O'QUVCHI → KURATOR
# (Faqat o'quvchi faol kurator chatida bo'lganda ishlaydi)
# ════════════════════════════════════════════════════════════════════════════════

@router.message(_StudentInCuratorChat(), F.chat.type == "private")
async def student_relay_to_curator(
    message: Message, db: DatabaseService, bot: Bot
) -> None:
    chat    = await db.get_active_curator_chat_by_student(message.from_user.id)
    student = await db.get_student(message.from_user.id)
    sname   = student.full_name if student else str(message.from_user.id)
    sgroup  = student.group_name if student else "—"

    try:
        await bot.send_message(
            chat.curator_telegram_id,
            f"📩 <b>{sname}</b> ({sgroup}) javob berdi:",
        )
        await bot.copy_message(
            chat_id=chat.curator_telegram_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        await bot.send_message(
            chat.curator_telegram_id,
            f"<i>Barcha ma'lumotni oldingizmi? «Javobni oldim» tugmasini bosing.</i>",
            reply_markup=kb_curator_active_chat(message.from_user.id),
        )
    except Exception as e:
        logger.warning(f"Student relay error: {e}")


# ════════════════════════════════════════════════════════════════════════════════
# O'QIDIM TUGMASI (o'quvchi bosadi)
# ════════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("cur_read:"))
async def student_read_curator_msg(
    cb: CallbackQuery, db: DatabaseService, bot: Bot
) -> None:
    curator_tg_id = int(cb.data.split(":")[1])
    student = await db.get_student(cb.from_user.id)
    sname   = student.full_name if student else str(cb.from_user.id)

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await cb.answer("✅ O'qildi.")

    try:
        await bot.send_message(curator_tg_id, f"👁 <b>{sname}</b> xabarni o'qidi.")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════════════════
# JAVOBNI OLDIM — OGOHLANTIRISH VA TASDIQLASH
# ════════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("cur:got_answer:"))
async def cur_got_answer_ask(cb: CallbackQuery, db: DatabaseService) -> None:
    student_id = int(cb.data.split(":")[2])
    student    = await db.get_student(student_id)
    sname      = student.full_name if student else str(student_id)

    await cb.message.answer(
        f"⚠️ <b>Diqqat!</b>\n\n"
        f"«Javobni oldim» tugmasini bossangiz,\n"
        f"<b>{sname}</b> dan boshqa xabar ololmaysiz.\n\n"
        f"<b>Barcha kerakli ma'lumotni olganingizga\n"
        f"ishonch hosil qiling, shundan keyin bosing.</b>",
        reply_markup=kb_curator_confirm_end(student_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("cur:end_confirm:"))
async def cur_end_confirm(
    cb: CallbackQuery, db: DatabaseService, bot: Bot
) -> None:
    session = await db.get_curator_session(cb.from_user.id)
    if not session:
        await cb.answer(); return

    student_id = int(cb.data.split(":")[2])
    student    = await db.get_student(student_id)
    sname      = student.full_name if student else str(student_id)
    cname      = _cinfo(session.curator_key).get("full_name", session.curator_key)

    await db.end_curator_chat_by_curator(cb.from_user.id)

    try:
        await bot.send_message(
            student_id,
            f"✅ <b>Chat yakunlandi.</b>\n\n"
            f"Kurator {cname} bilan suhbat tugatildi.\n"
            f"Agar yana savolingiz bo'lsa, o'qituvchingizga murojaat qiling.",
        )
    except Exception:
        pass

    try:
        await cb.message.edit_text(
            f"✅ Chat yakunlandi: <b>{sname}</b>\n\n"
            f"O'quvchiga «Chat yakunlandi» xabari yuborildi.",
            reply_markup=kb_curator_panel(),
        )
    except TelegramBadRequest:
        await cb.message.answer(
            f"✅ Chat yakunlandi: <b>{sname}</b>", reply_markup=kb_curator_panel()
        )
    await cb.answer()
    logger.info(f"Curator chat yakunlandi: {cname} ↔ {sname}")


@router.callback_query(F.data == "cur:end_cancel")
async def cur_end_cancel(cb: CallbackQuery) -> None:
    try:
        await cb.message.delete()
    except TelegramBadRequest:
        pass
    await cb.answer("Chat davom etmoqda.")


# ════════════════════════════════════════════════════════════════════════════════
# DAVOMAT YOQLAMASI: BELGILASH VA OTA-ONA GURUHIGA YUBORISH
# ════════════════════════════════════════════════════════════════════════════════

class DavomatFSM(StatesGroup):
    marking         = State()  # O'quvchilarni belgilash
    selecting_group = State()  # Ota-ona guruhini tanlash


def _davomat_marks_for_kb(students_data: list[dict]) -> list[dict]:
    return [
        {"full_name": s["full_name"], "present": s["present"], "idx": i}
        for i, s in enumerate(students_data)
    ]


def _davomat_header_text(group_name: str, date_str: str, students_data: list[dict]) -> str:
    present = sum(1 for s in students_data if s["present"])
    absent  = len(students_data) - present
    return (
        f"📋 <b>{group_name}</b> — Davomat yoqlamasi\n"
        f"📅 Sana: {date_str}\n\n"
        f"✅ Keldi: {present}  |  ❌ Kelmadi: {absent}\n\n"
        f"O'quvchilarni belgilang (bosish orqali ✅/❌ almashtiring):"
    )


@router.callback_query(F.data.startswith("cur:davomat:"))
async def start_davomat_marking(
    cb: CallbackQuery, db: DatabaseService, state: FSMContext
) -> None:
    """Yoqlamani to'ldirish — dars boshlanganidan 20 daqiqa o'tgach."""
    session = await db.get_curator_session(cb.from_user.id)
    if not session:
        await cb.answer("❌ Avval /curator bilan kiring!", show_alert=True)
        return

    parts      = cb.data.split(":", 3)   # ["cur", "davomat", "nF-2506", "2026-03-16"]
    group_name = parts[2]
    date_str   = parts[3]

    # MARS_CREDENTIALS dan barcha o'quvchilarni olamiz (ro'yxatdan o'tmaganlar ham)
    from credentials import MARS_CREDENTIALS
    cred_list = [
        (mid, c) for mid, c in MARS_CREDENTIALS.items() if c["group"] == group_name
    ]
    if not cred_list:
        await cb.answer(f"❌ {group_name} guruhida o'quvchilar topilmadi!", show_alert=True)
        return

    # Ro'yxatdan o'tgan o'quvchilarni mars_id bo'yicha topamiz
    registered = await db.get_students_by_group(group_name)
    reg_map = {s.mars_id: s for s in registered if s.mars_id}

    # Bugungi davomatni pre-fill: "yes"→✅, "no"→❌, javob yo'q→✅
    students_data = []
    for mars_id, cred in sorted(cred_list, key=lambda x: x[1]["name"]):
        reg     = reg_map.get(mars_id)
        user_id = reg.user_id if reg else None
        rec     = await db.get_student_attendance(user_id, date_str) if user_id else None
        present = (rec.status == "yes") if rec else True
        students_data.append({"user_id": user_id, "full_name": cred["name"], "present": present})

    await state.set_state(DavomatFSM.marking)
    await state.update_data(group_name=group_name, date_str=date_str, students=students_data)

    text  = _davomat_header_text(group_name, date_str, students_data)
    marks = _davomat_marks_for_kb(students_data)
    try:
        await cb.message.edit_text(text, reply_markup=kb_davomat_mark(marks))
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=kb_davomat_mark(marks))
    await cb.answer()


@router.callback_query(F.data.startswith("cur:tog:"))
async def toggle_student_mark(cb: CallbackQuery, state: FSMContext) -> None:
    """O'quvchi davomatini ✅↔❌ almashtiradi."""
    data          = await state.get_data()
    students_data = data.get("students")
    if not students_data:
        await cb.answer("⚠️ Sessiya tugadi. Qayta bosing.", show_alert=True)
        return

    idx = int(cb.data.split(":")[2])
    if 0 <= idx < len(students_data):
        students_data[idx]["present"] = not students_data[idx]["present"]
        await state.update_data(students=students_data)

    group_name = data.get("group_name", "—")
    date_str   = data.get("date_str", "—")
    text       = _davomat_header_text(group_name, date_str, students_data)
    marks      = _davomat_marks_for_kb(students_data)
    try:
        await cb.message.edit_text(text, reply_markup=kb_davomat_mark(marks))
    except TelegramBadRequest:
        pass
    await cb.answer()


@router.callback_query(F.data == "cur:davomat_send")
async def davomat_choose_group(
    cb: CallbackQuery, db: DatabaseService, state: FSMContext
) -> None:
    """Ota-ona guruhini tanlash sahifasiga o'tish."""
    data = await state.get_data()
    if not data.get("students"):
        await cb.answer("⚠️ Sessiya tugadi. Qayta bosing.", show_alert=True)
        return

    all_groups    = await db.get_all_groups()
    parent_groups = [g for g in all_groups if g.audience == AudienceType.PARENT and g.is_active]

    await state.set_state(DavomatFSM.selecting_group)

    group_name = data.get("group_name", "—")
    text = (
        f"📋 <b>{group_name}</b> — Yoqlama yuborish\n\n"
        f"Qaysi ota-ona guruhiga yuborasiz?"
    )
    try:
        await cb.message.edit_text(text, reply_markup=kb_select_parent_group(parent_groups))
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=kb_select_parent_group(parent_groups))
    await cb.answer()


@router.callback_query(F.data == "cur:davomat_back")
async def davomat_back_to_marking(cb: CallbackQuery, state: FSMContext) -> None:
    """Guruh tanlashdan belgilash sahifasiga qaytish."""
    data          = await state.get_data()
    students_data = data.get("students")
    if not students_data:
        await cb.answer("⚠️ Sessiya tugadi.", show_alert=True)
        await state.clear()
        return

    await state.set_state(DavomatFSM.marking)
    group_name = data.get("group_name", "—")
    date_str   = data.get("date_str", "—")
    text       = _davomat_header_text(group_name, date_str, students_data)
    marks      = _davomat_marks_for_kb(students_data)
    try:
        await cb.message.edit_text(text, reply_markup=kb_davomat_mark(marks))
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=kb_davomat_mark(marks))
    await cb.answer()


@router.callback_query(F.data.startswith("cur:pgroup:"))
async def davomat_send_to_group(
    cb: CallbackQuery, db: DatabaseService, bot: Bot, state: FSMContext
) -> None:
    """Tanlangan ota-ona guruhiga davomat yoqlamasini yuboradi."""
    session = await db.get_curator_session(cb.from_user.id)
    if not session:
        await cb.answer("❌ Avval /curator bilan kiring!", show_alert=True)
        return

    data          = await state.get_data()
    students_data = data.get("students")
    group_name    = data.get("group_name", "—")
    date_str      = data.get("date_str", "—")

    if not students_data:
        await cb.answer("⚠️ Sessiya tugadi.", show_alert=True)
        await state.clear()
        return

    chat_id = int(cb.data.split(":")[2])

    # Kurator ismi
    cname = _cinfo(session.curator_key).get("full_name", session.curator_key)

    # Sanani formatlash: "2026-03-16" → "16.03.2026"
    try:
        y, m, d = date_str.split("-")
        date_formatted = f"{d}.{m}.{y}"
    except Exception:
        date_formatted = date_str

    # Rasmdagidek xabar matni
    lines = [
        f"{cname} | MARS IT",
        f"{date_formatted}",
        "📌Davomat",
        "",
    ]
    for s in students_data:
        emoji = "✅" if s["present"] else "❌"
        lines.append(f"{s['full_name']} {emoji}")
    message_text = "\n".join(lines)

    try:
        await bot.send_message(chat_id, message_text)

        # DB ga ham saqlaymiz (user_id mavjud bo'lganda)
        for s in students_data:
            if s.get("user_id"):
                try:
                    await db.save_attendance(
                        s["user_id"], date_str,
                        "yes" if s["present"] else "no",
                    )
                except Exception as db_err:
                    logger.warning(f"Davomat DB saqlashda xato ({s['full_name']}): {db_err}")

        await state.clear()

        present = sum(1 for s in students_data if s["present"])
        absent  = len(students_data) - present
        try:
            await cb.message.edit_text(
                f"✅ <b>Yoqlama yuborildi!</b>\n\n"
                f"📚 Guruh: <b>{group_name}</b>\n"
                f"📅 Sana: {date_formatted}\n"
                f"✅ Keldi: {present}  |  ❌ Kelmadi: {absent}",
                reply_markup=kb_curator_panel(),
            )
        except TelegramBadRequest:
            await cb.message.answer(
                f"✅ Yoqlama yuborildi! Guruh: {group_name}",
                reply_markup=kb_curator_panel(),
            )
        await cb.answer("✅ Yuborildi!")
        logger.info(f"Davomat yuborildi: {group_name} → {chat_id} | {cname}")

    except Exception as e:
        await cb.answer(f"❌ Yuborib bo'lmadi: {e}", show_alert=True)
        logger.error(f"Davomat yuborishda xato: {e}")


@router.callback_query(F.data == "cur:davomat_cancel")
async def davomat_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    """Davomat to'ldirishni bekor qilish."""
    await state.clear()
    try:
        await cb.message.edit_text(
            "❌ Davomat to'ldirish bekor qilindi.",
            reply_markup=kb_curator_panel(),
        )
    except TelegramBadRequest:
        await cb.message.answer("❌ Bekor qilindi.", reply_markup=kb_curator_panel())
    await cb.answer()


# ════════════════════════════════════════════════════════════════════════════════
# KECHIKKAN O'QUVCHI — DAVOMATNI O'ZGARTIRISH
# ════════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("cur:att_update:"))
async def cur_att_update(
    cb: CallbackQuery, db: DatabaseService, bot: Bot
) -> None:
    """
    cur:att_update:USER_ID:DATE:STATUS
    Kurator kechikkan o'quvchining davomatini o'zgartiradi.
    """
    session = await db.get_curator_session(cb.from_user.id)
    if not session:
        await cb.answer("❌ Avval /curator bilan kiring!", show_alert=True)
        return

    parts      = cb.data.split(":", 4)  # ["cur", "att_update", uid, date, status]
    user_id    = int(parts[2])
    date_str   = parts[3]
    new_status = parts[4]  # "yes" | "no"

    student = await db.get_student(user_id)
    if not student:
        await cb.answer("❌ O'quvchi topilmadi!", show_alert=True)
        return

    old_emoji = "❌" if new_status == "yes" else "✅"
    new_emoji = "✅" if new_status == "yes" else "❌"

    await db.save_attendance(user_id, date_str, new_status)

    cname = _cinfo(session.curator_key).get("full_name", session.curator_key)
    notify = (
        f"✏️ <b>Davomat o'zgartirildi</b>\n\n"
        f"👤 {student.full_name} ({student.group_name})\n"
        f"📅 Sana: {date_str}\n"
        f"{old_emoji} → {new_emoji}\n"
        f"👩‍💼 Kurator: {cname}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, notify)
        except Exception:
            pass

    try:
        from sqlalchemy import select
        from database import CuratorSession
        async with db.session_factory() as db_sess:
            result = await db_sess.execute(select(CuratorSession))
            curator_sessions = list(result.scalars().all())
        for cs in curator_sessions:
            if cs.telegram_id != cb.from_user.id and cs.telegram_id not in ADMIN_IDS:
                try:
                    await bot.send_message(cs.telegram_id, notify)
                except Exception:
                    pass
    except Exception:
        pass

    await cb.answer(f"✅ Davomat o'zgartirildi: {new_emoji}", show_alert=True)
    logger.info(
        f"Davomat o'zgartirildi: {student.full_name} | {date_str} | "
        f"{old_emoji}→{new_emoji} | Kurator: {cname}"
    )
