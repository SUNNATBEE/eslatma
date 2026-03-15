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
from aiogram.types import TelegramObject

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
        # Ma'lumotlar bazasi servisini handler kontekstiga qo'shamiz
        data["db"] = self.db
        return await handler(event, data)
