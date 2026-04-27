"""
Standart JSON API javoblari (Mini App / admin).

Muvaffaqiyat: {"ok": true, ...}
Xato: {"ok": false, "error": "...", "code": "..."}
"""

from __future__ import annotations

from typing import Any

from aiohttp import web


def json_ok(status: int = 200, **fields: Any) -> web.Response:
    """Muvaffaqiyat javobi; maydonlar yuqori darajada birlashtiriladi."""
    body: dict[str, Any] = {"ok": True, **fields}
    return web.json_response(body, status=status)


def json_err(
    message: str,
    *,
    code: str = "error",
    status: int = 400,
    **extra: Any,
) -> web.Response:
    """Xato javobi."""
    body: dict[str, Any] = {"ok": False, "error": message, "code": code}
    if extra:
        body["details"] = extra
    return web.json_response(body, status=status)
