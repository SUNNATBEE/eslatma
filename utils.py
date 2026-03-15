"""
utils.py — Kichik yordamchi funksiyalar.
"""

import logging
from typing import Optional

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)


async def safe_edit(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    """
    Xabarni tahrirlaydi. Agar matn o'zgarmagan bo'lsa — xatolikni e'tiborsiz qoldiradi.
    Telegram 'message is not modified' xatosini oldini oladi.
    """
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass  # Matn bir xil — muammo yo'q
        else:
            raise


async def safe_edit_markup(
    message: Message,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    """Faqat reply_markup ni tahrirlaydi (matn o'zgarmasa ham xato bermaslik uchun)."""
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            pass
        else:
            raise
