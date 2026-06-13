"""
handlers/lesson_topic.py — Dars mavzusi → AI uy vazifasi oqimi (faqat admin).

Oqim:
  1. Admin /vazifa yozadi (yoki dars oxiridagi avtomatik tugmani bosadi).
  2. Guruh tanlaydi → yo'nalish (track) aniqlanadi.
  3. Modul → Blok → Dars mavzusi tanlaydi (o'quv dasturidan, curriculum.py).
  4. AI o'sha mavzuni chuqur tahlil qilib 10-16 yosh uchun 2 tilli vazifa tuzadi.
  5. Admin preview ko'radi → tasdiqlasa, guruhga yuboriladi.

callback_data sxemasi (kalit qisqaligi uchun indekslar ishlatiladi, ro'yxatlar FSM state'da):
  lt:start:<group>   — avtomatik prompt'dan guruh bilan boshlash
  lt:g:<idx>         — guruh tanlash
  lt:m:<idx>         — modul tanlash
  lt:b:<idx>         — blok tanlash
  lt:l:<idx>         — dars tanlash → AI generatsiya
  lt:regen           — qayta generatsiya
  lt:send            — guruhga yuborish
  lt:cancel          — bekor qilish
  lt:back:<step>     — orqaga (groups|modules|blocks)
"""

import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import ai_service
import curriculum
from config import ADMIN_IDS
from database import AudienceType, DatabaseService

logger = logging.getLogger(__name__)
router = Router()

_TG_LIMIT = 4000  # xavfsiz chegara (Telegram 4096)


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


class LessonTaskFSM(StatesGroup):
    group = State()
    module = State()
    block = State()
    lesson = State()
    preview = State()


# ─── Yordamchilar ─────────────────────────────────────────────────────────────


async def _student_group_names(db: DatabaseService) -> list[str]:
    """Aktiv o'quvchi guruhlari nomlarini qaytaradi (takrorsiz, tartiblangan)."""
    groups = await db.get_all_groups()
    names: list[str] = []
    seen: set[str] = set()
    for g in groups:
        if not g.is_active or g.audience != AudienceType.STUDENT:
            continue
        if g.name not in seen:
            seen.add(g.name)
            names.append(g.name)
    return sorted(names)


async def _resolve_group_chat(db: DatabaseService, group_name: str) -> int | None:
    """Guruh nomidan yuboriladigan chat_id ni topadi (o'quvchi guruhini afzal ko'radi)."""
    groups = await db.get_all_groups()
    matches = [g for g in groups if g.name == group_name]
    if not matches:
        return None
    for g in matches:
        if g.is_active and g.audience == AudienceType.STUDENT:
            return g.chat_id
    return matches[0].chat_id


def _kb_back_cancel(back_step: str | None = None) -> list[list[InlineKeyboardButton]]:
    row: list[InlineKeyboardButton] = []
    if back_step:
        row.append(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"lt:back:{back_step}"))
    row.append(InlineKeyboardButton(text="❌ Bekor", callback_data="lt:cancel"))
    return [row]


def _kb_groups(names: list[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"🏫 {n}", callback_data=f"lt:g:{i}")] for i, n in enumerate(names)]
    rows.append([InlineKeyboardButton(text="❌ Bekor", callback_data="lt:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_modules(modules: list[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📦 {m}", callback_data=f"lt:m:{i}")] for i, m in enumerate(modules)]
    rows += _kb_back_cancel("groups")
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_blocks(blocks: list[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"🧩 {b}", callback_data=f"lt:b:{i}")] for i, b in enumerate(blocks)]
    rows += _kb_back_cancel("modules")
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_lessons(titles: list[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📖 {t}"[:60], callback_data=f"lt:l:{i}")] for i, t in enumerate(titles)]
    rows += _kb_back_cancel("blocks")
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_preview() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Guruhga yuborish", callback_data="lt:send")],
            [
                InlineKeyboardButton(text="🔄 Qayta yaratish", callback_data="lt:regen"),
                InlineKeyboardButton(text="❌ Bekor", callback_data="lt:cancel"),
            ],
        ]
    )


async def _send_long(bot: Bot, chat_id: int, text: str, reply_markup=None) -> None:
    """Uzun matnni 4000 belgilik bo'laklarga bo'lib, oddiy matn (parse_mode=None) yuboradi."""
    chunks: list[str] = []
    cur = ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > _TG_LIMIT:
            if cur:
                chunks.append(cur)
            # Bitta qator juda uzun bo'lsa — qattiq kesamiz
            while len(line) > _TG_LIMIT:
                chunks.append(line[:_TG_LIMIT])
                line = line[_TG_LIMIT:]
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)

    for i, chunk in enumerate(chunks):
        is_last = i == len(chunks) - 1
        await bot.send_message(
            chat_id,
            chunk,
            parse_mode=None,  # AI matni toza matn — HTML sifatida talqin qilinmasin
            reply_markup=reply_markup if is_last else None,
        )


# ─── Boshlash ─────────────────────────────────────────────────────────────────


async def _show_groups(message_or_cb, state: FSMContext, db: DatabaseService) -> None:
    """Guruh tanlash bosqichini ko'rsatadi."""
    names = await _student_group_names(db)
    if not names:
        text = "📭 Aktiv o'quvchi guruhlari topilmadi.\nAvval guruh qo'shing (admin panel)."
        if isinstance(message_or_cb, CallbackQuery):
            await message_or_cb.message.edit_text(text)
        else:
            await message_or_cb.answer(text)
        await state.clear()
        return

    await state.update_data(group_list=names)
    await state.set_state(LessonTaskFSM.group)
    text = "📝 <b>Dars vazifasi yaratish</b>\n\nQaysi guruh uchun vazifa tuzamiz?"
    kb = _kb_groups(names)
    if isinstance(message_or_cb, CallbackQuery):
        await message_or_cb.message.edit_text(text, reply_markup=kb)
    else:
        await message_or_cb.answer(text, reply_markup=kb)


@router.message(Command("vazifa"))
async def cmd_vazifa(message: Message, state: FSMContext, db: DatabaseService) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("❌ Bu buyruq faqat adminlar uchun!")
        return
    await state.clear()
    await _show_groups(message, state, db)


@router.callback_query(F.data.startswith("lt:start:"))
async def cb_auto_start(cb: CallbackQuery, state: FSMContext, db: DatabaseService) -> None:
    """Dars oxiridagi avtomatik prompt tugmasi — guruh nomi bilan to'g'ridan modullarga o'tadi."""
    if not _is_admin(cb.from_user.id):
        return
    group_name = cb.data.split(":", 2)[2]
    await state.clear()
    await _enter_group(cb, state, group_name)


async def _enter_group(cb: CallbackQuery, state: FSMContext, group_name: str) -> None:
    """Guruh tanlangach yo'nalishni aniqlab modullarni ko'rsatadi."""
    track = curriculum.track_for_group(group_name)
    modules = curriculum.list_modules(track)
    if not modules:
        await cb.message.edit_text(f"⚠️ '{group_name}' uchun o'quv dasturi topilmadi (yo'nalish: {track}).")
        await state.clear()
        return

    await state.update_data(group_name=group_name, track=track, module_list=modules)
    await state.set_state(LessonTaskFSM.module)
    await cb.message.edit_text(
        f"🏫 Guruh: <b>{group_name}</b>\n"
        f"🧭 Yo'nalish: <b>{curriculum.TRACK_LABELS.get(track, track)}</b>\n\n"
        f"Qaysi <b>modul</b>ni o'tdingiz?",
        reply_markup=_kb_modules(modules),
    )


@router.callback_query(F.data.startswith("lt:g:"), StateFilter(LessonTaskFSM.group))
async def cb_pick_group(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    names = data.get("group_list", [])
    idx = int(cb.data.split(":")[2])
    if idx >= len(names):
        return
    await _enter_group(cb, state, names[idx])


@router.callback_query(F.data.startswith("lt:m:"), StateFilter(LessonTaskFSM.module))
async def cb_pick_module(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    modules = data.get("module_list", [])
    idx = int(cb.data.split(":")[2])
    if idx >= len(modules):
        return
    module = modules[idx]
    track = data["track"]
    blocks = curriculum.list_blocks(track, module)

    await state.update_data(module=module, block_list=blocks)
    await state.set_state(LessonTaskFSM.block)
    await cb.message.edit_text(
        f"🏫 <b>{data['group_name']}</b> · 📦 <b>{module}</b>\n\nQaysi <b>blok</b>ni o'tdingiz?",
        reply_markup=_kb_blocks(blocks),
    )


@router.callback_query(F.data.startswith("lt:b:"), StateFilter(LessonTaskFSM.block))
async def cb_pick_block(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    blocks = data.get("block_list", [])
    idx = int(cb.data.split(":")[2])
    if idx >= len(blocks):
        return
    block = blocks[idx]
    track, module = data["track"], data["module"]
    lessons = curriculum.list_lessons(track, module, block)
    titles = [le.title for le in lessons]

    await state.update_data(block=block, lesson_titles=titles)
    await state.set_state(LessonTaskFSM.lesson)
    await cb.message.edit_text(
        f"🏫 <b>{data['group_name']}</b> · 📦 <b>{module}</b> · 🧩 <b>{block}</b>\n\n"
        f"Qaysi <b>dars mavzusi</b>ni o'tdingiz?",
        reply_markup=_kb_lessons(titles),
    )


@router.callback_query(F.data.startswith("lt:l:"), StateFilter(LessonTaskFSM.lesson))
async def cb_pick_lesson(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    idx = int(cb.data.split(":")[2])
    titles = data.get("lesson_titles", [])
    if idx >= len(titles):
        return
    await state.update_data(lesson_index=idx)
    await _generate_and_preview(cb, state, bot)


# ─── Generatsiya + preview ───────────────────────────────────────────────────


async def _generate_and_preview(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    track = data["track"]
    module = data["module"]
    block = data["block"]
    idx = data["lesson_index"]
    group_name = data["group_name"]

    lesson = curriculum.get_lesson(track, module, block, idx)
    if lesson is None:
        await cb.message.edit_text("⚠️ Dars topilmadi. Qaytadan urinib ko'ring: /vazifa")
        await state.clear()
        return

    if not ai_service.is_configured():
        await cb.message.edit_text(
            "⚠️ AI sozlanmagan (ANTHROPIC_API_KEY yo'q).\n"
            "Vazifa generatsiyasi ishlamaydi — administrator bilan bog'laning."
        )
        await state.clear()
        return

    safe_title = html.escape(lesson.title)
    await cb.message.edit_text(
        f"⏳ <b>AI vazifa tuzmoqda...</b>\n\n📖 {safe_title}\n🏫 {html.escape(group_name)}\n\nBir oz kuting..."
    )

    try:
        text = await ai_service.generate_assignment(
            track_label=curriculum.TRACK_LABELS.get(track, track),
            module=module,
            block=block,
            lesson_name=lesson.name,
            metodika=lesson.metodika,
            academy=lesson.academy,
            group_name=group_name,
        )
    except Exception as e:
        logger.exception("AI vazifa generatsiya xatosi: %s", e)
        await cb.message.edit_text(f"❌ AI xatosi: <code>{e}</code>\n\nQayta urinib ko'ring: /vazifa")
        await state.clear()
        return

    await state.update_data(generated_text=text)
    await state.set_state(LessonTaskFSM.preview)

    chat_id = cb.message.chat.id
    header = (
        f"📋 <b>Tayyor vazifa (preview)</b>\n"
        f"📖 {safe_title}\n"
        f"🏫 {html.escape(group_name)} · {html.escape(module)} · {html.escape(block)}\n"
        f"{'─' * 20}"
    )
    await cb.message.edit_text(header)
    # AI matnini (uzun bo'lishi mumkin) alohida yuboramiz + tugmalar oxirgi bo'lakda
    await _send_long(bot, chat_id, text, reply_markup=_kb_preview())


@router.callback_query(F.data == "lt:regen", StateFilter(LessonTaskFSM.preview))
async def cb_regen(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    # Preview tugmalarini olib tashlaymiz va qayta generatsiya qilamiz
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _generate_and_preview(cb, state, bot)


@router.callback_query(F.data == "lt:send", StateFilter(LessonTaskFSM.preview))
async def cb_send(cb: CallbackQuery, state: FSMContext, bot: Bot, db: DatabaseService) -> None:
    data = await state.get_data()
    text = data.get("generated_text", "")
    group_name = data.get("group_name", "")
    if not text:
        await cb.message.edit_text("⚠️ Matn topilmadi. Qaytadan: /vazifa")
        await state.clear()
        return

    chat_id = await _resolve_group_chat(db, group_name)
    if chat_id is None:
        await cb.message.edit_text(
            f"❌ '{group_name}' guruhining chat ID si topilmadi.\n"
            f"Bot guruhga qo'shilganini va admin panelda ro'yxatda ekanini tekshiring."
        )
        await state.clear()
        return

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    try:
        await _send_long(bot, chat_id, f"📝 Yangi uy vazifasi!\n\n{text}")
        await cb.message.answer(f"✅ <b>Vazifa yuborildi!</b>\n🏫 Guruh: <b>{group_name}</b>")
        logger.info("Dars vazifasi yuborildi → '%s' (%s)", group_name, chat_id)
    except Exception as e:
        logger.exception("Vazifani guruhga yuborish xatosi: %s", e)
        await cb.message.answer(f"❌ Yuborishda xato: <code>{e}</code>")
    finally:
        await state.clear()


@router.callback_query(F.data == "lt:cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await cb.message.edit_text("❌ Bekor qilindi.")
    except Exception:
        pass


# ─── Orqaga navigatsiya ──────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("lt:back:"))
async def cb_back(cb: CallbackQuery, state: FSMContext, db: DatabaseService) -> None:
    step = cb.data.split(":")[2]
    data = await state.get_data()

    if step == "groups":
        await _show_groups(cb, state, db)
        return

    if step == "modules":
        modules = data.get("module_list", [])
        await state.set_state(LessonTaskFSM.module)
        await cb.message.edit_text(
            f"🏫 Guruh: <b>{data.get('group_name', '')}</b>\n\nQaysi <b>modul</b>ni o'tdingiz?",
            reply_markup=_kb_modules(modules),
        )
        return

    if step == "blocks":
        blocks = data.get("block_list", [])
        await state.set_state(LessonTaskFSM.block)
        await cb.message.edit_text(
            f"🏫 <b>{data.get('group_name', '')}</b> · 📦 <b>{data.get('module', '')}</b>\n\n"
            f"Qaysi <b>blok</b>ni o'tdingiz?",
            reply_markup=_kb_blocks(blocks),
        )
        return
