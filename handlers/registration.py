"""
handlers/registration.py — O'quvchilar ro'yxatdan o'tish jarayoni (FSM).

Qadamlar:
  1. Guruhni tanlash (inline keyboard)
  2. Mars Space ID kiritish
  3. Parol kiritish → tekshirish → ro'yxatga olish
"""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS
from credentials import MARS_CREDENTIALS, MARS_GROUPS
from database import DatabaseService
from keyboards import kb_mars_groups, kb_student_menu

logger = logging.getLogger(__name__)
router = Router()


class RegFSM(StatesGroup):
    waiting_group    = State()
    waiting_mars_id  = State()
    waiting_password = State()
    waiting_phone    = State()


def _is_valid_phone(phone: str) -> bool:
    """Telefon formati: +998XXXXXXXXX (jami 13 belgi, 12 raqam)."""
    import re
    return bool(re.fullmatch(r"\+998\d{9}", phone))


async def start_registration(message: Message, state: FSMContext) -> None:
    """commands.py /start dan chaqiriladi — ro'yxatdan o'tishni boshlaydi."""
    await state.set_state(RegFSM.waiting_group)
    await message.answer(
        "🎓 <b>Mars IT O'quv Markaziga xush kelibsiz!</b>\n\n"
        "Ro'yxatdan o'tish — 3 qadam:\n"
        "1️⃣ Guruhni tanlash\n"
        "2️⃣ Mars Space ID va parol\n"
        "3️⃣ Telefon raqam\n\n"
        "📚 <b>1/3 — Guruhingizni tanlang:</b>",
        reply_markup=kb_mars_groups(MARS_GROUPS),
    )


# ── 1-qadam: guruh tanlash ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("reg:group:"), StateFilter(RegFSM.waiting_group))
async def reg_select_group(cb: CallbackQuery, state: FSMContext) -> None:
    group = cb.data.split(":", 2)[2]
    await state.update_data(group=group)
    await state.set_state(RegFSM.waiting_mars_id)
    await cb.message.edit_text(
        f"<b>2/3 — Mars Space ID</b>\n\n"
        f"✅ Guruh: <b>{group}</b>\n\n"
        f"🔑 Mars Space ID raqamingizni kiriting:\n"
        f"<i>(Masalan: 1342455)</i>",
    )
    await cb.answer()


# ── 2-qadam: Mars ID kiritish ──────────────────────────────────────────────────

@router.message(StateFilter(RegFSM.waiting_mars_id))
async def reg_enter_mars_id(message: Message, state: FSMContext) -> None:
    raw    = message.text.strip() if message.text else ""
    upper  = raw.upper()
    is_num = raw.isdigit()
    is_p   = upper.startswith("P") and len(upper) >= 2 and upper[1:].isdigit()
    mars_id = upper if is_p else raw

    if not (is_num or is_p):
        await message.answer(
            "❌ <b>Noto'g'ri format!</b>\n\n"
            "Mars Space ID faqat raqamlardan iborat bo'lishi kerak.\n"
            "Masalan: <code>1342455</code>\n\n"
            "Qayta kiriting:"
        )
        return
    await state.update_data(mars_id=mars_id)
    await state.set_state(RegFSM.waiting_password)
    await message.answer("🔐 <b>3/3 — Mars Space parolingizni</b> kiriting:")


# ── 3-qadam: parol → tekshirish → ro'yxatga olish ─────────────────────────────

@router.message(StateFilter(RegFSM.waiting_password))
async def reg_enter_password(
    message: Message,
    state: FSMContext,
    db: DatabaseService,
    bot: Bot,
) -> None:
    password  = message.text.strip() if message.text else ""
    data      = await state.get_data()
    mars_id   = data.get("mars_id", "")
    sel_group = data.get("group", "")

    # Avval statik ro'yxatdan, so'ng DB dan tekshiramiz
    cred = MARS_CREDENTIALS.get(mars_id)
    if not cred:
        db_cred = await db.get_student_credential(mars_id)
        if db_cred:
            cred = {"password": db_cred.password, "name": db_cred.name, "group": db_cred.group_name}

    if not cred:
        await message.answer(
            "❌ <b>Bu ID topilmadi!</b>\n\n"
            "Mars Space ID raqamingizni tekshiring va qayta kiriting:",
        )
        await state.set_state(RegFSM.waiting_mars_id)
        return

    if cred["password"] != password:
        await message.answer(
            "❌ <b>Parol noto'g'ri!</b>\n\n"
            "Parolni tekshirib qayta kiriting:",
        )
        return

    if cred["group"] != sel_group:
        await message.answer(
            f"❌ <b>Guruh mos kelmadi!</b>\n\n"
            f"Siz <b>{sel_group}</b> guruhini tanladingiz,\n"
            f"lekin sizning guruhingiz <b>{cred['group']}</b>.\n\n"
            f"To'g'ri guruhingizni tanlang:",
            reply_markup=kb_mars_groups(MARS_GROUPS),
        )
        await state.set_state(RegFSM.waiting_group)
        return

    # ── Bu mars_id boshqa Telegram akkountga bog'liqmi? ──────────────────────
    existing = await db.get_student_by_mars_id(mars_id)
    if existing and existing.user_id != message.from_user.id:
        await message.answer(
            "⚠️ <b>Bu ID allaqachon ro'yxatdan o'tilgan!</b>\n\n"
            "Ushbu Mars Space ID boshqa Telegram akkountga bog'liq.\n\n"
            "Agar bu sizning ID ingiz bo'lsa, admin bilan bog'laning.",
        )
        await state.clear()
        return

    # ── Ma'lumotlarni saqlab, telefon so'raymiz ─────────────────────────────
    await state.update_data(
        full_name=cred["name"],
        confirmed_group=sel_group,
        confirmed_mars_id=mars_id,
    )
    await state.set_state(RegFSM.waiting_phone)
    await message.answer(
        f"✅ <b>Parol to'g'ri!</b>\n\n"
        f"📱 Shaxsiy <b>telefon raqamingizni</b> kiriting:\n\n"
        f"Namuna: <code>+998901234567</code>\n"
        f"<i>(+998 dan boshlang, jami 12 raqam)</i>",
    )


# ── 4-qadam: telefon raqam → ro'yxatga olish ──────────────────────────────────

@router.message(StateFilter(RegFSM.waiting_phone))
async def reg_enter_phone(
    message: Message,
    state: FSMContext,
    db: DatabaseService,
    bot: Bot,
) -> None:
    phone = message.text.strip() if message.text else ""

    if not _is_valid_phone(phone):
        await message.answer(
            "❌ <b>Noto'g'ri telefon raqami!</b>\n\n"
            "Format: <code>+998901234567</code>\n"
            "<i>+998 dan boshlang, keyin 9 ta raqam kiriting (jami 12 raqam).</i>\n\n"
            "Qayta kiriting:"
        )
        return

    data      = await state.get_data()
    full_name = data.get("full_name", "")
    sel_group = data.get("confirmed_group", "")
    mars_id   = data.get("confirmed_mars_id", "")
    user      = message.from_user
    tg_user   = f"@{user.username}" if user.username else str(user.id)

    await db.register_student(
        user_id=user.id,
        telegram_username=tg_user,
        full_name=full_name,
        mars_id=mars_id,
        group_name=sel_group,
        phone_number=phone,
    )
    await state.clear()

    await message.answer(
        f"✅ <b>Salom, {full_name}!</b>\n\n"
        f"Siz muvaffaqiyatli ro'yxatdan o'tdingiz! 🎉\n"
        f"📚 Guruh: <b>{sel_group}</b>\n"
        f"📱 Telefon: <code>{phone}</code>\n\n"
        f"Quyidagi tugmalardan foydalaning:",
        reply_markup=kb_student_menu(),
    )

    # ── Adminga bildirishnoma ────────────────────────────────────────────────
    admin_text = (
        f"🔔 <b>Yangi o'quvchi ro'yxatdan o'tdi!</b>\n\n"
        f"👤 Ism: <b>{full_name}</b>\n"
        f"📚 Guruh: <b>{sel_group}</b>\n"
        f"🆔 Mars ID: <code>{mars_id}</code>\n"
        f"📱 Telefon: <code>{phone}</code>\n"
        f"💬 Telegram: {tg_user}\n"
        f"🔗 User ID: <code>{user.id}</code>"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text)
        except Exception as e:
            logger.warning(f"Admin {admin_id} ga yuborib bo'lmadi: {e}")
