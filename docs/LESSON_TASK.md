# Dars vazifasi — `/vazifa` (AI uy vazifa generatori)

Ustoz (admin) dars oxirida o'tilgan **mavzuni tanlaydi**, AI o'sha mavzudan
**10-16 yoshli o'quvchilar uchun** qiziqarli uy vazifasi tuzadi va guruhga yuboradi.

## Oqim

1. **Boshlash** — ikki yo'l:
   - Qo'lda: admin `/vazifa` yozadi.
   - Avtomatik: dars tugagandan ~1 daqiqa keyin botdan **"📝 Vazifa yaratish"** tugmasi keladi
     (`send_lesson_topic_prompt` scheduler job; guruh allaqachon ma'lum).
2. **Guruh** tanlanadi (qo'lda oqimda) → guruh nomidan **yo'nalish (track)** aniqlanadi.
3. **Modul → Blok → Dars mavzusi** ketma-ket inline tugmalar bilan tanlanadi.
4. AI mavzuni chuqur tahlil qilib **2 tilli (🇺🇿 + 🇷🇺)** vazifa tuzadi.
5. Admin **preview** ko'radi → **✅ Guruhga yuborish** / **🔄 Qayta yaratish** / **❌ Bekor**.

## Ma'lumot manbasi

`Mavzular/` papkasidagi o'quv dasturi fayllari (`curriculum.py` o'qiydi):

| Track      | Fayl              | Guruhlar                          |
|------------|-------------------|-----------------------------------|
| `beginner` | `Mavzular/nbg`    | nBG-*, IK-* (IT Kids), Beginner   |
| `frontend` | `Mavzular/nfMavzu`| nF-*, nFPro-*, 2996-Pro           |

Fayl formati: `## Modul-N — M-blok` → `### K. Dars nomi` → `**Metodika**` / `**Academy vazifasi**`.
`Loyiha ishi` sarlavhali bo'limlar (placeholder) o'tkazib yuboriladi.

> ⚠️ **Deployment:** `Mavzular/` papkasi runtime'da o'qiladi. Docker `COPY . .` qiladi va
> `.dockerignore` uni chiqarmaydi — lekin **git'ga commit qilingan bo'lishi** shart, aks holda
> Render/Railway build kontekstida bo'lmaydi. Fayl topilmasa oqim "o'quv dasturi topilmadi"
> deydi (crash bo'lmaydi).

## Sozlash

- `ANTHROPIC_API_KEY` — AI generatsiya uchun (yo'q bo'lsa oqim ogohlantiradi).
- Model/limit: `config.py` → `AI_MODEL`, `AI_MAX_TOKENS`.
- Avtomatik promptni o'chirish: BotSetting `AUTO_MSG_LESSON_TASK=0`
  (yoki master `AUTO_MSG_MASTER=0`, kunlik `AUTO_MSG_GROUPS=0`).

## Tegishli fayllar

```
curriculum.py            — Mavzular/ parser (track → modul → blok → dars)
ai_service.py            — generate_assignment() (2 tilli vazifa)
handlers/lesson_topic.py — /vazifa FSM + inline oqim + preview/yuborish
scheduler.py             — send_lesson_topic_prompt() (dars oxirida prompt)
```

## Texnik eslatmalar

- callback_data `lt:*` qisqaligi uchun **indekslar** ishlatadi; ro'yxatlar FSM state'da.
- Dars nomlari `<a>`, `<img>` kabi belgilarni o'z ichiga olishi mumkin — HTML xabarlarda
  `html.escape()` qilinadi. AI matni `parse_mode=None` bilan yuboriladi.
- Uzun vazifa matni 4000 belgilik bo'laklarga bo'linadi (`_send_long`).
