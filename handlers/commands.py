"""
handlers/commands.py — Bot buyruqlari ishlovchilari.

Barcha admin buyruqlar endi inline keyboard bilan ishlaydi.
"""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import ChatMemberUpdated, Message

from config import ADMIN_IDS, SEND_HOUR, SEND_MINUTE, TIMEZONE
from database import DatabaseService, GroupType
from handlers.pending import pending_groups
from keyboards import kb_admin_panel, kb_back_to_panel, kb_group_list, kb_quick_add, kb_student_menu
from scheduler import get_tomorrow_info, send_daily_reminders

logger = logging.getLogger(__name__)
router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ─── /start ───────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db: DatabaseService) -> None:
    """
    Xush kelibsiz:
      Admin      → admin panel
      Ro'yxatdan o'tgan o'quvchi → o'quvchi paneli
      Yangi foydalanuvchi       → ro'yxatdan o'tish
    """
    from aiogram.fsm.context import FSMContext  # noqa — already imported via type hint
    await state.clear()  # Avvalgi FSM holatini tozalaymiz

    user_id = message.from_user.id

    if _is_admin(user_id):
        await message.answer(
            f"👋 <b>Assalomu alaykum, Admin!</b>\n\n"
            f"Men — O'quv markaz dars eslatmasi boti.\n\n"
            f"⏰ Har kuni soat <b>{SEND_HOUR:02d}:{SEND_MINUTE:02d}</b> da "
            f"ertangi dars haqida tegishli guruhlarga xabar yuboraman.\n\n"
            f"📅 <b>Qanday ishlaydi?</b>\n"
            f"  • Toq kun → Toq guruhlariga\n"
            f"  • Juft kun → Juft guruhlariga\n\n"
            f"Quyidagi paneldan boshqaruvingizni amalga oshiring:",
            reply_markup=kb_admin_panel(),
        )
        return

    # Ro'yxatdan o'tgan o'quvchimi?
    student = await db.get_student(user_id)
    if student:
        await db.update_last_active(user_id)
        await message.answer(
            f"👋 <b>Salom, {student.full_name}!</b>\n\n"
            f"📚 Guruh: <b>{student.group_name}</b>\n\n"
            f"Quyidagi tugmalardan foydalaning:",
            reply_markup=kb_student_menu(),
        )
        return

    # Yangi foydalanuvchi — ro'yxatdan o'tish
    from handlers.registration import start_registration
    await start_registration(message, state)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await cmd_start(message)


# ─── /panel — admin panelini ko'rsatish ──────────────────────────────────────

@router.message(Command("panel"))
async def cmd_panel(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("❌ Bu buyruq faqat adminlar uchun!")
        return
    await message.answer(
        "🎛 <b>Admin Panel</b>\n\nAmal tanlang:",
        reply_markup=kb_admin_panel(),
    )


# ─── /list_groups ─────────────────────────────────────────────────────────────

@router.message(Command("list_groups"))
async def cmd_list_groups(message: Message, db: DatabaseService) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("❌ Bu buyruq faqat adminlar uchun!")
        return

    groups = await db.get_all_groups()
    if not groups:
        await message.answer(
            "📭 <b>Guruhlar yo'q</b>\n\nGuruh qo'shish uchun paneldan foydalaning.",
            reply_markup=kb_admin_panel(),
        )
        return

    odd   = sum(1 for g in groups if g.group_type == GroupType.ODD)
    even  = sum(1 for g in groups if g.group_type == GroupType.EVEN)
    activ = sum(1 for g in groups if g.is_active)

    await message.answer(
        f"📋 <b>Guruhlar ro'yxati</b>\n\n"
        f"Jami: <b>{len(groups)}</b> ta ({activ} aktiv)\n"
        f"Toq: <b>{odd}</b> ta | Juft: <b>{even}</b> ta\n\n"
        f"Batafsil ko'rish uchun guruhni tanlang:",
        reply_markup=kb_group_list(groups),
    )


# ─── /add — qo'lda guruh qo'shish (skript/power-user uchun) ─────────────────

@router.message(Command("add"))
async def cmd_add(message: Message, db: DatabaseService) -> None:
    """
    Agar argumentsiz chaqirilsa — panelga yo'naltiradi.
    Argumentlar bilan: /add -100... Nom toq|juft
    """
    if not _is_admin(message.from_user.id):
        await message.answer("❌ Bu buyruq faqat adminlar uchun!")
        return

    parts = message.text.split(maxsplit=3)

    if len(parts) < 4:
        await message.answer(
            "ℹ️ Guruh qo'shish uchun quyidagi paneldan foydalaning:",
            reply_markup=kb_admin_panel(),
        )
        return

    try:
        chat_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Chat ID noto'g'ri! Raqam bo'lishi kerak.")
        return

    name     = parts[2]
    type_raw = parts[3].lower().strip()

    if type_raw in ("toq", "odd", "t"):
        group_type  = GroupType.ODD
        type_label  = "Toq kunliklar"
    elif type_raw in ("juft", "even", "j"):
        group_type  = GroupType.EVEN
        type_label  = "Juft kunliklar"
    else:
        await message.answer("❌ Tur noto'g'ri! 'toq' yoki 'juft' kiriting.")
        return

    try:
        group = await db.add_group(chat_id=chat_id, name=name, group_type=group_type)
        await message.answer(
            f"✅ <b>Guruh qo'shildi!</b>\n\n"
            f"📌 Nomi: <b>{group.name}</b>\n"
            f"🆔 Chat ID: <code>{group.chat_id}</code>\n"
            f"📋 Tur: {type_label}",
            reply_markup=kb_back_to_panel(),
        )
    except Exception as e:
        await message.answer(f"❌ Xatolik: <code>{e}</code>")


# ─── /remove ──────────────────────────────────────────────────────────────────

@router.message(Command("remove"))
async def cmd_remove(message: Message, db: DatabaseService) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("❌ Bu buyruq faqat adminlar uchun!")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "❌ Format: <code>/remove -100...</code>\n\n"
            "Yoki paneldan foydalaning:",
            reply_markup=kb_admin_panel(),
        )
        return

    try:
        chat_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Chat ID noto'g'ri!")
        return

    success = await db.remove_group(chat_id)
    if success:
        await message.answer(
            f"✅ Guruh o'chirildi: <code>{chat_id}</code>",
            reply_markup=kb_back_to_panel(),
        )
    else:
        await message.answer(f"❌ Bunday guruh topilmadi: <code>{chat_id}</code>")


# ─── /status ──────────────────────────────────────────────────────────────────

@router.message(Command("status"))
async def cmd_status(message: Message, db: DatabaseService) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("❌ Bu buyruq faqat adminlar uchun!")
        return

    groups = await db.get_all_groups()
    info   = get_tomorrow_info(TIMEZONE)

    odd_active  = sum(1 for g in groups if g.group_type == GroupType.ODD  and g.is_active)
    even_active = sum(1 for g in groups if g.group_type == GroupType.EVEN and g.is_active)
    next_type   = "Toq" if info.group_type == GroupType.ODD else "Juft"

    await message.answer(
        f"📊 <b>Bot holati</b>\n\n"
        f"<b>Guruhlar:</b>\n"
        f"  Jami: {len(groups)} ta\n"
        f"  Toq: {odd_active} aktiv | Juft: {even_active} aktiv\n\n"
        f"<b>Keyingi yuborish:</b>\n"
        f"  📅 {info.date_str} — {info.weekday_uz}\n"
        f"  {next_type} guruhlarga xabar ketadi\n\n"
        f"<b>Sozlamalar:</b>\n"
        f"  ⏰ {SEND_HOUR:02d}:{SEND_MINUTE:02d} | 🌍 {TIMEZONE}",
        reply_markup=kb_back_to_panel(),
    )


# ─── /test_send ───────────────────────────────────────────────────────────────

@router.message(Command("test_send"))
async def cmd_test_send(message: Message, bot: Bot, db: DatabaseService) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("❌ Bu buyruq faqat adminlar uchun!")
        return

    info      = get_tomorrow_info(TIMEZONE)
    next_type = "Toq" if info.group_type == GroupType.ODD else "Juft"
    sent_msg  = await message.answer(
        f"⏳ <b>Test yuborilmoqda...</b>\n"
        f"📅 {info.date_str} — {next_type} kun"
    )

    try:
        await send_daily_reminders(bot=bot, db=db, timezone_str=TIMEZONE)
        await sent_msg.edit_text(
            f"✅ <b>Test muvaffaqiyatli!</b>\n\n"
            f"📅 {info.date_str} — {next_type} kun uchun yuborildi.",
            reply_markup=kb_back_to_panel(),
        )
    except Exception as e:
        await sent_msg.edit_text(
            f"❌ <b>Xatolik:</b> <code>{e}</code>",
            reply_markup=kb_back_to_panel(),
        )


# ─── /chatid — guruh ichida chat ID ni ko'rsatish ────────────────────────────

@router.message(Command("chatid"))
async def cmd_chatid(message: Message, db: DatabaseService) -> None:
    """
    Guruh ichida → shu guruhning Chat ID sini ko'rsatadi va saqlaydi.
    Private chatda → saqlanган barcha guruhlar ro'yxatini ko'rsatadi.
    Private chatda forward bilan → forward qilingan guruhning ID sini ko'rsatadi.
    """
    chat     = message.chat
    is_group = chat.type in ("group", "supergroup")

    if is_group:
        title = chat.title or "Noma'lum guruh"
        # Guruhni avtomatik saqlaymiz
        await db.save_bot_chat(chat.id, title)
        await message.reply(
            f"🆔 <b>Guruh Chat ID si:</b>\n\n"
            f"📌 Guruh: <b>{title}</b>\n"
            f"🔢 Chat ID: <code>{chat.id}</code>\n\n"
            f"⬆️ Yuqoridagi raqamni admin panelga kiriting."
        )
        return

    # Private chat
    if not _is_admin(message.from_user.id):
        await message.answer(
            f"🆔 <b>Sizning ID ingiz:</b> <code>{message.from_user.id}</code>"
        )
        return

    # Forward qilingan xabar — guruh ID sini aniqlaymiz
    fwd = message.forward_from_chat
    if fwd and fwd.type in ("group", "supergroup", "channel"):
        title = fwd.title or "Noma'lum"
        await db.save_bot_chat(fwd.id, title)
        await message.answer(
            f"🆔 <b>Forward guruh/kanal:</b>\n\n"
            f"📌 Nom: <b>{title}</b>\n"
            f"🔢 Chat ID: <code>{fwd.id}</code>\n\n"
            f"✅ Saqlandi."
        )
        return

    # Barcha saqlangan guruhlarni ko'rsatamiz
    chats = await db.get_bot_chats()
    if not chats:
        await message.answer(
            f"📭 <b>Hali hech bir guruh saqlanmagan.</b>\n\n"
            f"Guruh Chat ID sini olish uchun:\n"
            f"1️⃣ Har bir guruhda <code>/chatid</code> yozing\n"
            f"2️⃣ <b>YOKI</b> guruhdan istalgan xabarni shu botga <b>forward</b> qiling"
        )
        return

    lines = "\n".join(f"  <code>{c.chat_id}</code>  —  {c.title}" for c in chats)
    await message.answer(
        f"📋 <b>Saqlangan guruhlar ({len(chats)} ta):</b>\n\n"
        f"{lines}\n\n"
        f"Admin paneldan ➕ Qo'shish orqali qo'shishingiz mumkin."
    )


# ─── Bot guruhga qo'shilganda avtomatik chat ID yuborish ─────────────────────

# ─── Guruhdan kelgan istalgan xabar → chat ID saqlanadi ─────────────────────

@router.message(F.chat.type.in_({"group", "supergroup"}))
async def auto_save_group(message: Message, db: DatabaseService) -> None:
    """Bot a'zo bo'lgan guruhdan xabar kelsa — chat ID avtomatik saqlanadi."""
    await db.save_bot_chat(message.chat.id, message.chat.title or str(message.chat.id))


# ─── Bot guruhga qo'shilganda avtomatik chat ID yuborish ─────────────────────

@router.my_chat_member(F.new_chat_member.status.in_({"left", "kicked", "banned"}))
async def bot_removed_from_group(event: ChatMemberUpdated, db: DatabaseService) -> None:
    """Bot guruhdan chiqarilganda bot_chats dan o'chiriladi."""
    chat = event.chat
    if chat.type not in ("group", "supergroup"):
        return
    await db.remove_bot_chat(chat.id)
    logger.info(f"Bot guruhdan chiqarildi: '{chat.title}' ({chat.id})")


@router.my_chat_member(F.new_chat_member.status.in_({"member", "administrator"}))
async def bot_added_to_group(event: ChatMemberUpdated, bot: Bot, db: DatabaseService) -> None:
    """
    Bot guruhga qo'shilganda:
    1. Guruhni pending_groups ga saqlaymiz
    2. Barcha adminlarga tugmali xabar yuboramiz
    Admin 2 ta click bilan guruhni ro'yxatga qo'sha oladi.
    """
    chat     = event.chat
    is_group = chat.type in ("group", "supergroup")
    if not is_group:
        return

    title = chat.title or f"Guruh {chat.id}"

    # DB ga saqlaymiz (doimiy) + vaqtinchalik xotirada ham
    await db.save_bot_chat(chat.id, title)
    pending_groups[chat.id] = title

    text = (
        f"🔔 <b>Bot yangi guruhga qo'shildi!</b>\n\n"
        f"📌 Guruh: <b>{title}</b>\n"
        f"🆔 Chat ID: <code>{chat.id}</code>\n\n"
        f"Bu guruhni dars eslatmasi ro'yxatiga qo'shishni xohlaysizmi?\n"
        f"<i>(Guruh nomi sifatida <b>{title}</b> ishlatiladi)</i>"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=text,
                reply_markup=kb_quick_add(chat.id),
            )
            logger.info(f"Quick-add xabari yuborildi → admin {admin_id}: '{title}' ({chat.id})")
        except Exception as e:
            logger.warning(f"Admin {admin_id} ga yuborib bo'lmadi: {e}")
