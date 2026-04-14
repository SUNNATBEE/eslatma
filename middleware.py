"""
middleware.py — Aiogram middleware'lari.

DatabaseMiddleware:
  Har bir handlerga 'db' parametrini avtomatik uzatadi.
  Bu dependency injection pattern — handlerlar DatabaseService ni
  to'g'ridan-to'g'ri import qilmaydi, balki funksiya parametri sifatida oladi.
"""

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, TelegramObject

from database import DatabaseService

logger = logging.getLogger(__name__)


class DatabaseMiddleware(BaseMiddleware):
    """
    Handler'larga 'db: DatabaseService' ni dependency injection orqali uzatadi.

    Ishlatilishi:
        dp.update.middleware(DatabaseMiddleware(db_service))

    Handler imzosi:
        async def my_handler(message: Message, db: DatabaseService): ...
    """

    def __init__(self, db: DatabaseService) -> None:
        self.db = db
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["db"] = self.db
        return await handler(event, data)


class CallbackAnswerMiddleware(BaseMiddleware):
    """
    Inline tugma bosilganda DARHOL Telegram'ga javob beradi.

    Render kabi sekin hosting'larda tugma ustida yuklanish animatsiyasi
    uzoq turadi — foydalanuvchi botni buzilgan deb o'ylaydi.
    Bu middleware tugmaning spinner'ini darhol o'chiradi, keyin handler
    o'z ishini bajaradi va natijani yuboradi.
    """

    async def __call__(
        self,
        handler: Callable[[CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        # Tugma spinner'ini darhol o'chirish
        try:
            await event.bot.answer_callback_query(callback_query_id=event.id)
        except Exception:
            logger.debug("CallbackAnswerMiddleware: callback queryga javob berib bo'lmadi", exc_info=True)

        # Handler'ni ishlatamiz
        # Agar handler callback.answer() qayta chaqirsa — xatoni e'tiborsiz qoldiramiz
        try:
            return await handler(event, data)
        except TelegramBadRequest as e:
            msg = str(e).lower()
            if "query is too old" in msg or "query id is invalid" in msg:
                pass  # Takror javob berish xatosi — kutilgan holat
            else:
                raise


class ButtonTrackingMiddleware(BaseMiddleware):
    """
    Har bir callback_query bosilganda tugma nomini DB ga saqlaydi.
    callback_data dan birinchi 2 qismni prefix sifatida ishlatadi:
      "att:yes:2026-03-17" → "att:yes"
      "student:hw"         → "student:hw"
    """

    def __init__(self, db: DatabaseService) -> None:
        self.db = db
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        if event.data:
            parts  = event.data.split(":")
            prefix = ":".join(parts[:2]) if len(parts) > 1 else event.data
            import asyncio
            asyncio.create_task(self.db.track_button(prefix))
        return await handler(event, data)


class TypingMiddleware(BaseMiddleware):
    """
    Xabar kelganda 'yozmoqda...' animatsiyasini ko'rsatadi.
    Foydalanuvchi bot so'rovini qabul qilganini biladi.
    Faqat shaxsiy chatlar uchun ishlaydi.
    """

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if getattr(event, "chat", None) and event.chat.type == "private":
            try:
                await event.bot.send_chat_action(
                    chat_id=event.chat.id,
                    action="typing",
                )
            except Exception:
                logger.debug("TypingMiddleware: typing action yuborib bo'lmadi", exc_info=True)
        return await handler(event, data)
