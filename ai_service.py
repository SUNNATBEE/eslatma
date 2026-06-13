"""
ai_service.py — Anthropic Claude orqali uy vazifasini professional tahlil qilish.

O'quvchi guruhga yuborgan vazifani (rasm/kod/zip/havola/matn) AI tahlil qiladi
va xato-kamchiliklarni IKKI tilda (O'zbek + Rus) tushuntiradi.

anthropic kutubxonasi LAZY import qilinadi — agar feature ishlatilmasa yoki
kutubxona o'rnatilmagan bo'lsa ham bot ishga tushaveradi.
"""

import logging

from config import AI_MAX_TOKENS, AI_MODEL, ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

# Anthropic AsyncAnthropic mijozi — bir marta yaratiladi (singleton)
_client = None


def is_configured() -> bool:
    """API kalit o'rnatilganmi?"""
    return bool(ANTHROPIC_API_KEY)


def _get_client():
    """AsyncAnthropic mijozini lazy yaratadi."""
    global _client
    if _client is None:
        from anthropic import AsyncAnthropic  # lazy import

        _client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _client


# ─── Ustoz persona (system prompt) ───────────────────────────────────────────
# Toza MATN chiqishi muhim — Telegram'da xavfsiz ko'rsatish uchun (markdown emas).
SYSTEM_PROMPT = (
    "Sen — Mars IT O'quv Markazining tajribali, professional dasturlash ustozisan.\n"
    "O'quvchilar senga uy vazifalarini yuboradi. Vazifa istalgan ko'rinishda bo'lishi mumkin:\n"
    "kod (HTML, CSS, JavaScript, Python, va h.k.), skrinshot (rasm), ZIP arxiv, "
    "havola (GitHub/sayt manbasi) yoki oddiy matn.\n\n"
    "Sening vazifang — yuborilgan ishni PROFESSIONAL tahlil qilish:\n"
    "1. Kod yoki ishni diqqat bilan tekshir.\n"
    "2. Xato va kamchiliklarni ANIQ top: sintaksis, mantiqiy xato, struktura, "
    "best-practice, dizayn, xavfsizlik, nomlash (naming), formatlash.\n"
    "3. Har bir xatoni o'quvchi TUSHUNADIGAN tarzda, sodda izohla. Iloji bo'lsa "
    "to'g'ri variantni ham ko'rsat.\n"
    "4. Yaxshi tomonlarini ham ayt — o'quvchini rag'batlantir.\n"
    "5. Oxirida 10 ballik baho qo'y va qisqa keyingi qadam tavsiyasini ber.\n\n"
    "MUHIM QOIDALAR:\n"
    "- Javobni IKKI tilda ber: AVVAL 🇺🇿 O'zbekcha, KEYIN 🇷🇺 Ruscha (to'liq tarjima).\n"
    "- Faqat TOZA MATN yoz. Markdown belgilaridan (**, ##, ```, *) MUTLAQO foydalanma.\n"
    "- Bo'limlar uchun emoji-sarlavhalar ishlat, masalan:\n"
    "  ✅ Yaxshi tomonlar / Сильные стороны\n"
    "  ⚠️ Xato va kamchiliklar / Ошибки и недочёты\n"
    "  💡 Tavsiyalar / Рекомендации\n"
    "  ⭐ Baho / Оценка: N/10\n"
    "- Kod parchalarini oddiy qatorlarda ko'rsat (``` ishlatma).\n"
    "- Samimiy, ammo professional ohangda yoz. O'quvchini hech qachon kamsitma.\n"
    "- Agar yuborilgan material vazifaga o'xshamasa yoki bo'sh bo'lsa — buni "
    "xushmuomalalik bilan ayt va nima yuborish kerakligini tushuntir.\n"
    "- Javob ortiqcha cho'zilmasin: eng muhim 3-6 ta nuqtaga e'tibor qarat."
)


async def analyze_homework(
    content_blocks: list[dict],
    student_name: str,
    group_name: str,
    notes: list[str] | None = None,
) -> str:
    """Vazifa materialini Claude'ga yuborib, 2 tilli tahlil matnini qaytaradi.

    content_blocks — Anthropic content bloklari ro'yxati (text va/yoki image).
    Xato bo'lsa Exception ko'taradi (chaqiruvchi ushlab oladi).
    """
    client = _get_client()

    intro = (
        f"O'quvchi: {student_name}\n"
        f"Guruh: {group_name or '—'}\n\n"
        "Quyida o'quvchining uy vazifasi keltirilgan. Uni professional tahlil qil "
        "va yuqoridagi qoidalarga rioya qilgan holda 2 tilda javob ber."
    )
    if notes:
        intro += "\n\nDiqqat (tizim eslatmasi): " + " ".join(notes)

    # Tartib: kontekst (matn) → material bloklari → yakuniy ko'rsatma
    user_content: list[dict] = [{"type": "text", "text": intro}]
    user_content.extend(content_blocks)
    user_content.append(
        {"type": "text", "text": "Endi yuqoridagi vazifani tahlil qilib, baho va tavsiya bilan yakunla."}
    )

    response = await client.messages.create(
        model=AI_MODEL,
        max_tokens=AI_MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # barqaror prefiks — keshlanadi
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )

    text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
    try:
        u = response.usage
        logger.info(
            "AI tahlil tayyor | model=%s in=%s out=%s cache_read=%s",
            AI_MODEL,
            getattr(u, "input_tokens", "?"),
            getattr(u, "output_tokens", "?"),
            getattr(u, "cache_read_input_tokens", "?"),
        )
    except Exception:
        pass

    if not text:
        raise RuntimeError("AI bo'sh javob qaytardi")
    return text


# ─── Dars mavzusidan uy vazifa generatsiyasi ─────────────────────────────────
# Toza MATN chiqishi muhim — Telegram guruhga to'g'ridan-to'g'ri yuboriladi.
ASSIGNMENT_SYSTEM_PROMPT = (
    "Sen — Mars IT O'quv Markazining tajribali, ijodkor dasturlash ustozisan.\n"
    "Senga bugun o'tilgan dars mavzusi, uning metodikasi va akademiya vazifasi beriladi.\n"
    "Sening vazifang — shu mavzuni CHUQUR tahlil qilib, 10-16 yoshli o'quvchilar uchun "
    "QIZIQARLI va bajariladigan uy vazifasi tuzish.\n\n"
    "VAZIFA QANDAY BO'LISHI KERAK:\n"
    "1. Mavzuga to'g'ridan-to'g'ri bog'liq bo'lsin (metodika va akademiya vazifasiga tayan).\n"
    "2. 10-16 yoshli bolaga mos: sodda til, qiziqarli mavzu (o'yin, multfilm, kundalik hayot).\n"
    "3. Aniq, bosqichma-bosqich ko'rsatma ber — o'quvchi nimani qilishini tushunsin.\n"
    "4. Bajarish mumkin bo'lgan hajmda bo'lsin (keyingi darsgacha ulgursin).\n"
    "5. Natija qanday topshirilishini ayt (masalan: skrinshot, kod, havola, fayl — guruhga "
    "#vazifa hashtagi bilan yuborilsin).\n\n"
    "JAVOB FORMATI (qat'iy):\n"
    "- Javobni IKKI tilda ber: AVVAL 🇺🇿 O'zbekcha, KEYIN 🇷🇺 Ruscha (to'liq tarjima).\n"
    "- Faqat TOZA MATN. Markdown belgilaridan (**, ##, ```, *) MUTLAQO foydalanma.\n"
    "- Quyidagi emoji-sarlavhali tuzilishdan foydalan:\n"
    "  📚 Mavzu: <mavzu nomi>\n"
    "  🎯 Vazifa: <nima qilish kerakligi, qisqa>\n"
    "  📝 Bosqichlar: <1), 2), 3) ko'rinishida aniq qadamlar>\n"
    "  ✅ Talablar: <vazifa to'liq sanaladigan shartlar>\n"
    "  💡 Maslahat: <foydali maslahat yoki qiziqarli fakt>\n"
    "  📤 Topshirish: <natijani qanday va qayerga yuborish>\n"
    "- Ruscha qism uchun: 📚 Тема, 🎯 Задание, 📝 Шаги, ✅ Требования, 💡 Совет, 📤 Сдача.\n"
    "- Samimiy, rag'batlantiruvchi ohang. Bolani 'dasturchi', 'qahramon' deb ata.\n"
    "- Ortiqcha cho'zma — qisqa, aniq va amaliy bo'lsin."
)


async def generate_assignment(
    *,
    track_label: str,
    module: str,
    block: str,
    lesson_name: str,
    metodika: str,
    academy: str,
    group_name: str = "",
    extra_note: str = "",
) -> str:
    """Dars mavzusi asosida 10-16 yosh uchun 2 tilli uy vazifasini generatsiya qiladi.

    Telegram guruhga to'g'ridan-to'g'ri yuboriladigan toza matn qaytaradi.
    Xato bo'lsa Exception ko'taradi (chaqiruvchi ushlab oladi).
    """
    client = _get_client()

    context = (
        f"Yo'nalish: {track_label}\n"
        f"Modul: {module} · Blok: {block}\n"
        f"Dars mavzusi: {lesson_name}\n"
        f"Guruh: {group_name or '—'}\n\n"
        "=== METODIKA (dars mazmuni) ===\n"
        f"{(metodika or '—')[:2500]}\n\n"
        "=== AKADEMIYA VAZIFASI (asl topshiriq) ===\n"
        f"{(academy or '—')[:2500]}\n\n"
        "Yuqoridagi mavzuni chuqur tahlil qilib, 10-16 yoshli o'quvchilar uchun "
        "qiziqarli uy vazifasini tuz va yuqoridagi formatda 2 tilda javob ber."
    )
    if extra_note:
        context += f"\n\nQo'shimcha (ustoz eslatmasi): {extra_note}"

    response = await client.messages.create(
        model=AI_MODEL,
        max_tokens=AI_MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": ASSIGNMENT_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # barqaror prefiks — keshlanadi
            }
        ],
        messages=[{"role": "user", "content": [{"type": "text", "text": context}]}],
    )

    text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
    try:
        u = response.usage
        logger.info(
            "AI vazifa generatsiya | model=%s in=%s out=%s cache_read=%s | dars=%s",
            AI_MODEL,
            getattr(u, "input_tokens", "?"),
            getattr(u, "output_tokens", "?"),
            getattr(u, "cache_read_input_tokens", "?"),
            lesson_name,
        )
    except Exception:
        pass

    if not text:
        raise RuntimeError("AI bo'sh javob qaytardi")
    return text
