# Bugungi mavzu (`/mavzu`) — Se/Pa/Sh 16:30 prompti

## Nima qiladi

Seshanba, Payshanba va Shanba kunlari soat **16:30** da (Asia/Tashkent) bot adminlarga
"📚 Bugun qaysi mavzuni o'tdingiz?" xabarini yuboradi. Admin tugmani bosib quyidagi
oqimdan o'tadi:

1. **Yo'nalish** (Beginner / Front-End) — `curriculum.py` dagi tracklar
2. **Modul → Blok → Mavzu** — `Mavzular/` o'quv dasturidan
3. **Video dars** — "Frontend darslari" kanalidagi videolar ro'yxatidan
4. **Guruh** — aktiv o'quvchi guruhlaridan
5. **Preview → ✅ Guruhga yuborish** — guruhga 2 tilli (UZ+RU) uyga vazifa xabari:
   mavzu nomi, qaysi video darsni ko'rish kerakligi va kanal postiga havola.

Oqimni qo'lda ham boshlash mumkin: **/mavzu** (faqat admin).

## Kanal videolari ro'yxati qayerdan keladi

Bot API kanal tarixini o'qiy olmaydi, shuning uchun videolar `channel_videos`
jadvalida yig'iladi:

- **Yangi postlar** — bot kanalda admin bo'lgani uchun har bir yangi video post
  `channel_post` orqali avtomatik saqlanadi (nom: caption 1-qatori → fayl nomi).
- **Eski videolar** — admin kanaldagi videoni botga (shaxsiy chatga) **forward**
  qiladi; bot "✅ Video ro'yxatga qo'shildi" deb tasdiqlaydi.

Havola formati: public kanal → `https://t.me/<username>/<message_id>`,
private kanal → `https://t.me/c/<id>/<message_id>`.

## Sozlash

- Bot video darslar kanalida **admin** bo'lishi shart (channel_post kelishi uchun).
- Vaqt/kunlarni admin panel orqali o'zgartirish mumkin (`topic_day_prompt` job,
  dow vergul bilan: `tue,thu,sat`).
- O'chirish: `AUTO_MSG_TOPIC_DAY=0` (BotSetting) yoki master `AUTO_MSG_MASTER`.

## Fayllar

| Fayl | Rol |
|---|---|
| `handlers/topic_day.py` | FSM oqimi (`td:` callbacklar), channel_post/forward yig'uvchi |
| `scheduler.py` → `send_topic_day_prompt` | Se/Pa/Sh 16:30 cron prompti (dedup: `topicday:<sana>`) |
| `database.py` → `ChannelVideo` | Kanal videolari jadvali + `save_channel_video` / `get_channel_videos` |
