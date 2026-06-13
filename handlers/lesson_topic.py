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
import uuid

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import ai_service
import curriculum
from config import ADMIN_IDS, WEBAPP_URL
from database import AudienceType, DatabaseService

logger = logging.getLogger(__name__)
router = Router()

_TG_LIMIT = 4000  # xavfsiz chegara (Telegram 4096)

# Vazifa oxiriga qo'shiladigan "qanday topshirish" yo'riqnomasi (2 tilli)
_SUBMIT_GUIDE = (
    "\n\n━━━━━━━━━━━━━━━━━━━\n"
    "📤 VAZIFANI QANDAY TOPSHIRASIZ?\n"
    "Ishingizni shu guruhga #vazifa so'zi bilan yuboring:\n"
    "• 🖼 rasm (skrinshot)  • 📦 ZIP arxiv  • 🔗 havola  • 💻 kod\n"
    "🤖 AI ishingizni tekshiradi va bahosiga qarab 30 gacha XP beradi.\n\n"
    "🇷🇺 КАК СДАТЬ ЗАДАНИЕ?\n"
    "Отправьте работу в эту группу со словом #vazifa:\n"
    "• 🖼 фото  • 📦 ZIP  • 🔗 ссылка  • 💻 код\n"
    "🤖 ИИ проверит работу и начислит до 30 XP."
)


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


class LessonTaskFSM(StatesGroup):
    group = State()
    module = State()
    block = State()
    lesson = State()
    custom_topic = State()  # ustoz mavzu nomini qo'lda yozadi (Pro guruhlar uchun)
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
    # Pro guruhlar yoki o'quv dasturida yo'q mavzular uchun — qo'lda yozish
    rows.append([InlineKeyboardButton(text="✍️ Mavzu nomini o'zim yozaman", callback_data="lt:custom")])
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
    """Guruh tanlangach yo'nalishni aniqlab modullarni ko'rsatadi.

    O'quv dasturi topilmasa (masalan Pro guruhlar) — faqat "mavzuni o'zim yozaman"
    yo'li ko'rsatiladi.
    """
    track = curriculum.track_for_group(group_name)
    modules = curriculum.list_modules(track)
    track_label = curriculum.TRACK_LABELS.get(track, track)

    await state.update_data(group_name=group_name, track=track, module_list=modules)
    await state.set_state(LessonTaskFSM.module)

    if not modules:
        await cb.message.edit_text(
            f"🏫 Guruh: <b>{group_name}</b>\n"
            f"🧭 Yo'nalish: <b>{track_label}</b>\n\n"
            "ℹ️ Bu guruh uchun tayyor o'quv dasturi yo'q (Pro/maxsus guruh).\n"
            "Mavzu nomini o'zingiz yozing — bot vazifa va UI namunasini tuzadi.",
            reply_markup=_kb_modules(modules),  # faqat "✍️ Mavzu nomini o'zim yozaman" + Bekor
        )
        return

    await cb.message.edit_text(
        f"🏫 Guruh: <b>{group_name}</b>\n"
        f"🧭 Yo'nalish: <b>{track_label}</b>\n\n"
        f"Qaysi <b>modul</b>ni o'tdingiz? Yoki mavzuni o'zingiz yozing.",
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
async def cb_pick_lesson(cb: CallbackQuery, state: FSMContext, bot: Bot, db: DatabaseService) -> None:
    data = await state.get_data()
    idx = int(cb.data.split(":")[2])
    titles = data.get("lesson_titles", [])
    if idx >= len(titles):
        return

    track, module, block, group_name = data["track"], data["module"], data["block"], data["group_name"]
    lesson = curriculum.get_lesson(track, module, block, idx)
    if lesson is None:
        await cb.message.edit_text("⚠️ Dars topilmadi. Qaytadan urinib ko'ring: /vazifa")
        await state.clear()
        return

    params = {
        "group_name": group_name,
        "track_label": curriculum.TRACK_LABELS.get(track, track),
        "module_label": module,
        "block_label": block,
        "lesson_name": lesson.name,
        "display_title": lesson.title,
        "metodika": lesson.metodika,
        "academy": lesson.academy,
        "extra_note": "",
    }
    await _run_generation(cb.message, state, bot, db, params)


# ─── Mavzuni qo'lda yozish (Pro guruhlar / o'quv dasturida yo'q mavzu) ────────


@router.callback_query(F.data == "lt:custom", StateFilter(LessonTaskFSM.module))
async def cb_custom_start(cb: CallbackQuery, state: FSMContext) -> None:
    """Ustoz mavzu nomini qo'lda yozishini so'raydi."""
    data = await state.get_data()
    group_name = data.get("group_name", "")
    await state.set_state(LessonTaskFSM.custom_topic)
    await cb.message.edit_text(
        f"✍️ <b>Mavzu nomini yozing</b>\n🏫 Guruh: <b>{html.escape(group_name)}</b>\n\n"
        "Masalan: <i>JavaScript massivlar (array) va ularning metodlari</i>\n\n"
        "Bot shu mavzudan vazifa va UI namunasini tuzadi.\n"
        "Bekor qilish: /cancel",
    )


@router.message(Command("cancel"), StateFilter(LessonTaskFSM))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """/vazifa oqimining istalgan bosqichida bekor qilish."""
    await state.clear()
    await message.answer("❌ Bekor qilindi.")


@router.message(StateFilter(LessonTaskFSM.custom_topic), F.text)
async def on_custom_topic(message: Message, state: FSMContext, bot: Bot, db: DatabaseService) -> None:
    """Ustoz yozgan mavzu nomidan vazifa + UI generatsiya qiladi."""
    if not _is_admin(message.from_user.id):
        return
    topic = (message.text or "").strip()
    if topic.startswith("/"):
        return  # buyruq — boshqa handlerga
    if len(topic) < 3:
        await message.answer("⚠️ Mavzu nomi juda qisqa. Iltimos, to'liqroq yozing.")
        return

    data = await state.get_data()
    track = data.get("track", "frontend")
    group_name = data.get("group_name", "")
    params = {
        "group_name": group_name,
        "track_label": curriculum.TRACK_LABELS.get(track, track),
        "module_label": "Ustoz mavzusi",
        "block_label": "—",
        "lesson_name": topic,
        "display_title": topic,
        "metodika": "",
        "academy": "",
        "extra_note": (
            "Bu mavzuni ustoz o'zi belgiladi — o'quv dasturida tayyor metodika yo'q. "
            "Mavzu nomidan kelib chiqib, qisqa va professional vazifa tuz."
        ),
    }
    status_msg = await message.answer("⏳ <b>Tayyorlanmoqda...</b>")
    await _run_generation(status_msg, state, bot, db, params)


# ─── Generatsiya + preview (umumiy yadro) ────────────────────────────────────


async def _build_ui_link(
    db: DatabaseService,
    *,
    lesson_name: str,
    display_title: str,
    metodika: str,
    academy: str,
    group_name: str,
    assignment_text: str,
) -> str | None:
    """Maqsadli UI namunasini AI bilan generatsiya qilib, saqlaydi va havola qaytaradi.

    WEBAPP_URL yo'q yoki xato bo'lsa None qaytaradi (vazifa matni baribir yuboriladi).
    """
    if not WEBAPP_URL:
        return None
    try:
        ui_html = await ai_service.generate_assignment_ui(
            lesson_name=lesson_name,
            metodika=metodika,
            academy=academy,
            group_name=group_name,
            assignment_text=assignment_text,
        )
        task_id = uuid.uuid4().hex[:12]
        await db.save_task_ui(task_id, display_title, group_name, ui_html)
        return f"{WEBAPP_URL.rstrip('/')}/task/{task_id}"
    except Exception as e:
        logger.warning("Vazifa UI generatsiya/saqlash xatosi: %s", e)
        return None


async def _run_generation(
    status_msg: Message,
    state: FSMContext,
    bot: Bot,
    db: DatabaseService,
    params: dict,
) -> None:
    """Vazifa matni + UI namunasini generatsiya qilib preview ko'rsatadi.

    status_msg — holat ko'rsatiladigan (tahrirlanadigan) xabar. params regen uchun
    state'ga saqlanadi.
    """
    if not ai_service.is_configured():
        await status_msg.edit_text(
            "⚠️ AI sozlanmagan (ANTHROPIC_API_KEY yo'q).\n"
            "Vazifa generatsiyasi ishlamaydi — administrator bilan bog'laning."
        )
        await state.clear()
        return

    group_name = params["group_name"]
    display_title = params["display_title"]
    safe_title = html.escape(display_title)
    await status_msg.edit_text(
        f"⏳ <b>AI vazifa tuzmoqda...</b>\n\n📖 {safe_title}\n🏫 {html.escape(group_name)}\n\nBir oz kuting..."
    )

    try:
        text = await ai_service.generate_assignment(
            track_label=params["track_label"],
            module=params["module_label"],
            block=params["block_label"],
            lesson_name=params["lesson_name"],
            metodika=params["metodika"],
            academy=params["academy"],
            group_name=group_name,
            extra_note=params.get("extra_note", ""),
        )
    except Exception as e:
        logger.exception("AI vazifa generatsiya xatosi: %s", e)
        await status_msg.edit_text(f"❌ AI xatosi: <code>{e}</code>\n\nQayta urinib ko'ring: /vazifa")
        await state.clear()
        return

    # Vazifa bilan birga maqsadli UI namunasini ham tuzamiz (havola sifatida)
    await status_msg.edit_text(f"⏳ <b>AI UI namunasini chizmoqda...</b>\n\n📖 {safe_title}\n\nDeyarli tayyor...")
    ui_link = await _build_ui_link(
        db,
        lesson_name=params["lesson_name"],
        display_title=display_title,
        metodika=params["metodika"],
        academy=params["academy"],
        group_name=group_name,
        assignment_text=text,
    )

    await state.update_data(generated_text=text, generated_ui_link=ui_link, gen_params=params)
    await state.set_state(LessonTaskFSM.preview)

    chat_id = status_msg.chat.id
    header = (
        f"📋 <b>Tayyor vazifa (preview)</b>\n"
        f"📖 {safe_title}\n"
        f"🏫 {html.escape(group_name)} · {html.escape(params['module_label'])} · "
        f"{html.escape(params['block_label'])}\n"
    )
    if ui_link:
        header += f"🎨 UI namuna: {html.escape(ui_link)}\n"
    else:
        header += "🎨 UI namuna: <i>yaratilmadi (WEBAPP_URL/AI tekshiring)</i>\n"
    header += "─" * 20
    await status_msg.edit_text(header)
    # AI matnini (uzun bo'lishi mumkin) alohida yuboramiz + tugmalar oxirgi bo'lakda
    await _send_long(bot, chat_id, text, reply_markup=_kb_preview())


@router.callback_query(F.data == "lt:regen", StateFilter(LessonTaskFSM.preview))
async def cb_regen(cb: CallbackQuery, state: FSMContext, bot: Bot, db: DatabaseService) -> None:
    # Preview tugmalarini olib tashlaymiz va qayta generatsiya qilamiz
    data = await state.get_data()
    params = data.get("gen_params")
    if not params:
        await cb.answer("Qayta yaratish uchun ma'lumot yo'q. /vazifa", show_alert=True)
        return
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _run_generation(cb.message, state, bot, db, params)


@router.callback_query(F.data == "lt:send", StateFilter(LessonTaskFSM.preview))
async def cb_send(cb: CallbackQuery, state: FSMContext, bot: Bot, db: DatabaseService) -> None:
    data = await state.get_data()
    text = data.get("generated_text", "")
    ui_link = data.get("generated_ui_link")
    group_name = data.get("group_name", "")
    display_title = data.get("gen_params", {}).get("display_title", "")
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

    header = "📚📚📚📚📚📚📚📚📚📚📚\n     📌 UYGA VAZIFA 📌\n📚📚📚📚📚📚📚📚📚📚📚"
    body = f"{header}\n\n{text}"
    if ui_link:
        body += f"\n\n🎨 Namuna UI — shu ko'rinishni yasang:\n{ui_link}"
    body += _SUBMIT_GUIDE

    try:
        await _send_long(bot, chat_id, body)
        # Guruhning joriy vazifasini saqlaymiz — #vazifa AI tekshiruvi shunga qarab baholaydi
        try:
            await db.set_group_current_task(group_name, display_title or "Uy vazifasi", text)
        except Exception as e:
            logger.warning("Joriy vazifani saqlash xatosi: %s", e)
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
