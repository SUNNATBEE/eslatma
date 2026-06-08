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
