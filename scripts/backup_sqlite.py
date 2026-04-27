#!/usr/bin/env python3
"""
SQLite faylini vaqt tamg'asi bilan nusxalaydi.

Ishlatish:
  python scripts/backup_sqlite.py
  DATABASE_URL=sqlite+aiosqlite:///./data/bot.db python scripts/backup_sqlite.py

Muhit: BACKUP_DIR (default: ./backups)
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path


def _sqlite_path_from_url(url: str) -> Path | None:
    # sqlite+aiosqlite:///relative  yoki  sqlite+aiosqlite:////absolute
    m = re.match(r"sqlite\+aiosqlite:///+(.*)", url.strip(), re.I)
    if not m:
        return None
    raw = m.group(1).replace("/", os.sep)
    p = Path(raw)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv()
    url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db")
    src = _sqlite_path_from_url(url)
    if not src or not src.is_file():
        print(f"SQLite fayl topilmadi: {src!r} (DATABASE_URL={url!r})")
        return 1
    out_dir = Path(os.getenv("BACKUP_DIR", "backups"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    dest = out_dir / f"{src.stem}_{stamp}{src.suffix}"
    shutil.copy2(src, dest)
    print(f"OK: {src} -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
