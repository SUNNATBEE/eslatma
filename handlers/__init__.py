"""
handlers/ — Telegram xabar va buyruq ishlovchilari paketi.
"""

from handlers.admin_extras import router as admin_extras_router
from handlers.attendance import router as attendance_router
from handlers.callbacks import router as callbacks_router
from handlers.commands import router as commands_router
from handlers.curator import router as curator_router
from handlers.registration import router as registration_router
from handlers.school import router as school_router
from handlers.student import router as student_router

__all__ = [
    "commands_router",
    "curator_router",
    "registration_router",
    "student_router",
    "attendance_router",
    "school_router",
    "admin_extras_router",
    "callbacks_router",
]
