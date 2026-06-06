"""
handlers/group_join.py — Guruhga qo'shilish anketasi (2 tilda: O'zbek + Rus).

Oqim (Yo'l B — bot orqali kirish):
  1. Foydalanuvchi `t.me/BOT?start=join` havolasini bosadi.
  2. Bot anketani so'raydi: ism familiya → yosh (faqat raqam) → qiziqishlar.
  3. (Ixtiyoriy) majburiy kanal obunasi — JOIN_REQUIRE_SUBSCRIPTION yoqilgan bo'lsa.
  4. Bot bir martalik taklif havolasi yuboradi → user guruhga kiradi.
  5. Adminga ma'lumot (ism/yosh/qiziqish/username) yuboriladi + DB ga saqlanadi.
  6. User guruhga kirgach, guruhda "Xush kelibsiz, <ism>" xabari chiqadi.

Yo'l A (poisk + kirish arizasi) ham parallel ishlaydi: chat_join_request → anketa
→ ariza tasdiqlanadi.

Barcha matnlar 2 tilda — ba'zi o'quvchilar o'zbekchani bilmasligi mumkin.
"""

import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import (
    ADMIN_IDS,
    INSTAGRAM_LINK,
    JOIN_GATE_ENABLED,
    JOIN_REQUIRE_SUBSCRIPTION,
    JOIN_TARGET_CHAT_ID,
    REQUIRED_CHANNELS,
    VIDEO_LESSONS_LINK,
)
from database import DatabaseService

logger = logging.getLogger(__name__)
router = Router()

# Kutilayotgan arizalar — {user_id: {"chat_id": int, "title": str}}
pending_join: dict[int, dict] = {}


class JoinFSM(StatesGroup):
    name = State()
    age = State()
    interests = State()
    subscribe = State()


# ─── Yordamchi funksiyalar ────────────────────────────────────────────────────


async def _resolve_target_chat(bot: Bot, db: DatabaseService) -> tuple[int | None, str]:
    """Yo'l B uchun maqsadli guruhni aniqlaydi (env yoki yagona guruh)."""
    if JOIN_TARGET_CHAT_ID:
        title = "guruh"
        try:
            chat = await bot.get_chat(JOIN_TARGET_CHAT_ID)
            title = chat.title or title
        except Exception as e:
            logger.warning(f"Target guruh ma'lumotini olib bo'lmadi: {e}")
        return JOIN_TARGET_CHAT_ID, title
    chats = await db.get_bot_chats()
    if len(chats) == 1:
        return chats[0].chat_id, chats[0].title
    return None, ""


async def _missing_subscriptions(bot: Bot, user_id: int) -> list[dict]:
    """Obuna bo'linmagan (tekshirib bo'ladigan) kanallar ro'yxati."""
    missing: list[dict] = []
    for ch in REQUIRED_CHANNELS:
        chat = ch.get("chat")
        if not chat:
            continue
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
    rows.append(
        [InlineKeyboardButton(text="✅ Tekshirish / Проверить", callback_data="joingate:verify")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _start_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Boshlash / Начать", callback_data=f"joingate:start:{chat_id}")]
        ]
    )


# Anketa matnlari (2 tilda) ────────────────────────────────────────────────────
_Q_NAME = (
    "✍️ <b>1/3</b>\n\n"
    "🇺🇿 Ism va familiyangizni yozing.\n"
    "🇷🇺 Напишите ваше имя и фамилию.\n\n"
    "<i>Masalan / Например: Ali Valiyev</i>"
)
_Q_AGE = (
    "🎂 <b>2/3</b>\n\n"
    "🇺🇿 Necha yoshdasiz? Faqat <b>raqam</b> yozing.\n"
    "🇷🇺 Сколько вам лет? Напишите только <b>число</b>.\n\n"
    "<i>Masalan / Например: 12</i>"
)
_Q_INTERESTS = (
    "💡 <b>3/3</b>\n\n"
    "🇺🇿 Nimaga qiziqasiz?\n"
    "🇷🇺 Чем вы увлекаетесь?\n\n"
    "<i>🇺🇿 Masalan: dasturlash, rasm chizish, ingliz tili\n"
    "🇷🇺 Например: программирование, рисование, английский</i>"
)
_ERR_NAME = (
    "🇺🇿 Iltimos, ism va familiyangizni to'liq yozing.\n"
    "🇷🇺 Пожалуйста, напишите имя и фамилию полностью."
)
_ERR_AGE = (
    "❌ 🇺🇿 Faqat raqam yozing (masalan: 12).\n"
    "🇷🇺 Напишите только число (например: 12)."
)
_ERR_INTERESTS = (
    "🇺🇿 Iltimos, qiziqishlaringizni yozing.\n"
    "🇷🇺 Пожалуйста, напишите ваши увлечения."
)
_SUBS_PROMPT = (
    "✅ <b>Anketa to'ldirildi! / Анкета заполнена!</b>\n\n"
    "🇺🇿 Endi quyidagi kanal(lar)ga obuna bo'ling va «Tekshirish» tugmasini bosing.\n"
    "🇷🇺 Теперь подпишитесь на канал(ы) ниже и нажмите «Проверить»."
)


def _start_text(title: str) -> str:
    return (
        "👋 <b>Salom! Привет!</b>\n\n"
        f"🇺🇿 <b>{title}</b> guruhiga qo'shilish uchun 3 ta savolga javob bering.\n"
        f"🇷🇺 Чтобы вступить в группу <b>{title}</b>, ответьте на 3 вопроса.\n\n"
        f"{_Q_NAME}"
    )


# ─── Yakuniy bosqich: havola/tasdiq + DB + admin xabar ────────────────────────


async def _finalize_join(user, data: dict, bot: Bot, db: DatabaseService) -> tuple[str, InlineKeyboardMarkup | None]:
    """Anketa tugagach: guruhga qo'shish (havola yoki tasdiq), DB, admin xabar.

    Qaytaradi: (foydalanuvchiga ko'rsatiladigan matn, markup | None).
    """
    chat_id = data.get("jg_chat_id")
    mode = data.get("jg_mode", "approve")
    title = data.get("jg_title") or pending_join.get(user.id, {}).get("title", "guruh")
    name = data.get("jg_name", "")
    age = data.get("jg_age", "")
    interests = data.get("jg_interests", "")
    username = f"@{user.username}" if user.username else None

    ok = True
    invite_link: str | None = None
    if mode == "invite":
        try:
            link_obj = await bot.create_chat_invite_link(
                chat_id,
                name=name[:30] or "join",
                member_limit=1,
                expire_date=datetime.now() + timedelta(hours=24),
            )
            invite_link = link_obj.invite_link
        except Exception as e:
            logger.warning(f"create_chat_invite_link xatosi ({chat_id}): {e}")
            ok = False
    else:
        try:
            await bot.approve_chat_join_request(chat_id, user.id)
        except Exception as e:
            logger.warning(f"approve_chat_join_request xatosi ({user.id}→{chat_id}): {e}")
            ok = False

    # DB ga saqlash
    try:
        await db.save_join_applicant(
            user_id=user.id,
            chat_id=chat_id,
            group_title=title,
            full_name=name,
            age=age,
            interests=interests,
            username=username,
            status="approved" if ok else "pending",
        )
    except Exception as e:
        logger.warning(f"save_join_applicant xatosi: {e}")

    pending_join.pop(user.id, None)

    # Adminlarga bildirishnoma (username bo'lsa ko'rsatamiz)
    username_line = username if username else "— (yo'q)"
    admin_text = (
        "🆕 <b>Yangi o'quvchi guruhga qo'shildi!</b>\n\n"
        f"📌 Guruh: <b>{title}</b>\n"
        f"👤 Ism: <b>{name}</b>\n"
        f"🎂 Yosh: <b>{age}</b>\n"
        f"💡 Qiziqishlar: {interests}\n"
        f"💬 Username: {username_line}\n"
        f"🔗 User ID: <code>{user.id}</code>"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_text)
        except Exception as e:
            logger.warning(f"Admin {admin_id} ga bildirishnoma yuborib bo'lmadi: {e}")

    # Foydalanuvchiga javob
    if mode == "invite" and invite_link:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🚀 Guruhga kirish / Вступить", url=invite_link)]]
        )
        text = (
            "🎉 <b>Tabriklaymiz! Поздравляем!</b>\n\n"
            f"🇺🇿 <b>{name}</b>, anketa qabul qilindi! Pastdagi tugmani bosing va guruhga qo'shiling.\n"
            f"🇷🇺 <b>{name}</b>, анкета принята! Нажмите кнопку ниже и вступите в группу.\n\n"
            "<i>🇺🇿 Havola faqat siz uchun, 24 soat ishlaydi.\n"
            "🇷🇺 Ссылка только для вас, работает 24 часа.</i>"
        )
        return text, markup
    if mode == "approve" and ok:
        text = (
            "🎉 <b>Tabriklaymiz! Поздравляем!</b>\n\n"
            f"🇺🇿 <b>{name}</b>, siz guruhga qabul qilindingiz!\n"
            f"🇷🇺 <b>{name}</b>, вы приняты в группу!"
        )
        return text, None
    text = (
        "⚠️ 🇺🇿 Anketa saqlandi, lekin guruhga qo'sha olmadik. Admin bilan bog'laning.\n"
        "🇷🇺 Анкета сохранена, но не удалось добавить в группу. Свяжитесь с админом."
    )
    return text, None


# ─── Yo'l B: /start join ──────────────────────────────────────────────────────


async def start_join_flow(message: Message, state: FSMContext, bot: Bot, db: DatabaseService) -> None:
    """Bot orqali kirish: /start join deep-link dan chaqiriladi."""
    chat_id, title = await _resolve_target_chat(bot, db)
    if not chat_id:
        await message.answer(
            "⚠️ 🇺🇿 Hozircha guruhga qo'shilish sozlanmagan. Admin bilan bog'laning.\n"
            "🇷🇺 Вступление пока не настроено. Свяжитесь с админом."
        )
        logger.warning("start_join_flow: target guruh aniqlanmadi (JOIN_TARGET_CHAT_ID ni o'rnating).")
        return
    await state.set_state(JoinFSM.name)
    await state.update_data(jg_chat_id=chat_id, jg_title=title, jg_mode="invite")
    await message.answer(_start_text(title))


# ─── Yo'l A: kirish arizasi (poisk) ───────────────────────────────────────────


@router.chat_join_request()
async def on_join_request(req: ChatJoinRequest, bot: Bot) -> None:
    """Guruhga kirish arizasi kelganda DM da anketani boshlaymiz."""
    user = req.from_user
    chat = req.chat

    if not JOIN_GATE_ENABLED:
        try:
            await req.approve()
        except Exception as e:
            logger.warning(f"Join request avto-tasdiq xatosi: {e}")
        return

    pending_join[user.id] = {"chat_id": chat.id, "title": chat.title or "guruh"}
    text = (
        "👋 <b>Salom! Привет!</b>\n\n"
        f"🇺🇿 Siz <b>{chat.title or 'guruh'}</b> guruhiga qo'shilmoqchisiz. "
        "Qabul qilinish uchun qisqa anketani to'ldiring.\n"
        f"🇷🇺 Вы хотите вступить в <b>{chat.title or 'группу'}</b>. "
        "Заполните короткую анкету, чтобы вас приняли.\n\n"
        "👇 Boshlash / Начать"
    )
    try:
        await bot.send_message(user.id, text, reply_markup=_start_keyboard(chat.id))
        logger.info(f"Join gate: {user.id} ({user.full_name}) → '{chat.title}' ({chat.id}) anketa boshlandi")
    except Exception as e:
        logger.warning(f"Join gate DM yuborib bo'lmadi ({user.id}): {e}")


@router.callback_query(F.data.startswith("joingate:start:"))
async def join_start(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = int(cb.data.split(":")[2])
    info = pending_join.get(cb.from_user.id, {})
    await state.set_state(JoinFSM.name)
    await state.update_data(jg_chat_id=chat_id, jg_title=info.get("title", "guruh"), jg_mode="approve")
    await cb.message.edit_text(_Q_NAME)
    await cb.answer()


# ─── Anketa: ism → yosh → qiziqishlar ─────────────────────────────────────────


@router.message(StateFilter(JoinFSM.name), F.chat.type == "private")
async def join_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 3:
        await message.answer(_ERR_NAME)
        return
    await state.update_data(jg_name=name)
    await state.set_state(JoinFSM.age)
    await message.answer(_Q_AGE)


@router.message(StateFilter(JoinFSM.age), F.chat.type == "private")
async def join_age(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    # Faqat raqam — tekshiramiz
    if not raw.isdigit() or not (3 <= int(raw) <= 100):
        await message.answer(_ERR_AGE)
        return
    await state.update_data(jg_age=raw)
    await state.set_state(JoinFSM.interests)
    await message.answer(_Q_INTERESTS)


@router.message(StateFilter(JoinFSM.interests), F.chat.type == "private")
async def join_interests(message: Message, state: FSMContext, bot: Bot, db: DatabaseService) -> None:
    interests = (message.text or "").strip()
    if len(interests) < 2:
        await message.answer(_ERR_INTERESTS)
        return
    await state.update_data(jg_interests=interests)

    # Obuna talab qilinsa — obuna bosqichiga o'tamiz
    if JOIN_REQUIRE_SUBSCRIPTION and (REQUIRED_CHANNELS or INSTAGRAM_LINK):
        await state.set_state(JoinFSM.subscribe)
        await message.answer(_SUBS_PROMPT, reply_markup=_subs_keyboard())
        return

    # Obunasiz — to'g'ridan-to'g'ri yakunlaymiz
    data = await state.get_data()
    text, markup = await _finalize_join(message.from_user, data, bot, db)
    await state.clear()
    await message.answer(text, reply_markup=markup)


# ─── (Ixtiyoriy) obunani tekshirish ───────────────────────────────────────────


@router.callback_query(F.data == "joingate:verify", StateFilter(JoinFSM.subscribe))
async def join_verify(cb: CallbackQuery, state: FSMContext, bot: Bot, db: DatabaseService) -> None:
    user = cb.from_user
    data = await state.get_data()
    if not data.get("jg_chat_id"):
        await cb.answer("Sessiya topilmadi. /start bosing. / Сессия не найдена.", show_alert=True)
        await state.clear()
        return

    missing = await _missing_subscriptions(bot, user.id)
    if missing:
        labels = ", ".join(m["label"] for m in missing)
        await cb.answer(
            f"❌ Obuna bo'ling / Подпишитесь:\n{labels}",
            show_alert=True,
        )
        return

    text, markup = await _finalize_join(user, data, bot, db)
    await state.clear()
    await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


# ─── Guruhga kirgach: "Xush kelibsiz" xabari ──────────────────────────────────


@router.chat_member()
async def on_member_joined(event: ChatMemberUpdated, bot: Bot, db: DatabaseService) -> None:
    """Yangi a'zo guruhga kirganda ismi bilan xush kelibsiz xabari."""
    old = event.old_chat_member.status if event.old_chat_member else None
    new = event.new_chat_member.status if event.new_chat_member else None
    # Faqat a'zo bo'lib kirganda (chiqib/quvilgandan → a'zo)
    if new != "member" or old not in ("left", "kicked"):
        return
    if event.chat.type not in ("group", "supergroup"):
        return

    user = event.new_chat_member.user
    if user.is_bot:
        return

    # Anketadagi haqiqiy ismni topamiz
    name = user.full_name
    try:
        applicants = await db.get_join_applicants(chat_id=event.chat.id)
        match = next((a for a in applicants if a.user_id == user.id), None)
        if match and match.full_name:
            name = match.full_name
    except Exception as e:
        logger.warning(f"on_member_joined: applicant qidirishda xato: {e}")

    mention = f'<a href="tg://user?id={user.id}">{name}</a>'
    text = (
        "🎉🎊 <b>URRAA! Yangi do'stimiz keldi!</b> 🎊🎉\n\n"
        f"👋 Xush kelibsiz, {mention}!\n\n"
        "🚀 Sen endi bizning ajoyib jamoamizning bir qismisan! "
        "Bu yerda biz birga <b>o'rganamiz</b>, <b>o'ynaymiz</b> va yangi narsalarni <b>kashf qilamiz</b>! 💡✨\n\n"
        "📺 <b>Yangi keldingmi yoki darsdan qolib ketdingmi?</b>\n"
        "Hech qisi yo'q! 😎 Pastdagi tugmani bos — barcha video darsliklarni ko'rib, "
        "hammaga bemalol yetib olasan! 🎬🔥\n\n"
        "🇷🇺 <i>Добро пожаловать! Если ты новенький или пропустил урок — "
        "нажми кнопку ниже и смотри все видеоуроки! 🎬</i>"
    )
    markup = None
    if VIDEO_LESSONS_LINK:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎬 Video darsliklar / Видеоуроки", url=VIDEO_LESSONS_LINK)]
            ]
        )
    try:
        await bot.send_message(event.chat.id, text, reply_markup=markup)
    except Exception as e:
        logger.warning(f"Guruhga xush kelibsiz xabarini yuborib bo'lmadi ({event.chat.id}): {e}")
