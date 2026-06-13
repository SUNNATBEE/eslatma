# Dars vazifasi — `/vazifa` (AI uy vazifa generatori)

Ustoz (admin) dars oxirida **mavzuni tanlaydi** (yoki nomini o'zi yozadi), AI o'sha mavzudan
**qisqa, professional va 10 yoshli bola tushunadigan** uy vazifasi + UI namunasini tuzadi va
guruhga yuboradi.

## Oqim

1. **Boshlash** — ikki yo'l:
   - Qo'lda: admin `/vazifa` yozadi.
   - Avtomatik: dars tugagandan ~1 daqiqa keyin botdan **"📝 Vazifa yaratish"** tugmasi keladi
     (`send_lesson_topic_prompt` scheduler job; guruh allaqachon ma'lum).
2. **Guruh** tanlanadi (qo'lda oqimda) → guruh nomidan **yo'nalish (track)** aniqlanadi.
3. **Mavzu** ikki yo'l bilan beriladi:
   - **O'quv dasturidan:** Modul → Blok → Dars mavzusi inline tugmalar bilan.
   - **Qo'lda:** **"✍️ Mavzu nomini o'zim yozaman"** tugmasi → admin mavzu nomini yozadi.
     Pro/maxsus guruhlar uchun (o'quv dasturi yo'q) — yagona yo'l, avtomatik taklif qilinadi.
4. AI mavzudan **2 tilli (🇺🇿 + 🇷🇺)**, qisqa va professional vazifa tuzadi.
5. AI **maqsadli UI namunasini** (HTML) ham chizadi — o'quvchi "shu ko'rinishni yasashi" kerak.
6. Admin **preview** ko'radi (UI havolasi bilan) → **✅ Guruhga yuborish** / **🔄 Qayta yaratish** / **❌ Bekor**.
7. Guruhga **📌 UYGA VAZIFA** katta sarlavhasi bilan yuboriladi.

> Istalgan bosqichda **`/cancel`** bilan to'xtatish mumkin.

## UI namuna havolasi (Figma o'rnida)

Vazifa bilan birga AI o'quvchi yasashi kerak bo'lgan **etalon UI** ni to'liq, mustaqil HTML
hujjat qilib generatsiya qiladi (tashqi resurssiz — barcha CSS inline, rasm o'rniga emoji/SVG).
Bot uni DB'ga saqlaydi va guruhga **`{WEBAPP_URL}/task/<id>`** havolasini yuboradi — o'quvchi
Telegram'da bosib, namunani ko'radi (login/Figma akkaunt kerak emas).

- Saqlash: `generated_task_ui` jadvali (`DatabaseService.save_task_ui` / `get_task_ui`).
- Ko'rsatish: `GET /task/{task_id}` endpoint (`main.py`).
- Generatsiya: `ai_service.generate_assignment_ui()`.
- `WEBAPP_URL` bo'sh bo'lsa yoki UI generatsiya xato bersa — vazifa matni baribir yuboriladi
  (havolasiz, oqim buzilmaydi).

> ⚠️ Render/Railway fayl tizimi efemer — shuning uchun UI **DB'da** saqlanadi (fayl emas),
> redeploy'dan keyin ham havola ishlaydi (DB saqlansa).

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
ai_service.py            — generate_assignment() (2 tilli vazifa) + generate_assignment_ui() (HTML namuna)
handlers/lesson_topic.py — /vazifa FSM + inline oqim + preview/yuborish + UI havola
main.py                  — GET /task/{task_id} (UI namunasini ko'rsatadi)
database.py              — GeneratedTaskUI modeli + save_task_ui/get_task_ui
scheduler.py             — send_lesson_topic_prompt() (dars oxirida prompt)
```

## Texnik eslatmalar

- callback_data `lt:*` qisqaligi uchun **indekslar** ishlatadi; ro'yxatlar FSM state'da.
- Dars nomlari `<a>`, `<img>` kabi belgilarni o'z ichiga olishi mumkin — HTML xabarlarda
  `html.escape()` qilinadi. AI matni `parse_mode=None` bilan yuboriladi.
- Uzun vazifa matni 4000 belgilik bo'laklarga bo'linadi (`_send_long`).
