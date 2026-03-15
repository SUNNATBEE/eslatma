"""
curator_credentials.py — Kuratorlar login/parol ma'lumotlari.

Parollarni o'zgartirish uchun shu faylni tahrirlang.
telegram_username — agar bo'lsa @ bilan yozing (masalan "@diyora"),
  bo'lmasa bo'sh qoldiring "".
"""

CURATORS: dict[str, dict] = {
    "diyora": {
        "password":           "diyora2024",   # ← parolni o'zgartiring
        "full_name":          "Diyora",
        "telegram_username":  "@mars_teamlead_curator",             # ← "@diyora" ko'rinishida to'ldiring
    },
    "zuhra": {
        "password":           "zuhra2024",    # ← parolni o'zgartiring
        "full_name":          "Zuhra",
        "telegram_username":  "@mars_yunusobod_curator",             # ← "@zuhra" ko'rinishida to'ldiring
    },
}
