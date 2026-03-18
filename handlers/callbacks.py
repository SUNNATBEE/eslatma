"""
handlers/callbacks.py — Inline tugmalar va FSM ishlovchilari.
"""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS, SEND_HOUR, SEND_MINUTE, TIMEZONE
from database import AudienceType, DatabaseService, GroupType
from handlers.pending import pending_groups
from keyboards import (
    kb_admin_panel, kb_back_to_panel, kb_cancel_fsm,
    kb_choose_audience, kb_choose_type, kb_confirm_delete,
    kb_group_actions, kb_group_list, kb_group_selector,
)
from scheduler import (
    build_reminder_message, get_tomorrow_info,
    send_daily_reminders, send_leaderboard_broadcast,
)
from config import WEBAPP_URL
from utils import safe_edit, safe_edit_markup

logger = logging.getLogger(__name__)
router = Router()


# ─── Yordamchi ────────────────────────────────────────────────────────────────

def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _group_card(group) -> str:
    """Guruh haqida chiroyli matn."""
    status  = "🟢 Aktiv" if group.is_active else "🔴 Nofaol"
    kind    = "Toq kunliklar" if group.group_type == GroupType.ODD else "Juft kunliklar"
    aud     = "👨‍👩‍👧 Ota-onalar" if group.audience == AudienceType.PARENT else "🎓 O'quvchilar"
    msg_str = f"<code>{group.last_message_id}</code>" if group.last_message_id else "yo'q"
    return (
        f"<b>📌 {group.name}</b>\n\n"
        f"🆔 Chat ID: <code>{group.chat_id}</code>\n"
        f"📋 Jadval: {kind}\n"
        f"👥 Auditoriya: {aud}\n"
        f"⚡️ Holat: {status}\n"
        f"💬 Oxirgi xabar ID: {msg_str}\n\n"
        f"Amalni tanlang:"
    )


# ─── FSM holatlari ────────────────────────────────────────────────────────────

class AddGroupFSM(StatesGroup):
    waiting_chat_id  = State()   # 1-qadam (qo'lda)
    waiting_name     = State()   # 2-qadam (qo'lda)
    waiting_type     = State()   # 3-qadam (inline)
    waiting_audience = State()   # 4-qadam (inline)


class BulkAddFSM(StatesGroup):
    """Bir nechta guruhni bir vaqtda qo'shish."""
    selecting_groups = State()   # Multi-select
    waiting_type     = State()   # Jadval turi
    waiting_audience = State()   # Auditoriya


# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN PANEL
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin:panel")
async def cb_admin_panel(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    await safe_edit(callback.message, 
        "🎛 <b>Admin Panel</b>\n\nAmal tanlang:",
        reply_markup=kb_admin_panel(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:list:"))
async def cb_admin_list(callback: CallbackQuery, db: DatabaseService) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    active_filter = callback.data.split(":")[2]  # all | parent | student
    groups        = await db.get_all_groups()

    parent_count  = sum(1 for g in groups if g.audience == AudienceType.PARENT)
    student_count = sum(1 for g in groups if g.audience == AudienceType.STUDENT)
    active        = sum(1 for g in groups if g.is_active)

    filter_labels = {"all": "Hammasi", "parent": "👨‍👩‍👧 Ota-onalar", "student": "🎓 O'quvchilar"}
    label = filter_labels.get(active_filter, "Hammasi")

    if not groups:
        await safe_edit(callback.message, 
            "📭 <b>Guruhlar yo'q</b>\n\nGuruh qo'shish uchun ➕ ni bosing.",
            reply_markup=kb_admin_panel(),
        )
        await callback.answer()
        return

    text = (
        f"📋 <b>Guruhlar — {label}</b>\n\n"
        f"Jami: <b>{len(groups)}</b> ta ({active} aktiv)\n"
        f"👨‍👩‍👧 Ota-onalar: <b>{parent_count}</b> | "
        f"🎓 O'quvchilar: <b>{student_count}</b>\n\n"
        f"Guruhni tanlang:"
    )
    await safe_edit(callback.message, 
        text, reply_markup=kb_group_list(groups, active_filter)
    )
    await callback.answer()


@router.callback_query(F.data == "admin:status")
async def cb_admin_status(callback: CallbackQuery, db: DatabaseService) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    groups    = await db.get_all_groups()
    info      = get_tomorrow_info(TIMEZONE)
    next_type = "Toq" if info.group_type == GroupType.ODD else "Juft"

    odd_active  = sum(1 for g in groups if g.group_type == GroupType.ODD  and g.is_active)
    even_active = sum(1 for g in groups if g.group_type == GroupType.EVEN and g.is_active)

    await safe_edit(callback.message, 
        f"📊 <b>Bot holati</b>\n\n"
        f"<b>Guruhlar:</b>\n"
        f"  Jami: {len(groups)} ta\n"
        f"  📌 Toq kunliklar: {odd_active} aktiv\n"
        f"  📎 Juft kunliklar: {even_active} aktiv\n\n"
        f"<b>Keyingi yuborish:</b>\n"
        f"  📅 {info.date_str} — {info.weekday_uz}\n"
        f"  ➡️ {next_type} guruhlarga xabar ketadi\n\n"
        f"<b>Sozlamalar:</b>\n"
        f"  ⏰ {SEND_HOUR:02d}:{SEND_MINUTE:02d} | 🌍 {TIMEZONE}",
        reply_markup=kb_back_to_panel(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:test_send")
async def cb_admin_test_send(callback: CallbackQuery, bot: Bot, db: DatabaseService) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    info      = get_tomorrow_info(TIMEZONE)
    next_type = "Toq" if info.group_type == GroupType.ODD else "Juft"

    await safe_edit(callback.message, 
        f"⏳ <b>Barcha guruhlarga test yuborilmoqda...</b>\n"
        f"📅 {info.date_str} ({next_type} kun) | Kutib turing..."
    )
    await callback.answer()

    try:
        await send_daily_reminders(bot=bot, db=db, timezone_str=TIMEZONE)
        await safe_edit(callback.message, 
            f"✅ <b>Test muvaffaqiyatli!</b>\n\n"
            f"📅 {info.date_str} — {next_type} kun\n"
            f"👨‍👩‍👧 Ota-onalarga alohida xabar\n"
            f"🎓 O'quvchilarga alohida xabar yuborildi.",
            reply_markup=kb_back_to_panel(),
        )
    except Exception as e:
        logger.error(f"Test xatosi: {e}")
        await safe_edit(callback.message, 
            f"❌ <b>Xatolik:</b>\n<code>{e}</code>",
            reply_markup=kb_back_to_panel(),
        )


# ─── Test: Reyting broadcast ──────────────────────────────────────────────────

@router.callback_query(F.data == "admin:test_leaderboard")
async def cb_admin_test_leaderboard(callback: CallbackQuery, bot: Bot, db: DatabaseService) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True); return
    await callback.answer()
    await safe_edit(callback.message, "⏳ <b>Reyting broadcast test qilinmoqda...</b>")
    try:
        await send_leaderboard_broadcast(bot=bot, db=db, webapp_url=WEBAPP_URL, timezone_str=TIMEZONE)
        await safe_edit(callback.message,
            "✅ <b>Reyting broadcast muvaffaqiyatli yuborildi!</b>\n"
            "Barcha aktiv guruhlarga top-5 reyting xabari ketdi.",
            reply_markup=kb_back_to_panel(),
        )
    except Exception as e:
        await safe_edit(callback.message,
            f"❌ <b>Xatolik:</b>\n<code>{e}</code>",
            reply_markup=kb_back_to_panel(),
        )


# ─── Dublikat o'quvchilarni tozalash ─────────────────────────────────────────

@router.callback_query(F.data == "admin:cleanup_duplicates")
async def cb_admin_cleanup_dupes(callback: CallbackQuery, db: DatabaseService) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True); return
    await callback.answer()
    await safe_edit(callback.message, "⏳ Dublikat o'quvchilar qidirilmoqda...")
    dupes = await db.find_duplicate_students()
    if not dupes:
        await safe_edit(callback.message,
            "✅ <b>Dublikat topilmadi!</b>\nBarcha o'quvchilar yagona.",
            reply_markup=kb_back_to_panel(),
        )
        return
    deleted = 0
    details = []
    for keep, remove in dupes:
        details.append(
            f"🗑 <b>{remove.full_name}</b> ({remove.group_name}) "
            f"— Lv.{remove.level} {remove.xp} XP o'chirildi"
        )
        await db.delete_student_by_id(remove.id)
        deleted += 1
    detail_text = "\n".join(details[:10])
    await safe_edit(callback.message,
        f"🧹 <b>{deleted} ta dublikat o'chirildi!</b>\n\n{detail_text}",
        reply_markup=kb_back_to_panel(),
    )


# ─── Barcha xabarlarni o'chirish ──────────────────────────────────────────────

@router.callback_query(F.data == "admin:delete_all_msgs")
async def cb_delete_all_msgs(callback: CallbackQuery, bot: Bot, db: DatabaseService) -> None:
    """Barcha guruhlardan oxirgi yuborilgan xabarlarni o'chirish."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    groups = await db.get_groups_with_message()
    if not groups:
        await callback.answer("📭 O'chiriladigan xabar yo'q!", show_alert=True)
        return

    await safe_edit(callback.message, 
        f"⏳ <b>{len(groups)} ta guruhdan xabar o'chirilmoqda...</b>"
    )
    await callback.answer()

    ok, fail, already = 0, 0, 0

    for group in groups:
        try:
            await bot.delete_message(
                chat_id=group.chat_id,
                message_id=group.last_message_id,
            )
            await db.clear_message_id(group.chat_id)
            ok += 1
            logger.info(f"Xabar o'chirildi: '{group.name}' msg_id={group.last_message_id}")
        except Exception as e:
            err = str(e).lower()
            if "message to delete not found" in err or "message can't be deleted" in err:
                await db.clear_message_id(group.chat_id)
                already += 1
            else:
                fail += 1
                logger.error(f"O'chirishda xato '{group.name}': {e}")

    result_text = (
        f"🗑 <b>Xabarlar o'chirildi!</b>\n\n"
        f"✅ Muvaffaqiyatli: {ok} ta\n"
    )
    if already:
        result_text += f"⚠️ Avval o'chirilgan: {already} ta\n"
    if fail:
        result_text += f"❌ Xato: {fail} ta\n"

    await safe_edit(callback.message, result_text, reply_markup=kb_back_to_panel())


# ═══════════════════════════════════════════════════════════════════════════════
#  GURUH AMALLARI
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("group:detail:"))
async def cb_group_detail(callback: CallbackQuery, db: DatabaseService) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    chat_id = int(callback.data.split(":")[2])
    group   = await db.get_group_by_chat_id(chat_id)
    if not group:
        await callback.answer("❌ Guruh topilmadi!", show_alert=True)
        return

    await safe_edit(callback.message, _group_card(group), reply_markup=kb_group_actions(group))
    await callback.answer()


@router.callback_query(F.data.startswith("group:on:"))
async def cb_group_on(callback: CallbackQuery, db: DatabaseService) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    chat_id = int(callback.data.split(":")[2])
    await db.set_group_active(chat_id, True)
    group = await db.get_group_by_chat_id(chat_id)
    await safe_edit(callback.message, _group_card(group), reply_markup=kb_group_actions(group))
    await callback.answer("🟢 Aktiv qilindi!")


@router.callback_query(F.data.startswith("group:off:"))
async def cb_group_off(callback: CallbackQuery, db: DatabaseService) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    chat_id = int(callback.data.split(":")[2])
    await db.set_group_active(chat_id, False)
    group = await db.get_group_by_chat_id(chat_id)
    await safe_edit(callback.message, _group_card(group), reply_markup=kb_group_actions(group))
    await callback.answer("⏸ Nofaol qilindi!")


@router.callback_query(F.data.startswith("group:test:"))
async def cb_group_test(callback: CallbackQuery, bot: Bot, db: DatabaseService) -> None:
    """Faqat shu guruhga test xabar yuborish."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    chat_id = int(callback.data.split(":")[2])
    group   = await db.get_group_by_chat_id(chat_id)
    if not group:
        await callback.answer("❌ Guruh topilmadi!", show_alert=True)
        return

    await callback.answer("⏳ Yuborilmoqda...")

    info = get_tomorrow_info(TIMEZONE)
    text = build_reminder_message(info, group.audience)

    try:
        sent = await bot.send_message(chat_id=group.chat_id, text=text, parse_mode="HTML")
        await db.save_message_id(group.chat_id, sent.message_id)
        logger.info(f"Test yuborildi: '{group.name}' msg_id={sent.message_id}")

        group = await db.get_group_by_chat_id(chat_id)
        await safe_edit(callback.message, 
            _group_card(group) + "\n✅ <b>Test muvaffaqiyatli yuborildi!</b>",
            reply_markup=kb_group_actions(group),
        )
    except Exception as e:
        logger.error(f"Test xatosi '{group.name}': {e}")
        await safe_edit(callback.message, 
            f"{_group_card(group)}\n❌ <b>Xatolik:</b> <code>{e}</code>",
            reply_markup=kb_group_actions(group),
        )


@router.callback_query(F.data.startswith("group:delete_msg:"))
async def cb_group_delete_msg(callback: CallbackQuery, bot: Bot, db: DatabaseService) -> None:
    """Faqat shu guruhdan oxirgi xabarni o'chirish."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    chat_id = int(callback.data.split(":")[2])
    group   = await db.get_group_by_chat_id(chat_id)

    if not group or not group.last_message_id:
        await callback.answer("📭 O'chiriladigan xabar yo'q!", show_alert=True)
        return

    try:
        await bot.delete_message(chat_id=group.chat_id, message_id=group.last_message_id)
        await db.clear_message_id(group.chat_id)
        logger.info(f"Xabar o'chirildi: '{group.name}' msg_id={group.last_message_id}")

        group = await db.get_group_by_chat_id(chat_id)
        await safe_edit(callback.message, 
            _group_card(group) + "\n✅ <b>Xabar o'chirildi!</b>",
            reply_markup=kb_group_actions(group),
        )
        await callback.answer("🗑 O'chirildi!")
    except Exception as e:
        err = str(e).lower()
        if "message to delete not found" in err:
            await db.clear_message_id(group.chat_id)
            await callback.answer("⚠️ Xabar avval o'chirilgan!", show_alert=True)
        else:
            logger.error(f"O'chirishda xato '{group.name}': {e}")
            await callback.answer(f"❌ Xato: {e}", show_alert=True)


@router.callback_query(F.data.startswith("group:delete_ask:"))
async def cb_group_delete_ask(callback: CallbackQuery, db: DatabaseService) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    chat_id = int(callback.data.split(":")[2])
    group   = await db.get_group_by_chat_id(chat_id)
    if not group:
        await callback.answer("❌ Guruh topilmadi!", show_alert=True)
        return

    await safe_edit(callback.message, 
        f"⚠️ <b>Tasdiqlash!</b>\n\n"
        f"<b>{group.name}</b> guruhini ro'yxatdan o'chirishni xohlaysizmi?\n"
        f"Bu amalni qaytarib bo'lmaydi!",
        reply_markup=kb_confirm_delete(chat_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("group:delete_yes:"))
async def cb_group_delete_yes(callback: CallbackQuery, db: DatabaseService) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    chat_id = int(callback.data.split(":")[2])
    await db.remove_group(chat_id)
    groups = await db.get_all_groups()

    await safe_edit(callback.message,
        "✅ <b>Guruh o'chirildi!</b>\n\nQolgan guruhlar:",
        reply_markup=kb_group_list(groups, "all") if groups else kb_admin_panel(),
    )
    await callback.answer("🗑 O'chirildi!")


# ═══════════════════════════════════════════════════════════════════════════════
#  FSM — GURUH QO'SHISH (4 QADAM)
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin:add_start")
async def cb_add_start(callback: CallbackQuery, state: FSMContext, db: DatabaseService) -> None:
    """➕ Qo'shish bosildi — bot a'zo guruhlar ro'yxatini ko'rsat."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    bot_chats = await db.get_bot_chats()

    if not bot_chats:
        await safe_edit(callback.message, 
            "😔 <b>Hali hech bir guruhda yo'q</b>\n\n"
            "Botni guruhlarga qo'shing, keyin shu tugmani bosing.\n\n"
            "Bot guruhga qo'shilganda avtomatik ro'yxat yangilanadi.",
            reply_markup=kb_admin_panel(),
        )
        await callback.answer()
        return

    await state.set_state(BulkAddFSM.selecting_groups)
    await state.update_data(selected=[])

    await safe_edit(callback.message, 
        f"➕ <b>Guruhlarni tanlang</b>\n\n"
        f"Bot a'zo bo'lgan guruhlar: <b>{len(bot_chats)}</b> ta\n\n"
        f"Qo'shmoqchi bo'lgan guruhlarni belgilang (✅),\n"
        f"keyin <b>Davom etish</b> ni bosing:",
        reply_markup=kb_group_selector(bot_chats, selected=set()),
    )
    await callback.answer()


@router.message(StateFilter(AddGroupFSM.waiting_chat_id))
async def fsm_got_chat_id(message: Message, state: FSMContext) -> None:
    try:
        chat_id = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer(
            "❌ Raqam kiriting!\nMasalan: <code>-1001234567890</code>",
            reply_markup=kb_cancel_fsm(),
        )
        return

    await state.update_data(chat_id=chat_id)
    await state.set_state(AddGroupFSM.waiting_name)
    await message.answer(
        f"✅ Chat ID: <code>{chat_id}</code>\n\n"
        f"<b>2/4 — Guruh nomi</b>\n\n"
        f"Guruh nomini kiriting (masalan: <code>Python_1A</code>):",
        reply_markup=kb_cancel_fsm(),
    )


@router.message(StateFilter(AddGroupFSM.waiting_name))
async def fsm_got_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip() if message.text else ""
    if not name or len(name) > 255:
        await message.answer("❌ Nom 1-255 belgi bo'lishi kerak.", reply_markup=kb_cancel_fsm())
        return

    await state.update_data(name=name)
    await state.set_state(AddGroupFSM.waiting_type)
    await message.answer(
        f"✅ Nom: <b>{name}</b>\n\n"
        f"<b>3/4 — Jadval turi</b>\n\n"
        f"Bu guruh qaysi kunlarda dars oladi?",
        reply_markup=kb_choose_type(),
    )


@router.callback_query(F.data.startswith("fsm:type:"), StateFilter(AddGroupFSM.waiting_type))
async def fsm_got_type(callback: CallbackQuery, state: FSMContext) -> None:
    raw  = callback.data.split(":")[2]
    gtype = GroupType.ODD if raw == "odd" else GroupType.EVEN
    label = "Toq kunliklar" if gtype == GroupType.ODD else "Juft kunliklar"

    await state.update_data(group_type=gtype.value)
    await state.set_state(AddGroupFSM.waiting_audience)

    await safe_edit(callback.message, 
        f"✅ Jadval: <b>{label}</b>\n\n"
        f"<b>4/4 — Auditoriya turi</b>\n\n"
        f"Bu guruh kimlar uchun?",
        reply_markup=kb_choose_audience(),
    )
    await callback.answer()


@router.callback_query(
    F.data.startswith("fsm:audience:"),
    StateFilter(AddGroupFSM.waiting_audience),
)
async def fsm_got_audience(
    callback: CallbackQuery, state: FSMContext, db: DatabaseService
) -> None:
    raw      = callback.data.split(":")[2]
    audience = AudienceType.PARENT if raw == "parent" else AudienceType.STUDENT
    aud_label = "👨‍👩‍👧 Ota-onalar" if audience == AudienceType.PARENT else "🎓 O'quvchilar"

    data      = await state.get_data()
    chat_id   = data["chat_id"]
    name      = data["name"]
    group_type = GroupType(data["group_type"])
    type_label = "Toq kunliklar" if group_type == GroupType.ODD else "Juft kunliklar"

    await state.clear()

    try:
        group = await db.add_group(
            chat_id=chat_id, name=name,
            group_type=group_type, audience=audience,
        )
        await safe_edit(callback.message, 
            f"🎉 <b>Guruh muvaffaqiyatli qo'shildi!</b>\n\n"
            f"📌 Nomi: <b>{group.name}</b>\n"
            f"🆔 Chat ID: <code>{group.chat_id}</code>\n"
            f"📋 Jadval: {type_label}\n"
            f"👥 Auditoriya: {aud_label}\n"
            f"🟢 Holat: Aktiv",
            reply_markup=kb_admin_panel(),
        )
        await callback.answer("✅ Qo'shildi!")
        logger.info(
            f"Yangi guruh: '{name}' | {group_type.value} | {audience.value}"
        )
    except Exception as e:
        logger.error(f"FSM saqlash xatosi: {e}")
        await safe_edit(callback.message, 
            f"❌ <b>Saqlashda xatolik!</b>\n<code>{e}</code>",
            reply_markup=kb_admin_panel(),
        )
        await callback.answer()


# ═══════════════════════════════════════════════════════════════════════════════
#  BULK ADD — Multi-select orqali bir nechta guruh qo'shish
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(
    F.data.startswith("select:toggle:"),
    StateFilter(BulkAddFSM.selecting_groups),
)
async def cb_select_toggle(callback: CallbackQuery, state: FSMContext, db: DatabaseService) -> None:
    """Guruhni tanlash/bekor qilish (toggle)."""
    chat_id = int(callback.data.split(":")[2])
    data    = await state.get_data()
    selected: set[int] = set(data.get("selected", []))

    if chat_id in selected:
        selected.discard(chat_id)
    else:
        selected.add(chat_id)

    await state.update_data(selected=list(selected))

    bot_chats = await db.get_bot_chats()
    await safe_edit_markup(callback.message, 
        reply_markup=kb_group_selector(bot_chats, selected)
    )
    await callback.answer()


@router.callback_query(F.data == "select:all", StateFilter(BulkAddFSM.selecting_groups))
async def cb_select_all(callback: CallbackQuery, state: FSMContext, db: DatabaseService) -> None:
    """Barcha guruhlarni tanlash."""
    bot_chats = await db.get_bot_chats()
    selected  = {c.chat_id for c in bot_chats}
    await state.update_data(selected=list(selected))
    await safe_edit_markup(callback.message, 
        reply_markup=kb_group_selector(bot_chats, selected)
    )
    await callback.answer(f"☑️ {len(selected)} ta tanlandi!")


@router.callback_query(F.data == "select:none", StateFilter(BulkAddFSM.selecting_groups))
async def cb_select_none(callback: CallbackQuery, state: FSMContext, db: DatabaseService) -> None:
    """Tanlashni bekor qilish."""
    bot_chats = await db.get_bot_chats()
    await state.update_data(selected=[])
    await safe_edit_markup(callback.message, 
        reply_markup=kb_group_selector(bot_chats, set())
    )
    await callback.answer("⬜ Bekor qilindi")


@router.callback_query(F.data == "select:confirm", StateFilter(BulkAddFSM.selecting_groups))
async def cb_select_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """Tanlangan guruhlar bilan davom etish — jadval turini so'rash."""
    data     = await state.get_data()
    selected = data.get("selected", [])

    if not selected:
        await callback.answer("⚠️ Hech qaysi guruh tanlanmadi!", show_alert=True)
        return

    await state.set_state(BulkAddFSM.waiting_type)
    await safe_edit(callback.message, 
        f"✅ <b>{len(selected)} ta guruh tanlandi</b>\n\n"
        f"<b>Jadval turi</b>\n\n"
        f"Bu guruhlar qaysi kunlarda dars oladi?",
        reply_markup=kb_choose_type(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fsm:type:"), StateFilter(BulkAddFSM.waiting_type))
async def bulk_got_type(callback: CallbackQuery, state: FSMContext) -> None:
    """BulkAdd — jadval turi tanlandi."""
    raw    = callback.data.split(":")[2]
    gtype  = GroupType.ODD if raw == "odd" else GroupType.EVEN
    label  = "Toq kunliklar" if gtype == GroupType.ODD else "Juft kunliklar"

    await state.update_data(group_type=gtype.value)
    await state.set_state(BulkAddFSM.waiting_audience)

    data  = await state.get_data()
    count = len(data.get("selected", []))

    await safe_edit(callback.message, 
        f"✅ Jadval: <b>{label}</b>\n\n"
        f"<b>Auditoriya</b>\n\n"
        f"Bu <b>{count} ta</b> guruh kimlar uchun?",
        reply_markup=kb_choose_audience(),
    )
    await callback.answer()


@router.callback_query(
    F.data.startswith("fsm:audience:"),
    StateFilter(BulkAddFSM.waiting_audience),
)
async def bulk_got_audience(
    callback: CallbackQuery, state: FSMContext, db: DatabaseService
) -> None:
    """BulkAdd — auditoriya tanlandi, barcha guruhlarni saqlaymiz."""
    raw      = callback.data.split(":")[2]
    audience = AudienceType.PARENT if raw == "parent" else AudienceType.STUDENT
    aud_label = "👨‍👩‍👧 Ota-onalar" if audience == AudienceType.PARENT else "🎓 O'quvchilar"

    data       = await state.get_data()
    selected   = data.get("selected", [])
    group_type = GroupType(data["group_type"])
    type_label = "Toq kunliklar" if group_type == GroupType.ODD else "Juft kunliklar"

    # Guruh nomlarini bot_chats dan olamiz
    bot_chats    = await db.get_bot_chats()
    chat_map     = {c.chat_id: c.title for c in bot_chats}

    await state.clear()

    ok, fail = 0, 0
    saved_names = []

    for chat_id in selected:
        title = chat_map.get(chat_id, f"Guruh {chat_id}")
        try:
            await db.add_group(
                chat_id=chat_id,
                name=title,
                group_type=group_type,
                audience=audience,
            )
            saved_names.append(f"  ✅ {title}")
            ok += 1
        except Exception as e:
            saved_names.append(f"  ❌ {title}: {e}")
            fail += 1
            logger.error(f"Bulk save xato '{title}': {e}")

    names_text = "\n".join(saved_names[:10])
    if len(saved_names) > 10:
        names_text += f"\n  ... va yana {len(saved_names)-10} ta"

    await safe_edit(callback.message, 
        f"🎉 <b>Guruhlar qo'shildi!</b>\n\n"
        f"📋 Jadval: {type_label}\n"
        f"👥 Auditoriya: {aud_label}\n\n"
        f"<b>Natija:</b> {ok} ta muvaffaqiyatli, {fail} ta xato\n\n"
        f"{names_text}",
        reply_markup=kb_admin_panel(),
    )
    await callback.answer("✅ Saqlandi!")
    logger.info(f"BulkAdd: {ok} guruh qo'shildi | {type_label} | {aud_label}")


# ═══════════════════════════════════════════════════════════════════════════════
#  QUICK ADD — Guruhga qo'shilganda tezkor qo'shish (2 click)
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("quickadd:start:"))
async def cb_quickadd_start(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Admin 'Ha, qo'shish' ni bosdi.
    Chat ID va nom allaqachon ma'lum (pending_groups dan).
    Faqat jadval turi va auditoriyani so'raymiz (2 qadam).
    """
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    chat_id = int(callback.data.split(":")[2])
    title   = pending_groups.get(chat_id)

    if not title:
        # Xotiradan o'chib ketgan bo'lsa (bot qayta ishga tushgan)
        title = f"Guruh {chat_id}"

    # FSM ga chat_id va nomni oldindan yozamiz
    await state.update_data(chat_id=chat_id, name=title)
    await state.set_state(AddGroupFSM.waiting_type)

    await safe_edit(callback.message, 
        f"➕ <b>Guruh qo'shilmoqda</b>\n\n"
        f"📌 Nomi: <b>{title}</b>\n"
        f"🆔 Chat ID: <code>{chat_id}</code>\n\n"
        f"<b>1/2 — Jadval turi</b>\n\n"
        f"Bu guruh qaysi kunlarda dars oladi?",
        reply_markup=kb_choose_type(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("quickadd:skip:"))
async def cb_quickadd_skip(callback: CallbackQuery) -> None:
    """Admin 'O'tkazib yuborish' ni bosdi."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    chat_id = int(callback.data.split(":")[2])
    pending_groups.pop(chat_id, None)  # Xotiradan o'chiramiz

    await safe_edit(callback.message, 
        "⏭ <b>O'tkazib yuborildi.</b>\n\n"
        "Kerak bo'lsa paneldan qo'shishingiz mumkin:",
        reply_markup=kb_admin_panel(),
    )
    await callback.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    """Bo'sh tugma — hech narsa qilmaydi."""
    await callback.answer()


@router.callback_query(F.data == "fsm:cancel")
async def fsm_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(callback.message, 
        "❌ <b>Bekor qilindi.</b>\n\nAdmin panel:",
        reply_markup=kb_admin_panel(),
    )
    await callback.answer("Bekor qilindi")
