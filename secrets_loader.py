"""
secrets_loader.py - Repo tashqarisidagi secret/config payloadlarni yuklash.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_json_mapping(
    *,
    env_json_key: str,
    env_file_key: str,
    default_filename: str,
) -> dict[str, Any]:
    """JSON mappingni env ichidan yoki lokal fayldan yuklaydi."""
    inline_json = os.getenv(env_json_key, "").strip()
    if inline_json:
        try:
            payload = json.loads(inline_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"{env_json_key} yaroqsiz JSON: {e}") from e
        if not isinstance(payload, dict):
            raise ValueError(f"{env_json_key} dict bo'lishi kerak")
        return payload

    file_path = Path(os.getenv(env_file_key, default_filename)).expanduser()
    if not file_path.is_absolute():
        file_path = Path(__file__).resolve().parent / file_path
    if not file_path.exists():
        logger.warning(
            f"Secret fayl topilmadi: {file_path}. "
            f"{env_file_key} yoki {env_json_key} ni sozlang. "
            f"Bo'sh dict bilan davom etilmoqda."
        )
        return {}

    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{file_path} yaroqsiz JSON: {e}") from e
    if not isinstance(payload, dict):
        raise ValueError(f"{file_path} dict bo'lishi kerak")
    return payload
