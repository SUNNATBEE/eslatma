"""
ai_service.py — Anthropic Claude orqali uy vazifasini professional tahlil qilish.

O'quvchi guruhga yuborgan vazifani (rasm/kod/zip/havola/matn) AI tahlil qiladi
va xato-kamchiliklarni IKKI tilda (O'zbek + Rus) tushuntiradi.

anthropic kutubxonasi LAZY import qilinadi — agar feature ishlatilmasa yoki
kutubxona o'rnatilmagan bo'lsa ham bot ishga tushaveradi.
"""

import logging
import re

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


# ─── Uy vazifasini MAVZU bo'yicha baholash (#vazifa → XP) ────────────────────
# O'quvchi yuborgan ishni guruhga oxirgi berilgan uy vazifasi (etalon) bo'yicha
# tekshiradi va 0-10 ball qo'yadi. Ball oxirida [[BAHO:N]] markeri bilan beriladi
# (kod tomonida parse qilinadi va XP'ga aylantiriladi: max 30).
GRADE_SYSTEM_PROMPT = (
    "Sen — Mars IT O'quv Markazining adolatli, professional dasturlash ustozisan.\n"
    "Senga AVVAL o'quvchiga berilgan UY VAZIFASI (etalon) beriladi, KEYIN o'quvchi "
    "topshirgan ish (kod, rasm, ZIP yoki havola).\n\n"
    "Vazifang — o'quvchi ishini AYNAN shu berilgan vazifa talablariga solishtirib baholash:\n"
    "1. Vazifa talablari bajarilganmi? Har bir shartni tekshir.\n"
    "2. Xato va kamchiliklarni aniq top (sintaksis, mantiq, dizayn, struktura).\n"
    "3. Yaxshi tomonlarni ham ayt — rag'batlantir.\n"
    "4. Qisqa va aniq bo'l — eng muhim 3-5 nuqta.\n\n"
    "BAHOLASH MEZONI (0-10):\n"
    "- 9-10: vazifa to'liq, sifatli bajarilgan.\n"
    "- 7-8: yaxshi, kichik kamchiliklar bilan.\n"
    "- 5-6: o'rtacha — asosiy qism bor, lekin talablar to'liq emas.\n"
    "- 3-4: kam bajarilgan, ko'p kamchilik.\n"
    "- 0-2: vazifaga aloqasi yo'q yoki deyarli bo'sh.\n\n"
    "JAVOB FORMATI (qat'iy):\n"
    "- IKKI tilda: AVVAL 🇺🇿 O'zbekcha, KEYIN 🇷🇺 Ruscha.\n"
    "- Faqat TOZA MATN. Markdown (**, ##, ```, *) ISHLATMA.\n"
    "- Emoji-sarlavhalar: ✅ Yaxshi / Сильные, ⚠️ Kamchilik / Ошибки, 💡 Tavsiya / Совет.\n"
    "- 10 yoshli bola tushunadigan sodda til.\n"
    "- ENG OXIRGI qatorda ALBATTA mashina o'qiydigan marker yoz: [[BAHO:N]] "
    "(N — 0 dan 10 gacha butun son). Bu qatorni boshqa hech narsa bilan aralashtirma."
)


def _parse_grade(text: str) -> tuple[str, int | None]:
    """[[BAHO:N]] markerini ajratib oladi: (markersiz_matn, N yoki None)."""
    score: int | None = None
    m = re.search(r"\[\[\s*BAHO\s*:\s*(\d{1,2})\s*\]\]", text, re.IGNORECASE)
    if m:
        try:
            score = max(0, min(10, int(m.group(1))))
        except ValueError:
            score = None
    clean = re.sub(r"\[\[\s*BAHO\s*:\s*\d{1,2}\s*\]\]", "", text, flags=re.IGNORECASE).strip()
    return clean, score


async def grade_homework(
    content_blocks: list[dict],
    student_name: str,
    group_name: str,
    assignment_text: str,
    notes: list[str] | None = None,
) -> tuple[str, int | None]:
    """O'quvchi ishini berilgan uy vazifasi bo'yicha baholaydi.

    Returns: (feedback_matni, baho_0_10 yoki None). Baho topilmasa None.
    Xato bo'lsa Exception ko'taradi (chaqiruvchi ushlab oladi).
    """
    client = _get_client()

    intro = (
        f"O'quvchi: {student_name}\n"
        f"Guruh: {group_name or '—'}\n\n"
        "=== O'QUVCHIGA BERILGAN UY VAZIFASI (etalon — shunga solishtir) ===\n"
        f"{(assignment_text or '—')[:3000]}\n\n"
        "=== O'QUVCHI TOPSHIRGAN ISH (quyida) ==="
    )
    if notes:
        intro += "\n\nDiqqat (tizim eslatmasi): " + " ".join(notes)

    user_content: list[dict] = [{"type": "text", "text": intro}]
    user_content.extend(content_blocks)
    user_content.append(
        {
            "type": "text",
            "text": "Endi yuqoridagi ishni berilgan vazifa talablariga solishtirib bahola. "
            "Oxirida [[BAHO:N]] markerini qo'yishni unutma.",
        }
    )

    response = await client.messages.create(
        model=AI_MODEL,
        max_tokens=AI_MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": GRADE_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )

    raw = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
    if not raw:
        raise RuntimeError("AI bo'sh javob qaytardi")
    feedback, score = _parse_grade(raw)
    try:
        u = response.usage
        logger.info(
            "AI vazifa baholash | model=%s in=%s out=%s baho=%s",
            AI_MODEL,
            getattr(u, "input_tokens", "?"),
            getattr(u, "output_tokens", "?"),
            score,
        )
    except Exception:
        pass
    return feedback, score


# ─── Vazifa UI namunasi (HTML) generatsiyasi ─────────────────────────────────
# AI uy vazifasi bilan birga o'quvchi "yasashi kerak bo'lgan" maqsadli UI ni
# to'liq, mustaqil HTML hujjat ko'rinishida chizadi. Bot uni hosting qilib,
# guruhga havola sifatida yuboradi (Figma o'rnini bosadi — login kerak emas).
UI_SYSTEM_PROMPT = (
    "Sen — tajribali front-end dizayner va o'qituvchisan. Senga dars mavzusi va o'quvchiga "
    "berilgan uy vazifasi beriladi. Sening vazifang — o'quvchi YASASHI kerak bo'lgan maqsadli "
    "natijani (target UI) ko'rsatuvchi NAMUNA sahifani tuzish.\n\n"
    "QAT'IY QOIDALAR:\n"
    "1. FAQAT bitta to'liq, mustaqil HTML hujjat qaytar. '<!DOCTYPE html>' bilan boshlanib "
    "'</html>' bilan tugasin.\n"
    "2. Hech qanday tashqi resurs ISHLATMA: tashqi CSS/JS/shrift/rasm havolalari, CDN, "
    "<script src=...>, <img src=http...> — TAQIQLANADI. Barcha CSS <style> ichida inline bo'lsin.\n"
    "3. Rasm kerak bo'lsa — CSS shakllari, emoji yoki SVG (inline) ishlat. Tashqi URL yo'q.\n"
    "4. Mobilga mos (responsive), zamonaviy va chiroyli ko'rinsin — bu o'quvchiga ETALON namuna.\n"
    "5. Matnlar o'zbek tilida (yoki mavzuga mos) bo'lsin. Real, mazmunli kontent qo'y "
    "(lorem ipsum EMAS).\n"
    "6. Murakkablik dars mavzusiga mos, lekin SODDA bo'lsin — 10 yoshli bola ham "
    "takrorlay oladigan darajada.\n"
    "7. Javobда HECH QANDAY izoh, markdown yoki ``` belgisi BO'LMASIN — faqat toza HTML."
)


def _strip_html_fence(text: str) -> str:
    """AI javobidan ```html ... ``` ramkasini va ortiqcha bo'shliqni olib tashlaydi."""
    t = text.strip()
    if t.startswith("```"):
        first_nl = t.find("\n")
        if first_nl != -1:
            t = t[first_nl + 1 :]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


async def generate_assignment_ui(
    *,
    lesson_name: str,
    metodika: str,
    academy: str,
    group_name: str = "",
    assignment_text: str = "",
) -> str:
    """Dars mavzusi va vazifa asosida maqsadli UI namunasini (to'liq HTML) generatsiya qiladi.

    Tashqi resurssiz, mustaqil HTML hujjat qaytaradi. Xato bo'lsa Exception ko'taradi.
    """
    client = _get_client()

    context = (
        f"Dars mavzusi: {lesson_name}\n"
        f"Guruh: {group_name or '—'}\n\n"
        "=== METODIKA (dars mazmuni) ===\n"
        f"{(metodika or '—')[:2000]}\n\n"
        "=== AKADEMIYA VAZIFASI ===\n"
        f"{(academy or '—')[:1500]}\n\n"
        "=== O'QUVCHIGA BERILGAN UY VAZIFASI ===\n"
        f"{(assignment_text or '—')[:2000]}\n\n"
        "Yuqoridagi mavzu va vazifaga mos ETALON UI namunasini to'liq HTML hujjat sifatida tuz. "
        "O'quvchi shu ko'rinishni o'zi yasashi kerak."
    )

    response = await client.messages.create(
        model=AI_MODEL,
        max_tokens=max(AI_MAX_TOKENS, 4000),
        system=[
            {
                "type": "text",
                "text": UI_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # barqaror prefiks — keshlanadi
            }
        ],
        messages=[{"role": "user", "content": [{"type": "text", "text": context}]}],
    )

    raw = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
    html = _strip_html_fence(raw)
    try:
        u = response.usage
        logger.info(
            "AI vazifa UI generatsiya | model=%s in=%s out=%s | dars=%s",
            AI_MODEL,
            getattr(u, "input_tokens", "?"),
            getattr(u, "output_tokens", "?"),
            lesson_name,
        )
    except Exception:
        pass

    if not html or "<" not in html:
        raise RuntimeError("AI yaroqli HTML qaytarmadi")
    return html


# ─── Dars mavzusidan uy vazifa generatsiyasi ─────────────────────────────────
# Toza MATN chiqishi muhim — Telegram guruhga to'g'ridan-to'g'ri yuboriladi.
ASSIGNMENT_SYSTEM_PROMPT = (
    "Sen — Mars IT O'quv Markazining tajribali, ijodkor dasturlash ustozisan.\n"
    "Senga dars mavzusi beriladi (ba'zan metodika va akademiya vazifasi bilan, ba'zan "
    "faqat mavzu nomi — ustoz o'zi belgilagan). Sening vazifang — shu mavzudan QISQA, "
    "PROFESSIONAL va aniq uy vazifasi tuzish.\n\n"
    "VAZIFA QANDAY BO'LISHI KERAK:\n"
    "1. Mavzuga to'g'ridan-to'g'ri bog'liq bo'lsin. Metodika/akademiya berilsa — unga tayan; "
    "faqat mavzu nomi berilsa — shu nomdan kelib chiqib mantiqiy vazifa tuz.\n"
    "2. Til ENG SODDA bo'lsin — 10 yoshli bola ham bir o'qishda tushunsin. Murakkab "
    "atamalardan qoch yoki qavs ichida sodda izohla.\n"
    "3. Aniq, bosqichma-bosqich ko'rsatma ber — o'quvchi nimani qilishini aniq bilsin.\n"
    "4. QISQA bo'lsin: ortiqcha gap, kirish so'zlari va suv yo'q. Faqat kerakli ma'lumot.\n"
    "5. Bajarish mumkin bo'lgan hajmda (keyingi darsgacha ulgursin).\n"
    "6. Natija qanday topshirilishini ayt (skrinshot, kod, havola yoki fayl — guruhga "
    "#vazifa hashtagi bilan).\n\n"
    "JAVOB FORMATI (qat'iy):\n"
    "- Javobni IKKI tilda ber: AVVAL 🇺🇿 O'zbekcha, KEYIN 🇷🇺 Ruscha (to'liq tarjima).\n"
    "- Faqat TOZA MATN. Markdown belgilaridan (**, ##, ```, *) MUTLAQO foydalanma.\n"
    "- Quyidagi emoji-sarlavhali tuzilishdan foydalan (har bo'lim QISQA bo'lsin):\n"
    "  📚 Mavzu: <mavzu nomi>\n"
    "  🎯 Vazifa: <bir-ikki gapda nima qilish kerakligi>\n"
    "  📝 Bosqichlar: <1), 2), 3) ko'rinishida aniq, qisqa qadamlar>\n"
    "  ✅ Talablar: <vazifa to'liq sanaladigan shartlar, qisqa ro'yxat>\n"
    "  💡 Maslahat: <bitta foydali maslahat>\n"
    "  📤 Topshirish: <natijani qanday va qayerga yuborish>\n"
    "- Ruscha qism uchun: 📚 Тема, 🎯 Задание, 📝 Шаги, ✅ Требования, 💡 Совет, 📤 Сдача.\n"
    "- Samimiy, ammo professional ohang. Bolani 'dasturchi', 'qahramon' deb ata.\n"
    "- ENG MUHIMI: qisqa, aniq, professional. Ortiqcha cho'zma."
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
    """Dars mavzusi asosida 2 tilli, qisqa va professional uy vazifasini generatsiya qiladi.

    Til 10 yoshli bola tushunadigan darajada sodda. metodika/academy bo'sh bo'lsa
    (ustoz mavzuni o'zi yozgan holat) — faqat mavzu nomidan kelib chiqadi.
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
