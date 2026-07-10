"""
handlers/topic_day.py — "Bugungi mavzu" oqimi (faqat admin).

Seshanba/Payshanba/Shanba 16:30 da scheduler adminga "Bugun qaysi mavzuni
o'tdingiz?" xabarini yuboradi (scheduler.send_topic_day_prompt). Oqim:
  1. Admin tugmani bosadi (yoki /mavzu yozadi).
  2. Yo'nalish (track) → Modul → Blok → Mavzu tanlaydi (curriculum.py).
  3. Video darslar kanalidagi videolar ro'yxatidan videoni tanlaydi.
  4. Guruhni tanlaydi.
  5. Preview → tasdiqlasa, guruhga uyga vazifa (mavzu + video havola) yuboriladi.

Kanal videolari qayerdan keladi:
  - Bot kanalda admin — yangi video postlar channel_post orqali avtomatik saqlanadi.
  - Eski videolarni admin kanaldan botga (shaxsiy chatga) forward qilib qo'shadi.

callback_data sxemasi (ro'yxatlar FSM state'da, callback'da indekslar):
  td:start      — oqimni boshlash (scheduler prompti tugmasi)
  td:t:<idx>    — yo'nalish (track) tanlash
  td:m:<idx>    — modul tanlash
  td:b:<idx>    — blok tanlash
  td:l:<idx>    — mavzu (dars) tanlash
  td:v:<idx>    — video tanlash
  td:v:skip     — videosiz davom etish
  td:gr:<idx>   — guruh tanlash
  td:send       — guruhga yuborish
  td:cancel     — bekor qilish
  td:back:<step> — orqaga (tracks|modules|blocks|lessons|videos)
"""

import asyncio
import html
import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import curriculum
from config import ADMIN_IDS
from database import AudienceType, DatabaseService

logger = logging.getLogger(__name__)
router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


class TopicDayFSM(StatesGroup):
    track = State()
    module = State()
    block = State()
    lesson = State()
    video = State()
    group = State()
    preview = State()


# ─── Kanal videolarini yig'ish ────────────────────────────────────────────────


def _video_title_from_message(msg: Message) -> str:
    """Kanal postidan video nomini ajratadi: caption 1-qatori → fayl nomi → fallback."""
    caption = (msg.caption or "").strip()
    if caption:
        return caption.split("\n", 1)[0].strip()[:300]
    if msg.video and msg.video.file_name:
        return msg.video.file_name[:300]
    if msg.document and msg.document.file_name:
        return msg.document.file_name[:300]
    return f"Video dars #{msg.message_id}"


def _is_video_message(msg: Message) -> bool:
    if msg.video:
        return True
    doc = msg.document
    return bool(doc and (doc.mime_type or "").startswith("video/"))


@router.channel_post(F.video | F.document)
async def on_channel_video(msg: Message, db: DatabaseService) -> None:
    """Bot admin bo'lgan kanaldagi yangi video post — avtomatik saqlanadi."""
    if not _is_video_message(msg):
        return
    is_new = await db.save_channel_video(
        chat_id=msg.chat.id,
        message_id=msg.message_id,
        title=_video_title_from_message(msg),
        channel_username=msg.chat.username or "",
        channel_title=msg.chat.title or "",
    )
    if is_new:
        logger.info("Kanal videosi saqlandi: '%s' (%s/%s)", _video_title_from_message(msg), msg.chat.id, msg.message_id)


# Ommaviy forward (100 tagacha birdan) — har videoga alohida javob o'rniga
# forwardlar to'xtagach BITTA umumiy hisobot yuboriladi (debounce).
_backfill_stats: dict[int, dict] = {}  # user_id → {"new", "dup", "hidden", "task"}
_BACKFILL_SUMMARY_DELAY = 2.5  # soniya — oxirgi forwarddan keyin kutish


async def _send_backfill_summary(user_id: int, msg: Message) -> None:
    """Forward oqimi to'xtagach umumiy hisobot yuboradi."""
    await asyncio.sleep(_BACKFILL_SUMMARY_DELAY)
    stats = _backfill_stats.pop(user_id, None)
    if not stats:
        return
    lines: list[str] = []
    if stats["new"]:
        lines.append(f"✅ <b>{stats['new']} ta</b> yangi video ro'yxatga qo'shildi.")
    if stats["dup"]:
        lines.append(f"ℹ️ {stats['dup']} ta video allaqachon ro'yxatda edi.")
    if stats["hidden"]:
        lines.append(
            f"⚠️ {stats['hidden']} ta forwardda kanal ma'lumoti yashirilgan — "
            'forward qilishda "Hide sender name" ni o\'chirib qayta yuboring.'
        )
    if lines:
        lines.append("\n📖 Ro'yxatni ko'rish/ishlatish: /mavzu")
        try:
            await msg.answer("\n".join(lines))
        except Exception:
            pass


@router.message(F.chat.type == "private", F.forward_origin, F.video | F.document)
async def on_forwarded_channel_video(msg: Message, db: DatabaseService) -> None:
    """Admin kanaldagi eski videoni botga forward qilsa — ro'yxatga qo'shiladi.

    Ko'p videoni birdan forward qilish mumkin (Telegram'da 100 tagacha belgilab) —
    bot hammasini saqlab, oxirida bitta umumiy hisobot yuboradi.
    """
    if not _is_admin(msg.from_user.id):
        return
    if not _is_video_message(msg):
        return

    user_id = msg.from_user.id
    stats = _backfill_stats.setdefault(user_id, {"new": 0, "dup": 0, "hidden": 0, "task": None})

    origin = msg.forward_origin
    origin_chat = getattr(origin, "chat", None)
    if origin_chat is None or origin_chat.type != "channel":
        stats["hidden"] += 1
    else:
        is_new = await db.save_channel_video(
            chat_id=origin_chat.id,
            message_id=getattr(origin, "message_id", 0) or 0,
            title=_video_title_from_message(msg),
            channel_username=origin_chat.username or "",
            channel_title=origin_chat.title or "",
        )
        stats["new" if is_new else "dup"] += 1

    # Debounce: har yangi forwardda taymerni qayta boshlaymiz
    task = stats.get("task")
    if task and not task.done():
        task.cancel()
    stats["task"] = asyncio.create_task(_send_backfill_summary(user_id, msg))


# ─── Klaviaturalar ────────────────────────────────────────────────────────────


def _kb_back_cancel(back_step: str | None = None) -> list[list[InlineKeyboardButton]]:
    row: list[InlineKeyboardButton] = []
    if back_step:
        row.append(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"td:back:{back_step}"))
    row.append(InlineKeyboardButton(text="❌ Bekor", callback_data="td:cancel"))
    return [row]


def _kb_index_list(items: list[str], prefix: str, icon: str, back_step: str | None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{icon} {t}"[:60], callback_data=f"td:{prefix}:{i}")] for i, t in enumerate(items)
    ]
    rows += _kb_back_cancel(back_step)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_videos(titles: list[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📺 {t}"[:60], callback_data=f"td:v:{i}")] for i, t in enumerate(titles)]
    rows.append([InlineKeyboardButton(text="⏭ Videosiz davom etish", callback_data="td:v:skip")])
    rows += _kb_back_cancel("lessons")
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_preview() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Guruhga yuborish", callback_data="td:send")],
            [
                InlineKeyboardButton(text="⬅️ Orqaga", callback_data="td:back:groups"),
                InlineKeyboardButton(text="❌ Bekor", callback_data="td:cancel"),
            ],
        ]
    )


def _video_link(chat_id: int, message_id: int, username: str) -> str:
    """Kanal postiga havola: public kanal → t.me/<username>/<id>, private → t.me/c/..."""
    if username:
        return f"https://t.me/{username}/{message_id}"
    internal = str(chat_id).removeprefix("-100")
    return f"https://t.me/c/{internal}/{message_id}"


# ─── Oqim bosqichlari ─────────────────────────────────────────────────────────


async def _show_tracks(message_or_cb, state: FSMContext) -> None:
    """1-bosqich: yo'nalish tanlash (bitta bo'lsa — to'g'ridan modullarga)."""
    tracks = curriculum.available_tracks()
    if not tracks:
        text = "⚠️ O'quv dasturi fayllari topilmadi (Mavzular/ papkasi bo'sh)."
        if isinstance(message_or_cb, CallbackQuery):
            await message_or_cb.message.edit_text(text)
        else:
            await message_or_cb.answer(text)
        await state.clear()
        return

    await state.update_data(track_list=tracks)
    if len(tracks) == 1:
        await _enter_track(message_or_cb, state, tracks[0])
        return

    labels = [curriculum.TRACK_LABELS.get(t, t) for t in tracks]
    await state.set_state(TopicDayFSM.track)
    text = "📚 <b>Bugun qaysi mavzuni o'tdingiz?</b>\n\nAvval yo'nalishni tanlang:"
    kb = _kb_index_list(labels, "t", "🧭", None)
    if isinstance(message_or_cb, CallbackQuery):
        await message_or_cb.message.edit_text(text, reply_markup=kb)
    else:
        await message_or_cb.answer(text, reply_markup=kb)


async def _enter_track(message_or_cb, state: FSMContext, track: str) -> None:
    """Yo'nalish tanlangach modullarni ko'rsatadi."""
    modules = curriculum.list_modules(track)
    track_label = curriculum.TRACK_LABELS.get(track, track)
    await state.update_data(track=track, module_list=modules)
    await state.set_state(TopicDayFSM.module)
    text = f"🧭 Yo'nalish: <b>{html.escape(track_label)}</b>\n\nQaysi <b>modul</b>ni o'tdingiz?"
    kb = _kb_index_list(modules, "m", "📦", "tracks")
    if isinstance(message_or_cb, CallbackQuery):
        await message_or_cb.message.edit_text(text, reply_markup=kb)
    else:
        await message_or_cb.answer(text, reply_markup=kb)


@router.message(Command("mavzu"))
async def cmd_mavzu(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("❌ Bu buyruq faqat adminlar uchun!")
        return
    await state.clear()
    await _show_tracks(message, state)


@router.callback_query(F.data == "td:start")
async def cb_start(cb: CallbackQuery, state: FSMContext) -> None:
    """Scheduler promptidagi tugma — oqimni boshlaydi."""
    if not _is_admin(cb.from_user.id):
        return
    await state.clear()
    await _show_tracks(cb, state)


@router.callback_query(F.data.startswith("td:t:"), StateFilter(TopicDayFSM.track))
async def cb_pick_track(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    tracks = data.get("track_list", [])
    idx = int(cb.data.split(":")[2])
    if idx >= len(tracks):
        return
    await _enter_track(cb, state, tracks[idx])


@router.callback_query(F.data.startswith("td:m:"), StateFilter(TopicDayFSM.module))
async def cb_pick_module(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    modules = data.get("module_list", [])
    idx = int(cb.data.split(":")[2])
    if idx >= len(modules):
        return
    module = modules[idx]
    blocks = curriculum.list_blocks(data["track"], module)
    await state.update_data(module=module, block_list=blocks)
    await state.set_state(TopicDayFSM.block)
    await cb.message.edit_text(
        f"📦 <b>{html.escape(module)}</b>\n\nQaysi <b>blok</b>ni o'tdingiz?",
        reply_markup=_kb_index_list(blocks, "b", "🧩", "modules"),
    )


@router.callback_query(F.data.startswith("td:b:"), StateFilter(TopicDayFSM.block))
async def cb_pick_block(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    blocks = data.get("block_list", [])
    idx = int(cb.data.split(":")[2])
    if idx >= len(blocks):
        return
    block = blocks[idx]
    lessons = curriculum.list_lessons(data["track"], data["module"], block)
    titles = [le.title for le in lessons]
    await state.update_data(block=block, lesson_titles=titles)
    await state.set_state(TopicDayFSM.lesson)
    await cb.message.edit_text(
        f"📦 <b>{html.escape(data['module'])}</b> · 🧩 <b>{html.escape(block)}</b>\n\nQaysi <b>mavzu</b>ni o'tdingiz?",
        reply_markup=_kb_index_list(titles, "l", "📖", "blocks"),
    )


async def _show_videos(cb: CallbackQuery, state: FSMContext, db: DatabaseService) -> None:
    """Mavzu tanlangach — kanaldagi video darslar ro'yxati."""
    data = await state.get_data()
    videos = await db.get_channel_videos(limit=60)
    await state.update_data(video_ids=[v.id for v in videos])
    await state.set_state(TopicDayFSM.video)

    lesson_title = data.get("lesson_title", "")
    if not videos:
        await cb.message.edit_text(
            f"📖 Mavzu: <b>{html.escape(lesson_title)}</b>\n\n"
            "📭 Kanal videolari ro'yxati hali bo'sh.\n"
            "Video qo'shish uchun kanaldagi videoni shu botga <b>forward</b> qiling "
            "(yangi kanal postlari avtomatik qo'shiladi).\n\n"
            "Hozircha videosiz davom etishingiz mumkin:",
            reply_markup=_kb_videos([]),
        )
        return

    titles = [v.title or f"Video #{v.message_id}" for v in videos]
    await state.update_data(video_titles=titles)
    await cb.message.edit_text(
        f"📖 Mavzu: <b>{html.escape(lesson_title)}</b>\n\n"
        f"📺 Kanaldagi qaysi <b>video dars</b>ni ko'rish kerak? ({len(titles)} ta)",
        reply_markup=_kb_videos(titles),
    )


@router.callback_query(F.data.startswith("td:l:"), StateFilter(TopicDayFSM.lesson))
async def cb_pick_lesson(cb: CallbackQuery, state: FSMContext, db: DatabaseService) -> None:
    data = await state.get_data()
    titles = data.get("lesson_titles", [])
    idx = int(cb.data.split(":")[2])
    if idx >= len(titles):
        return
    await state.update_data(lesson_title=titles[idx])
    await _show_videos(cb, state, db)


async def _show_groups(cb: CallbackQuery, state: FSMContext, db: DatabaseService) -> None:
    """Video tanlangach — qaysi guruhga yuborishni so'raydi."""
    groups = await db.get_all_groups()
    names: list[str] = []
    seen: set[str] = set()
    for g in groups:
        if g.is_active and g.audience == AudienceType.STUDENT and g.name not in seen:
            seen.add(g.name)
            names.append(g.name)
    names.sort()

    if not names:
        await cb.message.edit_text("📭 Aktiv o'quvchi guruhlari topilmadi.\nAvval guruh qo'shing (admin panel).")
        await state.clear()
        return

    await state.update_data(group_list=names)
    await state.set_state(TopicDayFSM.group)
    await cb.message.edit_text(
        "🏫 Qaysi <b>guruhga</b> yuboramiz?",
        reply_markup=_kb_index_list(names, "gr", "🏫", "videos"),
    )


@router.callback_query(F.data.startswith("td:v:"), StateFilter(TopicDayFSM.video))
async def cb_pick_video(cb: CallbackQuery, state: FSMContext, db: DatabaseService) -> None:
    raw = cb.data.split(":")[2]
    if raw == "skip":
        await state.update_data(video_idx=None)
        await _show_groups(cb, state, db)
        return
    data = await state.get_data()
    titles = data.get("video_titles", [])
    idx = int(raw)
    if idx >= len(titles):
        return
    await state.update_data(video_idx=idx)
    await _show_groups(cb, state, db)


def _build_group_message(
    lesson_title: str,
    module: str,
    block: str,
    video_title: str | None,
    video_link: str | None,
) -> str:
    """Guruhga yuboriladigan uyga vazifa matni (UZ + RU)."""
    safe_lesson = html.escape(lesson_title)
    lines = [
        "📚📚📚📚📚📚📚📚📚📚📚",
        "     📌 UYGA VAZIFA 📌",
        "📚📚📚📚📚📚📚📚📚📚📚",
        "",
        f"📖 Mavzu: <b>{safe_lesson}</b>",
        f"📦 {html.escape(module)} · {html.escape(block)}",
    ]
    if video_title and video_link:
        lines += [
            "",
            f"📺 Video dars: <b>{html.escape(video_title)}</b>",
            f"👉 {video_link}",
            "",
            "✅ Videoni to'liq ko'rib chiqing va mavzu bo'yicha vazifani bajaring.",
        ]
    else:
        lines += ["", "✅ Mavzu bo'yicha uyga vazifani bajaring."]
    lines += [
        "",
        "🇷🇺 <b>ДОМАШНЕЕ ЗАДАНИЕ</b>",
        f"Тема: <b>{safe_lesson}</b>",
    ]
    if video_title and video_link:
        lines.append("Полностью посмотрите видеоурок по ссылке выше и выполните задание по теме.")
    else:
        lines.append("Выполните домашнее задание по теме.")
    return "\n".join(lines)


@router.callback_query(F.data.startswith("td:gr:"), StateFilter(TopicDayFSM.group))
async def cb_pick_group(cb: CallbackQuery, state: FSMContext, db: DatabaseService) -> None:
    data = await state.get_data()
    names = data.get("group_list", [])
    idx = int(cb.data.split(":")[2])
    if idx >= len(names):
        return
    group_name = names[idx]

    # Video ma'lumotini tayyorlaymiz
    video_title = video_link = None
    v_idx = data.get("video_idx")
    video_ids = data.get("video_ids") or []
    if v_idx is not None and 0 <= v_idx < len(video_ids):
        videos = await db.get_channel_videos(limit=60)
        video = next((v for v in videos if v.id == video_ids[v_idx]), None)
        if video:
            video_title = video.title or f"Video #{video.message_id}"
            video_link = _video_link(video.chat_id, video.message_id, video.channel_username)

    text = _build_group_message(
        lesson_title=data.get("lesson_title", ""),
        module=data.get("module", ""),
        block=data.get("block", ""),
        video_title=video_title,
        video_link=video_link,
    )
    await state.update_data(group_name=group_name, final_text=text)
    await state.set_state(TopicDayFSM.preview)
    await cb.message.edit_text(
        f"👀 <b>Preview</b> — 🏫 <b>{html.escape(group_name)}</b> guruhiga yuboriladi:\n{'─' * 20}\n\n{text}",
        reply_markup=_kb_preview(),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "td:send", StateFilter(TopicDayFSM.preview))
async def cb_send(cb: CallbackQuery, state: FSMContext, db: DatabaseService) -> None:
    data = await state.get_data()
    group_name = data.get("group_name", "")
    text = data.get("final_text", "")
    if not text or not group_name:
        await cb.message.edit_text("⚠️ Ma'lumot topilmadi. Qaytadan: /mavzu")
        await state.clear()
        return

    groups = await db.get_all_groups()
    chat_id = None
    for g in groups:
        if g.name == group_name and g.is_active and g.audience == AudienceType.STUDENT:
            chat_id = g.chat_id
            break
    if chat_id is None:
        await cb.message.edit_text(f"❌ '{html.escape(group_name)}' guruhining chat ID si topilmadi.")
        await state.clear()
        return

    try:
        await cb.bot.send_message(chat_id, text, disable_web_page_preview=False)
        await cb.message.edit_text(f"✅ <b>Uyga vazifa yuborildi!</b>\n🏫 Guruh: <b>{html.escape(group_name)}</b>")
        logger.info("Bugungi mavzu vazifasi yuborildi → '%s' (%s)", group_name, chat_id)
    except Exception as e:
        logger.exception("Bugungi mavzu vazifasini yuborish xatosi: %s", e)
        await cb.message.edit_text(f"❌ Yuborishda xato: <code>{html.escape(str(e))}</code>")
    finally:
        await state.clear()


@router.callback_query(F.data == "td:cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await cb.message.edit_text("❌ Bekor qilindi.")
    except Exception:
        pass


# ─── Orqaga navigatsiya ──────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("td:back:"))
async def cb_back(cb: CallbackQuery, state: FSMContext, db: DatabaseService) -> None:
    step = cb.data.split(":")[2]
    data = await state.get_data()

    if step == "tracks":
        await _show_tracks(cb, state)
        return

    if step == "modules":
        await _enter_track(cb, state, data.get("track", "frontend"))
        return

    if step == "blocks":
        blocks = data.get("block_list", [])
        await state.set_state(TopicDayFSM.block)
        await cb.message.edit_text(
            f"📦 <b>{html.escape(data.get('module', ''))}</b>\n\nQaysi <b>blok</b>ni o'tdingiz?",
            reply_markup=_kb_index_list(blocks, "b", "🧩", "modules"),
        )
        return

    if step == "lessons":
        titles = data.get("lesson_titles", [])
        await state.set_state(TopicDayFSM.lesson)
        await cb.message.edit_text(
            f"📦 <b>{html.escape(data.get('module', ''))}</b> · 🧩 <b>{html.escape(data.get('block', ''))}</b>\n\n"
            f"Qaysi <b>mavzu</b>ni o'tdingiz?",
            reply_markup=_kb_index_list(titles, "l", "📖", "blocks"),
        )
        return

    if step == "videos":
        await _show_videos(cb, state, db)
        return

    if step == "groups":
        await _show_groups(cb, state, db)
        return
