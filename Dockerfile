# ─── Dockerfile ───────────────────────────────────────────────────────────────
# Engil Python image — Alpine asosida (production uchun optimal)
FROM python:3.12-slim

# Metadata
LABEL maintainer="O'quv Markaz Bot"
LABEL description="Telegram dars eslatmasi boti"

# Python xatoliklarini to'g'ridan-to'g'ri chiqarish (buffersiz)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Ishchi papka
WORKDIR /app

# ─── Kutubxonalarni o'rnatish ─────────────────────────────────────────────────
# Avval faqat requirements.txt ni ko'chiramiz (Docker layer caching uchun)
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ─── Loyiha fayllarini ko'chirish ─────────────────────────────────────────────
COPY . .

# ─── Ma'lumotlar bazasi uchun papka ───────────────────────────────────────────
# /data — Render persistent disk mount point
# /app/data — fallback (disk yo'q bo'lsa)
RUN mkdir -p /data && mkdir -p /app/data

# ─── Portni ochish (keep-alive uchun) ────────────────────────────────────────
EXPOSE 8080

# ─── Ishga tushirish ──────────────────────────────────────────────────────────
CMD ["python", "main.py"]
