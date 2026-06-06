"""
handlers/group_join.py — Guruhga kirish arizasi (join request) "gate".

Oqim:
  1. Foydalanuvchi guruhga kirish arizasini yuboradi
     (guruhda "Approve new members" yoqilgan, bot esa admin).
  2. Bot unga shaxsiy (DM) xabar yuboradi va FSM boshlaydi:
       ism familiya → yosh → qiziqishlar.
  3. Majburiy obuna bosqichi: Telegram kanal(lar) obunasi TEKSHIRILADI,
     Instagram esa faqat tugma (Telegram bot uni tekshira olmaydi).
  4. Hammasi bajarilsa — ariza tasdiqlanadi (approve_chat_join_request)
     va a'zo guruhga qabul qilinadi.
  5. Adminlarga ism/yosh/qiziqish bilan bildirishnoma yuboriladi + DB ga saqlanadi.

MUHIM: bot guruhda admin bo'lib, "Add users / Approve new members" huquqiga ega
bo'lishi shart. Obunani tekshirish uchun bot tegishli kanal(lar)da ham admin
bo'lishi kerak (config.REQUIRED_CHANNELS).
"""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import ADMIN_IDS, INSTAGRAM_LINK, JOIN_GATE_ENABLED, REQUIRED_CHANNELS
from database import DatabaseService

logger = logging.getLogger(__name__)
router = Router()

# Kutilayotgan arizalar — {user_id: {"chat_id": int, "title": str}}
# Bir foydalanuvchi bir vaqtda bitta arizani to'ldiradi (oxirgisi saqlanadi).
pending_join: dict[int, dict] = {}


class JoinFSM(StatesGroup):
    name = State()
    age = State()
    interests = State()
    subscribe = State()


# ─── Yordamchi: obuna tekshirish va klaviatura ────────────────────────────────


async def _missing_subscriptions(bot: Bot, user_id: int) -> list[dict]:
    """Obuna bo'linmagan (tekshirib bo'ladigan) kanallar ro'yxatini qaytaradi.

    - `chat` bo'sh kanallar (Instagram, yopiq invite) tekshirilmaydi — o'tkazib yuboriladi.
    - Bot kanal/guruhda admin bo'lmasa yoki xato bo'lsa — BLOKLAMAYMIZ (faqat log).
    """
    missing: list[dict] = []
    for ch in REQUIRED_CHANNELS:
        chat = ch.get("chat")
        if not chat:
            continue  # tekshirib bo'lmaydi — faqat tugma
        try:
            member = await bot.get_chat_member(chat, user_id)
            if member.status in ("left", "kicked"):
                missing.append(ch)
        except Exception as e:
            logger.warning(f"Obuna tekshirib bo'lmadi ({chat}): {e}")
    return missing


def _subs_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for ch in REQUIRED_CHANNELS:
        if ch.get("link"):
            rows.append([InlineKeyboardButton(text=f"📢 {ch['label']}", url=ch["link"])])
    if INSTAGRAM_LINK:
        rows.append([InlineKeyboardButton(text="📸 Instagram", url=INSTAGRAM_LINK)])
    rows.append([InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="joingate:verify")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _start_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Ma'lumot kiritish", callback_data=f"joingate:start:{chat_id}")]
        ]
    )


# ─── 1-qadam: kirish arizasi keldi ────────────────────────────────────────────


@router.chat_join_request()
async def on_join_request(req: ChatJoinRequest, bot: Bot) -> None:
    """Guruhga kirish arizasi kelganda DM da anketani boshlaymiz."""
    user = req.from_user
    chat = req.chat

    if not JOIN_GATE_ENABLED:
        # Gate o'chirilgan — to'g'ridan-to'g'ri tasdiqlaymiz
        try:
            await req.approve()
        except Exception as e:
            logger.warning(f"Join request avto-tasdiq xatosi: {e}")
        return

    pending_join[user.id] = {"chat_id": chat.id, "title": chat.title or "guruh"}

    greet_name = user.first_name or "do'st"
    text = (
        f"👋 <b>Assalomu alaykum, {greet_name}!</b>\n\n"
        f"Siz <b>{chat.title or 'guruh'}</b> guruhiga qo'shilmoqchisiz.\n\n"
        f"Guruhga qabul qilinishingiz uchun avval qisqa anketani to'ldiring:\n"
        f"1️⃣ Ism familiya\n"
        f"2️⃣ Yosh\n"
        f"3️⃣ Qiziqishlaringiz\n\n"
        f"So'ng kanallarga obuna bo'lasiz. Boshlash uchun tugmani bosing 👇"
    )
    try:
        await bot.send_message(user.id, text, reply_markup=_start_keyboard(chat.id))
        logger.info(f"Join gate: {user.id} ({user.full_name}) → '{chat.title}' ({chat.id}) anketa boshlandi")
    except Exception as e:
        # Foydalanuvchi botni ishga tushirmagan yoki bloklagan — ariza pending qoladi
        logger.warning(f"Join gate DM yuborib bo'lmadi ({user.id}): {e}")


@router.callback_query(F.data.startswith("joingate:start:"))
async def join_start(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = int(cb.data.split(":")[2])
    await state.set_state(JoinFSM.name)
    await state.update_data(jg_chat_id=chat_id)
    await cb.message.edit_text(
        "📝 <b>1/3 — Ism familiya</b>\n\nIsm va familiyangizni to'liq kiriting:\n<i>(Masalan: Ali Valiyev)</i>"
    )
    await cb.answer()


# ─── 2-qadam: ism → yosh → qiziqishlar ────────────────────────────────────────


@router.message(StateFilter(JoinFSM.name), F.chat.type == "private")
async def join_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 3:
        await message.answer("❌ Iltimos, to'liq ism familiyangizni kiriting (kamida 3 ta belgi):")
        return
    await state.update_data(jg_name=name)
    await state.set_state(JoinFSM.age)
    await message.answer("🎂 <b>2/3 — Yosh</b>\n\nNecha yoshdasiz? (faqat raqam, masalan: 17)")


@router.message(StateFilter(JoinFSM.age), F.chat.type == "private")
async def join_age(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (3 <= int(raw) <= 100):
        await message.answer("❌ Yoshni faqat raqamlarda kiriting (masalan: 17):")
        return
    await state.update_data(jg_age=raw)
    await state.set_state(JoinFSM.interests)
    await message.answer(
        "💡 <b>3/3 — Qiziqishlar</b>\n\n"
        "Nimaga qiziqasiz? (masalan: dasturlash, dizayn, AI, ingliz tili)"
    )


@router.message(StateFilter(JoinFSM.interests), F.chat.type == "private")
async def join_interests(message: Message, state: FSMContext) -> None:
    interests = (message.text or "").strip()
    if len(interests) < 2:
        await message.answer("❌ Iltimos, qiziqishlaringizni yozing:")
        return
    await state.update_data(jg_interests=interests)
    await state.set_state(JoinFSM.subscribe)

    await message.answer(
        "✅ <b>Anketa to'ldirildi!</b>\n\n"
        "📌 Endi guruhga qabul qilinish uchun quyidagi kanallarga <b>obuna bo'ling</b>, "
        "so'ng <b>«Obunani tekshirish»</b> tugmasini bosing:",
        reply_markup=_subs_keyboard(),
    )


# ─── 3-qadam: obunani tekshirish → tasdiqlash ─────────────────────────────────


@router.callback_query(F.data == "joingate:verify", StateFilter(JoinFSM.subscribe))
async def join_verify(cb: CallbackQuery, state: FSMContext, bot: Bot, db: DatabaseService) -> None:
    user = cb.from_user
    data = await state.get_data()
    chat_id = data.get("jg_chat_id")
    info = pending_join.get(user.id, {})
    title = info.get("title", "guruh")

    if not chat_id:
        await cb.answer("Ariza topilmadi. Qaytadan kirish arizasini yuboring.", show_alert=True)
        await state.clear()
        return

    # ── Obunani tekshirish ──────────────────────────────────────────────────
    missing = await _missing_subscriptions(bot, user.id)
    if missing:
        labels = ", ".join(m["label"] for m in missing)
        await cb.answer(
            f"❌ Avval quyidagilarga obuna bo'ling:\n{labels}\n\nSo'ng qayta tekshiring.",
            show_alert=True,
        )
        return

    # ── Arizani tasdiqlash ──────────────────────────────────────────────────
    approved = True
    try:
        await bot.approve_chat_join_request(chat_id, user.id)
    except Exception as e:
        # Ariza muddati o'tgan / allaqachon a'zo / bot huquqi yo'q
        logger.warning(f"approve_chat_join_request xatosi ({user.id}→{chat_id}): {e}")
        approved = False

    name = data.get("jg_name", "")
    age = data.get("jg_age", "")
    interests = data.get("jg_interests", "")
    username = f"@{user.username}" if user.username else None

    # ── DB ga saqlash ──────────────────────────────────────────────────────
    try:
        await db.save_join_applicant(
            user_id=user.id,
            chat_id=chat_id,
            group_title=title,
            full_name=name,
            age=age,
            interests=interests,
            username=username,
            status="approved" if approved else "pending",
        )
    except Exception as e:
        logger.warning(f"save_join_applicant xatosi: {e}")

    pending_join.pop(user.id, None)
    await state.clear()

    if approved:
        await cb.message.edit_text(
            f"🎉 <b>Tabriklaymiz, {name}!</b>\n\n"
            f"Siz <b>{title}</b> guruhiga qabul qilindingiz.\n"
            f"Guruhga o'tib, faol bo'ling! 🚀"
        )
    else:
        await cb.message.edit_text(
            "⚠️ Anketangiz qabul qilindi, lekin guruhga avtomatik qo'sha olmadik.\n"
            "Iltimos, kirish arizangizni qaytadan yuboring yoki admin bilan bog'laning."
        )
    await cb.answer()

    # ── Adminlarga bildirishnoma ────────────────────────────────────────────
    admin_text = (
        "🆕 <b>Guruhga yangi a'zo qo'shildi!</b>\n\n"
        f"📌 Guruh: <b>{title}</b>\n"
        f"👤 Ism: <b>{name}</b>\n"
        f"🎂 Yosh: <b>{age}</b>\n"
        f"💡 Qiziqishlar: {interests}\n"
        f"💬 Telegram: {username or '—'}\n"
        f"🔗 User ID: <code>{user.id}</code>"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text)
        except Exception as e:
            logger.warning(f"Admin {admin_id} ga bildirishnoma yuborib bo'lmadi: {e}")
