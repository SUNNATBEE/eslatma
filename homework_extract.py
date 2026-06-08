"""
homework_extract.py — Telegram xabarlaridan uy vazifasi materialini ajratib oladi.

Qo'llab-quvvatlanadi:
  • Rasm (photo)        → Claude vision uchun base64 image bloki
  • Rasm-hujjat (doc)   → png/jpg/gif/webp document
  • ZIP arxiv           → ichidagi kod/matn fayllar matn sifatida
  • Kod/matn fayl       → html/css/js/py/... matn sifatida
  • Havola (link)       → HTML/kod manbasi yuklab olinadi (GitHub raw qo'llab-quvvatlanadi)
  • Matn/kod            → xabar matni/izohi

Natija: (content_blocks, notes) — Anthropic content bloklari + tizim eslatmalari.
"""

import io
import ipaddress
import logging
import re
import socket
import zipfile
from urllib.parse import urlparse

import aiohttp
from aiogram import Bot
from aiogram.types import Message

from config import (
    AI_MAX_FILE_CHARS,
    AI_MAX_IMAGE_MB,
    AI_MAX_IMAGES,
    AI_MAX_LINK_BYTES,
    AI_MAX_TOTAL_CHARS,
    AI_MAX_ZIP_FILES,
)

logger = logging.getLogger(__name__)

# Matn/kod sifatida o'qiladigan kengaytmalar
CODE_EXT = {
    "html", "htm", "css", "scss", "sass", "less", "js", "mjs", "cjs", "jsx",
    "ts", "tsx", "vue", "svelte", "py", "json", "md", "txt", "xml", "yml",
    "yaml", "c", "cpp", "h", "hpp", "cs", "java", "kt", "go", "rs", "rb",
    "php", "sql", "sh", "bat", "ini", "env", "toml", "gitignore",
}
# Rasm sifatida yuboriladigan kengaytmalar
IMG_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
_MIME_BY_EXT = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp",
}

_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)


def extract_urls(text: str) -> list[str]:
    """Matndan http(s) havolalarni ajratadi."""
    return _URL_RE.findall(text or "")


# ─── Telegram fayl yuklab olish ───────────────────────────────────────────────


async def _tg_bytes(bot: Bot, file_id: str, max_bytes: int | None = None) -> tuple[bytes | None, str | None]:
    try:
        f = await bot.get_file(file_id)
        if max_bytes and f.file_size and f.file_size > max_bytes:
            return None, f"Fayl juda katta ({f.file_size // 1024} KB), o'tkazib yuborildi."
        buf = io.BytesIO()
        await bot.download_file(f.file_path, buf)
        return buf.getvalue(), None
    except Exception as e:
        logger.warning("Telegram fayl yuklab bo'lmadi (%s): %s", file_id, e)
        return None, "Faylni yuklab bo'lmadi."


# ─── Havola (link) o'qish ─────────────────────────────────────────────────────


def _is_blocked_host(host: str) -> bool:
    """SSRF himoyasi: ichki/lokal manzillarni rad etadi."""
    if not host:
        return True
    low = host.lower()
    if low == "localhost" or low.endswith(".local") or low.endswith(".internal"):
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
            return True
    return False


def _to_raw_github(url: str) -> str:
    """GitHub blob havolasini raw'ga aylantiradi (kod manbasini olish uchun)."""
    if "github.com" in url and "/blob/" in url:
        return url.replace("github.com", "raw.githubusercontent.com", 1).replace("/blob/", "/", 1)
    return url


async def _fetch_url(url: str) -> tuple[str | None, str | None]:
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return None, None
        if _is_blocked_host(p.hostname or ""):
            return None, f"Havola xavfsizlik sababli ochilmadi: {url}"
        target = _to_raw_github(url)
        timeout = aiohttp.ClientTimeout(total=12)
        headers = {"User-Agent": "Mozilla/5.0 (otaOnaBot homework checker)"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
            async with s.get(target, allow_redirects=True) as r:
                if r.status >= 400:
                    return None, f"Havola ochilmadi (HTTP {r.status}): {url}"
                data = await r.content.read(AI_MAX_LINK_BYTES + 1)
        text = data.decode("utf-8", "ignore").strip()
        if not text:
            return None, f"Havola bo'sh: {url}"
        return text[:AI_MAX_LINK_BYTES], None
    except Exception as e:
        logger.warning("Havolani o'qib bo'lmadi (%s): %s", url, e)
        return None, f"Havolani o'qib bo'lmadi: {url}"


# ─── ZIP arxiv ────────────────────────────────────────────────────────────────


def _extract_zip_bytes(data: bytes) -> str:
    parts: list[str] = []
    used = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            count = 0
            for name in names:
                if count >= AI_MAX_ZIP_FILES:
                    break
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext not in CODE_EXT:
                    continue
                # bekor papkalarni o'tkazib yuboramiz (har qanday darajada)
                segments = set(name.split("/"))
                if segments & {"node_modules", ".git", "__pycache__"} or name.startswith("__MACOSX"):
                    continue
                try:
                    raw = zf.read(name)
                except Exception:
                    continue
                content = raw.decode("utf-8", "ignore")
                if not content.strip():
                    continue
                chunk = content[:AI_MAX_FILE_CHARS]
                block = f"\n── {name} ──\n{chunk}"
                if used + len(block) > AI_MAX_TOTAL_CHARS:
                    break
                parts.append(block)
                used += len(block)
                count += 1
    except zipfile.BadZipFile:
        return ""
    return "".join(parts)


# ─── Asosiy: xabarlardan content bloklarini yig'ish ───────────────────────────


async def build_homework_payload(
    messages: list[Message], bot: Bot, strip_triggers=None
) -> tuple[list[dict], list[str]]:
    """Xabarlar ro'yxatidan Anthropic content bloklarini va eslatmalarni yig'adi.

    strip_triggers — matndan olib tashlanadigan hashtag'lar (ixtiyoriy callable).
    """
    blocks: list[dict] = []
    notes: list[str] = []
    total_chars = 0
    image_count = 0
    max_image_bytes = int(AI_MAX_IMAGE_MB * 1024 * 1024)

    for msg in messages:
        # 1) Matn / izoh / havola
        raw_text = (msg.text or msg.caption or "").strip()
        if raw_text:
            cleaned = strip_triggers(raw_text) if strip_triggers else raw_text
            cleaned = cleaned.strip()
            urls = extract_urls(cleaned)
            if cleaned and total_chars < AI_MAX_TOTAL_CHARS:
                chunk = cleaned[:AI_MAX_FILE_CHARS]
                blocks.append({"type": "text", "text": f"[O'quvchi matni/kodi]:\n{chunk}"})
                total_chars += len(chunk)
            for url in urls[:3]:
                if total_chars >= AI_MAX_TOTAL_CHARS:
                    break
                fetched, note = await _fetch_url(url)
                if fetched:
                    chunk = fetched[: AI_MAX_TOTAL_CHARS - total_chars]
                    blocks.append({"type": "text", "text": f"[Havola tarkibi — {url}]:\n{chunk}"})
                    total_chars += len(chunk)
                if note:
                    notes.append(note)

        # 2) Rasm (photo)
        if msg.photo and image_count < AI_MAX_IMAGES:
            data, note = await _tg_bytes(bot, msg.photo[-1].file_id, max_image_bytes)
            if data:
                import base64

                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": base64.standard_b64encode(data).decode("ascii"),
                        },
                    }
                )
                image_count += 1
            if note:
                notes.append(note)

        # 3) Hujjat (document): rasm / zip / kod-matn
        if msg.document:
            doc = msg.document
            mime = (doc.mime_type or "").lower()
            fname = doc.file_name or "fayl"
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""

            if (mime.startswith("image/") or ext in IMG_EXT) and image_count < AI_MAX_IMAGES:
                data, note = await _tg_bytes(bot, doc.file_id, max_image_bytes)
                if data:
                    import base64

                    media_type = mime if mime.startswith("image/") else _MIME_BY_EXT.get(ext, "image/png")
                    blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64.standard_b64encode(data).decode("ascii"),
                            },
                        }
                    )
                    image_count += 1
                if note:
                    notes.append(note)

            elif ext == "zip" or "zip" in mime:
                data, note = await _tg_bytes(bot, doc.file_id, max_bytes=20 * 1024 * 1024)
                if data:
                    text = _extract_zip_bytes(data)
                    if text and total_chars < AI_MAX_TOTAL_CHARS:
                        chunk = text[: AI_MAX_TOTAL_CHARS - total_chars]
                        blocks.append({"type": "text", "text": f"[ZIP arxiv — {fname}]:\n{chunk}"})
                        total_chars += len(chunk)
                    elif not text:
                        notes.append(f"'{fname}' arxividan kod fayllari topilmadi.")
                if note:
                    notes.append(note)

            elif ext in CODE_EXT or mime.startswith("text/"):
                data, note = await _tg_bytes(bot, doc.file_id, max_bytes=2 * 1024 * 1024)
                if data and total_chars < AI_MAX_TOTAL_CHARS:
                    text = data.decode("utf-8", "ignore")
                    chunk = text[: min(AI_MAX_FILE_CHARS, AI_MAX_TOTAL_CHARS - total_chars)]
                    blocks.append({"type": "text", "text": f"[Fayl — {fname}]:\n{chunk}"})
                    total_chars += len(chunk)
                if note:
                    notes.append(note)
            else:
                kind = mime or "nomalum tur"
                notes.append(f"'{fname}' ({kind}) qo'llab-quvvatlanmaydi.")

    return blocks, notes
