"""
keyboards.py — Barcha inline keyboard layoutlari.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import CHANNEL_LINK, WEBAPP_URL
from database import AudienceType, BotChat, Group, GroupType


def kb_admin_panel() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if WEBAPP_URL:
        builder.row(
            InlineKeyboardButton(
                text="🛠 Admin Mini App",
                web_app=WebAppInfo(url=f"{WEBAPP_URL.rstrip('/')}/webapp/admin-mini.html"),
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="🖥 Admin Panel (eski)",
                web_app=WebAppInfo(url=f"{WEBAPP_URL.rstrip('/')}/webapp/admin.html"),
            )
        )
    builder.row(
        InlineKeyboardButton(text="📋 Guruhlar", callback_data="admin:list:all"),
        InlineKeyboardButton(text="➕ Qo'shish", callback_data="admin:add_start"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Holat", callback_data="admin:status"),
        InlineKeyboardButton(text="🚀 Test", callback_data="admin:test_send"),
    )
    builder.row(
        InlineKeyboardButton(text="👥 O'quvchilar", callback_data="admin:students:all"),
        InlineKeyboardButton(text="📊 Statistika", callback_data="admin:stats"),
    )
    builder.row(
        InlineKeyboardButton(text="📝 Uy vazifasi", callback_data="admin:hw_menu"),
        InlineKeyboardButton(text="📅 Jadval", callback_data="admin:set_schedule"),
    )
    builder.row(
        InlineKeyboardButton(text="📢 O'quvchilarga", callback_data="admin:grp_msg:student"),
        InlineKeyboardButton(text="📢 Ota-onalarga", callback_data="admin:grp_msg:parent"),
    )
    builder.row(
        InlineKeyboardButton(text="📢 Broadcast", callback_data="admin:broadcast"),
        InlineKeyboardButton(text="➕ O'quvchi qo'sh", callback_data="admin:add_student_cred"),
    )
    builder.row(
        InlineKeyboardButton(text="📥 Excel eksport", callback_data="admin:excel_export"),
        InlineKeyboardButton(text="⏰ Vaqt sozlash", callback_data="admin:set_time"),
    )
    builder.row(
        InlineKeyboardButton(text="🔍 Faollik", callback_data="admin:check_activity"),
        InlineKeyboardButton(text="🗑 Xabarlarni o'chir", callback_data="admin:delete_all_msgs"),
    )
    builder.row(
        InlineKeyboardButton(text="🔔 Avto xabarlar", callback_data="admin:auto_msg"),
    )
    builder.row(
        InlineKeyboardButton(text="🏆 Test Reyting", callback_data="admin:test_leaderboard"),
        InlineKeyboardButton(text="🧹 Dublikatlar", callback_data="admin:cleanup_duplicates"),
    )
    return builder.as_markup()


# ─── Admin: o'quvchilar ro'yxati ──────────────────────────────────────────────


def kb_admin_students(
    students: list,
    all_groups: list[str],
    active_group: str = "all",
) -> InlineKeyboardMarkup:
    """
    Tepada guruh filtrlari (nechta ro'yxatdan o'tgani ko'rsatiladi),
    pastda tanlangan guruh o'quvchilari — bosish bilan detail sahifa ochiladi.
    """
    builder = InlineKeyboardBuilder()

    # Guruh filtrlari
    total = len(students)
    all_mark = "●" if active_group == "all" else "○"
    builder.row(
        InlineKeyboardButton(
            text=f"{all_mark} Hammasi ({total})",
            callback_data="admin:students:all",
        )
    )

    group_btns = []
    for g in all_groups:
        cnt = sum(1 for s in students if s.group_name == g)
        mark = "●" if active_group == g else "○"
        group_btns.append(
            InlineKeyboardButton(
                text=f"{mark} {g} ({cnt})",
                callback_data=f"admin:students:{g}",
            )
        )
    for i in range(0, len(group_btns), 2):
        builder.row(*group_btns[i : i + 2])

    # Filtrlangan o'quvchilar
    filtered = students if active_group == "all" else [s for s in students if s.group_name == active_group]

    if not filtered:
        builder.row(InlineKeyboardButton(text="📭 Hali hech kim ro'yxatdan o'tmagan", callback_data="noop"))
    else:
        for s in filtered:
            label = f"👤 {s.full_name}"
            if active_group == "all":
                label += f"  |  {s.group_name}"
            tg_hint = s.telegram_username or f"ID:{s.user_id}"
            builder.row(
                InlineKeyboardButton(
                    text=f"{label}  ({tg_hint})",
                    callback_data=f"admin:student_detail:{s.user_id}",
                )
            )

    builder.row(InlineKeyboardButton(text="◀️ Panel", callback_data="admin:panel"))
    return builder.as_markup()


def kb_student_detail(student) -> InlineKeyboardMarkup:
    """O'quvchi detail sahifasi tugmalari."""
    builder = InlineKeyboardBuilder()

    # Telegram havolasi
    tg_raw = student.telegram_username or ""
    if tg_raw.startswith("@"):
        tg_url = f"https://t.me/{tg_raw[1:]}"
    elif tg_raw:
        tg_url = f"https://t.me/{tg_raw}"
    else:
        tg_url = f"tg://user?id={student.user_id}"

    builder.row(
        InlineKeyboardButton(text="🔗 Telegramda ochish", url=tg_url),
        InlineKeyboardButton(text="📩 Bot orqali xabar", callback_data=f"admin:msg_student:{student.user_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🗑 Ro'yxatdan o'chirish", callback_data=f"admin:remove_student:{student.user_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Ro'yxatga qaytish", callback_data="admin:students:all"),
    )
    return builder.as_markup()


def kb_confirm_remove_student(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Ha, o'chir", callback_data=f"admin:remove_confirm:{user_id}"),
        InlineKeyboardButton(text="❌ Bekor", callback_data=f"admin:student_detail:{user_id}"),
    )
    return builder.as_markup()


# ─── Ro'yxatdan o'tish ────────────────────────────────────────────────────────


def kb_mars_groups(groups: list[str]) -> InlineKeyboardMarkup:
    """Guruhni tanlash tugmalari (ro'yxatdan o'tish uchun)."""
    builder = InlineKeyboardBuilder()
    for g in groups:
        builder.row(
            InlineKeyboardButton(
                text=f"📚 {g}",
                callback_data=f"reg:group:{g}",
            )
        )
    return builder.as_markup()


# ─── O'quvchi paneli ──────────────────────────────────────────────────────────


def kb_student_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if WEBAPP_URL:
        builder.row(
            InlineKeyboardButton(
                text="🚀 Mini App — Shaxsiy kabinet",
                web_app=WebAppInfo(url=f"{WEBAPP_URL.rstrip('/')}/webapp/student.html"),
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="📖 Qo'llanma / Инструкция",
                web_app=WebAppInfo(url=f"{WEBAPP_URL.rstrip('/')}/webapp/guide.html?role=student"),
            )
        )
    builder.row(
        InlineKeyboardButton(text="📚 Uy vazifasi", callback_data="student:homework"),
        InlineKeyboardButton(text="📺 Darslar kanali", url=CHANNEL_LINK),
    )
    builder.row(
        InlineKeyboardButton(text="📅 Dars jadvali", callback_data="student:schedule"),
        InlineKeyboardButton(text="📜 Vazifa tarixi", callback_data="student:hw_history"),
    )
    builder.row(
        InlineKeyboardButton(text="📱 Telefon", callback_data="student:change_phone"),
        InlineKeyboardButton(text="⚠️ Muammo bildirish", callback_data="student:report"),
    )
    return builder.as_markup()


def kb_attendance(date_str: str) -> InlineKeyboardMarkup:
    """Davomat tugmalari — kunlik eslatma bilan birga yuboriladi."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Ha, boraman", callback_data=f"attend:yes:{date_str}"),
        InlineKeyboardButton(text="❌ Kela olmayman", callback_data=f"attend:no:{date_str}"),
    )
    return builder.as_markup()


# ─── Admin: uy vazifasi yuborish ─────────────────────────────────────────────


def kb_hw_groups(groups: list[str], prefix: str = "hw") -> InlineKeyboardMarkup:
    """Admin uchun guruh tanlash (uy vazifasi / jadval / broadcast uchun)."""
    builder = InlineKeyboardBuilder()
    for g in groups:
        builder.row(
            InlineKeyboardButton(
                text=f"📚 {g}",
                callback_data=f"{prefix}:group:{g}",
            )
        )
    builder.row(InlineKeyboardButton(text="◀️ Panel", callback_data="admin:panel"))
    return builder.as_markup()


# ─── Guruhlar ro'yxati (filter bilan) ────────────────────────────────────────


def kb_group_list(groups: list[Group], active_filter: str = "all") -> InlineKeyboardMarkup:
    """
    active_filter: "all" | "parent" | "student"
    Tepada filter tugmalari, pastda guruhlar ro'yxati.
    """
    builder = InlineKeyboardBuilder()

    # Filter tugmalari
    all_mark = "●" if active_filter == "all" else "○"
    parent_mark = "●" if active_filter == "parent" else "○"
    student_mark = "●" if active_filter == "student" else "○"

    builder.row(
        InlineKeyboardButton(text=f"{all_mark} Hammasi", callback_data="admin:list:all"),
        InlineKeyboardButton(text=f"{parent_mark} Ota-onalar", callback_data="admin:list:parent"),
        InlineKeyboardButton(text=f"{student_mark} O'quvchilar", callback_data="admin:list:student"),
    )

    # Filtr bo'yicha guruhlar
    filtered = _filter_groups(groups, active_filter)
    if not filtered:
        builder.row(InlineKeyboardButton(text="📭 Guruhlar yo'q", callback_data="noop"))
    else:
        for g in filtered:
            status = "🟢" if g.is_active else "🔴"
            aud_icon = "👨‍👩‍👧" if g.audience == AudienceType.PARENT else "🎓"
            kind = "Toq" if g.group_type == GroupType.ODD else "Juft"
            builder.row(
                InlineKeyboardButton(
                    text=f"{status}{aud_icon} {g.name} ({kind})",
                    callback_data=f"group:detail:{g.chat_id}",
                )
            )

    builder.row(InlineKeyboardButton(text="◀️ Panel", callback_data="admin:panel"))
    return builder.as_markup()


def _filter_groups(groups: list[Group], f: str) -> list[Group]:
    if f == "parent":
        return [g for g in groups if g.audience == AudienceType.PARENT]
    if f == "student":
        return [g for g in groups if g.audience == AudienceType.STUDENT]
    return groups


# ─── Multi-select: guruh tanlash ─────────────────────────────────────────────


def kb_group_selector(
    bot_chats: list[BotChat],
    selected: set[int],
) -> InlineKeyboardMarkup:
    """
    Bot a'zo bo'lgan guruhlar ro'yxati.
    Har bir guruh toggle: ✅ tanlangan | ☐ tanlanmagan.
    """
    builder = InlineKeyboardBuilder()

    if not bot_chats:
        builder.row(
            InlineKeyboardButton(
                text="😔 Bot hech bir guruhda yo'q",
                callback_data="noop",
            )
        )
    else:
        for chat in bot_chats:
            check = "✅" if chat.chat_id in selected else "☐"
            builder.row(
                InlineKeyboardButton(
                    text=f"{check} {chat.title}",
                    callback_data=f"select:toggle:{chat.chat_id}",
                )
            )

    # Alt tugmalar
    count = len(selected)
    builder.row(
        InlineKeyboardButton(text="☑️ Barchasini tanla", callback_data="select:all"),
        InlineKeyboardButton(text="⬜ Bekor qil", callback_data="select:none"),
    )
    confirm_text = f"✅ Davom etish ({count} ta)" if count else "✅ Davom etish"
    builder.row(
        InlineKeyboardButton(text=confirm_text, callback_data="select:confirm"),
        InlineKeyboardButton(text="❌ Bekor", callback_data="fsm:cancel"),
    )
    return builder.as_markup()


# ─── Guruh amallari ───────────────────────────────────────────────────────────


def kb_group_actions(group: Group) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if group.is_active:
        toggle_btn = InlineKeyboardButton(text="⏸ Nofaol", callback_data=f"group:off:{group.chat_id}")
    else:
        toggle_btn = InlineKeyboardButton(text="▶️ Aktiv", callback_data=f"group:on:{group.chat_id}")

    builder.row(
        toggle_btn,
        InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"group:delete_ask:{group.chat_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🚀 Test yuborish", callback_data=f"group:test:{group.chat_id}"),
        InlineKeyboardButton(text="❌ Xabarni o'chir", callback_data=f"group:delete_msg:{group.chat_id}"),
    )
    builder.row(InlineKeyboardButton(text="◀️ Ro'yxat", callback_data="admin:list:all"))
    return builder.as_markup()


def kb_confirm_delete(chat_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Ha, o'chir", callback_data=f"group:delete_yes:{chat_id}"),
        InlineKeyboardButton(text="❌ Bekor", callback_data=f"group:detail:{chat_id}"),
    )
    return builder.as_markup()


def kb_choose_type() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="1️⃣ Toq kunliklar", callback_data="fsm:type:odd"),
        InlineKeyboardButton(text="2️⃣ Juft kunliklar", callback_data="fsm:type:even"),
    )
    builder.row(InlineKeyboardButton(text="❌ Bekor", callback_data="fsm:cancel"))
    return builder.as_markup()


def kb_choose_audience() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👨‍👩‍👧 Ota-onalar", callback_data="fsm:audience:parent"),
        InlineKeyboardButton(text="🎓 O'quvchilar", callback_data="fsm:audience:student"),
    )
    builder.row(InlineKeyboardButton(text="❌ Bekor", callback_data="fsm:cancel"))
    return builder.as_markup()


def kb_quick_add(chat_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Ha, qo'shish", callback_data=f"quickadd:start:{chat_id}"),
        InlineKeyboardButton(text="❌ O'tkazib yuborish", callback_data=f"quickadd:skip:{chat_id}"),
    )
    return builder.as_markup()


def kb_read_confirm(admin_id: int) -> InlineKeyboardMarkup:
    """O'quvchiga yuborilgan xabarga qo'shiladigan 'O'qidim' tugmasi."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ O'qidim",
            callback_data=f"read_confirm:{admin_id}",
        )
    )
    return builder.as_markup()


# ─── Kurator paneli ───────────────────────────────────────────────────────────


def kb_curator_panel() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if WEBAPP_URL:
        builder.row(
            InlineKeyboardButton(
                text="🎛 Kurator Paneli",
                web_app=WebAppInfo(url=f"{WEBAPP_URL.rstrip('/')}/webapp/curator.html"),
            )
        )
    else:
        # WEBAPP_URL yo'q bo'lsa chiqish tugmasi ko'rsatiladi
        builder.row(
            InlineKeyboardButton(text="🚪 Chiqish", callback_data="cur:logout"),
        )
    return builder.as_markup()


def kb_curator_students(
    students: list,
    all_groups: list[str],
    active_group: str = "all",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    # Guruh filtrlari
    all_mark = "●" if active_group == "all" else "○"
    builder.row(
        InlineKeyboardButton(
            text=f"{all_mark} Hammasi ({len(students)})",
            callback_data="cur:list:all",
        )
    )
    grp_btns = []
    for g in all_groups:
        cnt = sum(1 for s in students if s.group_name == g)
        mark = "●" if active_group == g else "○"
        grp_btns.append(
            InlineKeyboardButton(
                text=f"{mark} {g} ({cnt})",
                callback_data=f"cur:list:{g}",
            )
        )
    for i in range(0, len(grp_btns), 2):
        builder.row(*grp_btns[i : i + 2])

    # Filtrlangan o'quvchilar
    filtered = students if active_group == "all" else [s for s in students if s.group_name == active_group]
    if not filtered:
        builder.row(InlineKeyboardButton(text="📭 O'quvchilar yo'q", callback_data="noop"))
    else:
        for s in filtered:
            tg = s.telegram_username or f"ID:{s.user_id}"
            label = f"👤 {s.full_name}  |  {s.group_name}  ({tg})"
            builder.row(
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"cur:contact:{s.user_id}",
                )
            )

    builder.row(InlineKeyboardButton(text="◀️ Panel", callback_data="cur:panel"))
    return builder.as_markup()


def kb_curator_contact(student, has_active_chat: bool = False) -> InlineKeyboardMarkup:
    """O'quvchi bilan bog'lanish variantlari."""
    builder = InlineKeyboardBuilder()

    tg_raw = student.telegram_username or ""
    if tg_raw.startswith("@"):
        tg_url = f"https://t.me/{tg_raw[1:]}"
    elif tg_raw:
        tg_url = f"https://t.me/{tg_raw}"
    else:
        tg_url = None

    if tg_url:
        builder.row(InlineKeyboardButton(text="🔗 Telegramda yozish", url=tg_url))

    if has_active_chat:
        builder.row(
            InlineKeyboardButton(
                text="💬 Faol chat mavjud → Ko'rish",
                callback_data=f"cur:resume:{student.user_id}",
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="💬 Bot orqali aloqa",
                callback_data=f"cur:chat_start:{student.user_id}",
            )
        )

    builder.row(InlineKeyboardButton(text="◀️ Ro'yxat", callback_data="cur:list:all"))
    return builder.as_markup()


def kb_curator_active_chat(student_user_id: int) -> InlineKeyboardMarkup:
    """Kurator chat jarayonida ko'radigan tugma."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Javobni oldim",
            callback_data=f"cur:got_answer:{student_user_id}",
        )
    )
    return builder.as_markup()


def kb_curator_confirm_end(student_user_id: int) -> InlineKeyboardMarkup:
    """'Javobni oldim' uchun ogohlantirish + tasdiqlash."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Ha, yakunlayman", callback_data=f"cur:end_confirm:{student_user_id}"),
        InlineKeyboardButton(text="❌ Davom etish", callback_data="cur:end_cancel"),
    )
    return builder.as_markup()


def kb_curator_read(curator_telegram_id: int) -> InlineKeyboardMarkup:
    """O'quvchiga yuborilgan kurator xabarida 'O'qidim' tugmasi."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📖 O'qidim",
            callback_data=f"cur_read:{curator_telegram_id}",
        )
    )
    return builder.as_markup()


# ─── Uy vazifasi menyusi ─────────────────────────────────────────────────────


def kb_hw_menu() -> InlineKeyboardMarkup:
    """Uy vazifasi bosh menyusi."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Yangi vazifa yuborish", callback_data="admin:send_hw"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Vazifalarni boshqarish", callback_data="admin:hw_list"),
    )
    builder.row(InlineKeyboardButton(text="◀️ Panel", callback_data="admin:panel"))
    return builder.as_markup()


def kb_hw_manage(groups: list[str], homeworks: dict) -> InlineKeyboardMarkup:
    """Guruhlar ro'yxati — har biri uchun o'chirish/o'zgartirish tugmalari."""
    builder = InlineKeyboardBuilder()
    for g in groups:
        hw = homeworks.get(g)
        if hw:
            date = hw.sent_at.strftime("%d.%m")
            builder.row(
                InlineKeyboardButton(text=f"📚 {g} ({date})", callback_data="noop"),
            )
            builder.row(
                InlineKeyboardButton(text="✏️ O'zgartirish", callback_data=f"hw:edit:{g}"),
                InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"hw:delete_ask:{g}"),
            )
        else:
            builder.row(
                InlineKeyboardButton(text=f"📭 {g} — vazifa yo'q", callback_data="noop"),
                InlineKeyboardButton(text="➕ Qo'shish", callback_data=f"hw:edit:{g}"),
            )
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin:hw_menu"))
    return builder.as_markup()


def kb_hw_delete_confirm(group_name: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Ha, o'chir", callback_data=f"hw:delete_yes:{group_name}"),
        InlineKeyboardButton(text="❌ Bekor", callback_data="admin:hw_list"),
    )
    return builder.as_markup()


# ─── Kurator: davomat yoqlamasi ───────────────────────────────────────────────


def kb_davomat_start(group_name: str, date_str: str) -> InlineKeyboardMarkup:
    """Kuratorga yuborilgan — dars boshlanganidan 20 daqiqa o'tgach yuboriladi."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📋 Yoqlamani to'ldirish",
            callback_data=f"cur:davomat:{group_name}:{date_str}",
        )
    )
    return builder.as_markup()


def kb_davomat_mark(students_marks: list[dict]) -> InlineKeyboardMarkup:
    """
    O'quvchilarni belgilash klaviaturasi.
    students_marks: [{"full_name": str, "present": bool, "idx": int}, ...]
    """
    builder = InlineKeyboardBuilder()
    for item in students_marks:
        emoji = "✅" if item["present"] else "❌"
        builder.row(
            InlineKeyboardButton(
                text=f"{emoji} {item['full_name']}",
                callback_data=f"cur:tog:{item['idx']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="📩 Yuborish", callback_data="cur:davomat_send"),
        InlineKeyboardButton(text="❌ Bekor", callback_data="cur:davomat_cancel"),
    )
    return builder.as_markup()


def kb_select_parent_group(parent_groups: list) -> InlineKeyboardMarkup:
    """Ota-ona guruhini tanlash."""
    builder = InlineKeyboardBuilder()
    if not parent_groups:
        builder.row(
            InlineKeyboardButton(
                text="⚠️ Ota-ona guruhlari topilmadi",
                callback_data="noop",
            )
        )
    else:
        for g in parent_groups:
            builder.row(
                InlineKeyboardButton(
                    text=f"👨‍👩‍👧 {g.name}",
                    callback_data=f"cur:pgroup:{g.chat_id}",
                )
            )
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="cur:davomat_back"))
    return builder.as_markup()


def kb_cancel_fsm() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="fsm:cancel"))
    return builder.as_markup()


def kb_back_to_panel() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Panel", callback_data="admin:panel"))
    return builder.as_markup()
