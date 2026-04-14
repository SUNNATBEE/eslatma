"""
utils.py - Kichik yordamchi funksiyalar.
"""

import hashlib
import hmac
import logging
import secrets
from typing import Optional

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)
PBKDF2_PREFIX = "pbkdf2_sha256"


def hash_secret(secret: str, *, salt: str | None = None, iterations: int = 390000) -> str:
    """Matnni PBKDF2-SHA256 formatida hash qiladi."""
    if not isinstance(secret, str) or not secret:
        raise ValueError("Secret bo'sh bo'lmasligi kerak")
    salt = salt or secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return f"{PBKDF2_PREFIX}${iterations}${salt}${derived}"


def is_hashed_secret(value: str) -> bool:
    return isinstance(value, str) and value.startswith(f"{PBKDF2_PREFIX}$")


def verify_secret(stored_value: str, candidate: str) -> bool:
    """Hashlangan va legacy plain matn secretlarni solishtiradi."""
    if not stored_value or candidate is None:
        return False
    if is_hashed_secret(stored_value):
        try:
            _prefix, iterations_raw, salt, expected = stored_value.split("$", 3)
            derived = hashlib.pbkdf2_hmac(
                "sha256",
                candidate.encode("utf-8"),
                salt.encode("utf-8"),
                int(iterations_raw),
            ).hex()
            return hmac.compare_digest(derived, expected)
        except (TypeError, ValueError):
            logger.warning("Hash formatini o'qib bo'lmadi")
            return False
    return hmac.compare_digest(stored_value, candidate)


async def safe_edit(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    """
    Xabarni tahrirlaydi. Agar matn o'zgarmagan bo'lsa xatolikni e'tiborsiz qoldiradi.
    """
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            logger.debug("safe_edit: message is not modified")
        else:
            raise


async def safe_edit_markup(
    message: Message,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    """Faqat reply_markup ni tahrirlaydi."""
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            logger.debug("safe_edit_markup: markup is not modified")
        else:
            raise
