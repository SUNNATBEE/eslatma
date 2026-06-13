"""
curriculum.py — Mavzular/ papkadagi o'quv dasturi fayllarini structured ko'rinishga o'qiydi.

Ikki yo'nalish (track):
  beginner — Mavzular/nbg      (nBG / Beginner / IT Kids guruhlari)
  frontend — Mavzular/nfMavzu  (nF / nFPro / Front-End guruhlari)

Struktura: track → modul → blok → darslar ro'yxati.
Har dars: Lesson(num, name, metodika, academy).

Fayl formati (markdown):
    ## Modul-1 — 1-blok
    ### 1. Dars nomi
    **Metodika**
    <metodika matni>
    **Academy vazifasi**
    <academy matni>

"Loyiha ishi" sarlavhali "darslar" — placeholder, o'tkazib yuboriladi.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import cache

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_MAVZULAR_DIR = os.path.join(_BASE_DIR, "Mavzular")

# Yo'nalish → o'quv dasturi fayli
TRACK_FILES: dict[str, str] = {
    "beginner": os.path.join(_MAVZULAR_DIR, "nbg"),
    "frontend": os.path.join(_MAVZULAR_DIR, "nfMavzu"),
}

# Yo'nalish → ko'rsatiladigan nom
TRACK_LABELS: dict[str, str] = {
    "beginner": "Beginner / IT Kids",
    "frontend": "Front-End",
}

# Placeholder darslar (o'tkazib yuboriladi)
_SKIP_LESSON_NAMES = {"loyiha ishi"}

# "## Modul-1 — 1-blok"  (— em-dash, – en-dash yoki - bo'lishi mumkin)
_HEADER_RE = re.compile(r"^##\s+(Modul-\d+)\s*[—–-]\s*(\d+-blok)\b", re.IGNORECASE)
# "### 1. Dars nomi"  yoki  "### Loyiha ishi"
_LESSON_RE = re.compile(r"^###\s+(?:(\d+)\.\s*)?(.+?)\s*$")


@dataclass
class Lesson:
    num: str
    name: str
    metodika_lines: list[str] = field(default_factory=list)
    academy_lines: list[str] = field(default_factory=list)

    @property
    def metodika(self) -> str:
        return _clean("\n".join(self.metodika_lines))

    @property
    def academy(self) -> str:
        return _clean("\n".join(self.academy_lines))

    @property
    def title(self) -> str:
        """Tugmada/sarlavhada ko'rsatiladigan nom (raqam bilan)."""
        return f"{self.num}. {self.name}" if self.num else self.name


def _clean(text: str) -> str:
    """Ortiqcha bo'sh qatorlarni qisqartiradi, placeholder belgilarni olib tashlaydi."""
    text = text.replace("_(bo'sh)_", "").strip()
    # 3+ ketma-ket bo'sh qatorni 2 taga
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_file(path: str) -> dict[str, dict[str, list[Lesson]]]:
    """Bitta o'quv dasturi faylini {modul: {blok: [Lesson]}} ko'rinishiga o'qiydi."""
    modules: dict[str, dict[str, list[Lesson]]] = {}
    cur_module: str | None = None
    cur_block: str | None = None
    cur_lesson: Lesson | None = None
    section: str | None = None  # None | "metodika" | "academy"

    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            stripped = line.strip()

            # Modul-blok sarlavhasi
            mh = _HEADER_RE.match(stripped)
            if mh:
                cur_module, cur_block = mh.group(1), mh.group(2)
                cur_lesson = None
                section = None
                continue

            # Dars sarlavhasi
            if stripped.startswith("### "):
                lh = _LESSON_RE.match(stripped)
                if lh:
                    name = lh.group(2).strip()
                    if name.lower() in _SKIP_LESSON_NAMES or cur_module is None:
                        cur_lesson = None
                        section = None
                        continue
                    cur_lesson = Lesson(num=(lh.group(1) or "").strip(), name=name)
                    modules.setdefault(cur_module, {}).setdefault(cur_block, []).append(cur_lesson)
                    section = None
                    continue

            if cur_lesson is None:
                continue

            if stripped == "**Metodika**":
                section = "metodika"
                continue
            if stripped == "**Academy vazifasi**":
                section = "academy"
                continue
            # Boshqa bo'lim sarlavhalari (** ... **) — bo'limni yopadi
            if stripped.startswith("**") and stripped.endswith("**"):
                section = None
                continue

            if section == "metodika":
                cur_lesson.metodika_lines.append(line)
            elif section == "academy":
                cur_lesson.academy_lines.append(line)

    return modules


@cache
def get_track(track: str) -> dict[str, dict[str, list[Lesson]]]:
    """Yo'nalish bo'yicha to'liq strukturani qaytaradi (keshlanadi)."""
    path = TRACK_FILES.get(track)
    if not path or not os.path.isfile(path):
        return {}
    return _parse_file(path)


def available_tracks() -> list[str]:
    """Fayli mavjud bo'lgan yo'nalishlar ro'yxati."""
    return [t for t, p in TRACK_FILES.items() if os.path.isfile(p)]


def list_modules(track: str) -> list[str]:
    return list(get_track(track).keys())


def list_blocks(track: str, module: str) -> list[str]:
    return list(get_track(track).get(module, {}).keys())


def list_lessons(track: str, module: str, block: str) -> list[Lesson]:
    return get_track(track).get(module, {}).get(block, [])


def get_lesson(track: str, module: str, block: str, index: int) -> Lesson | None:
    lessons = list_lessons(track, module, block)
    if 0 <= index < len(lessons):
        return lessons[index]
    return None


def track_for_group(group_name: str) -> str:
    """Guruh nomidan yo'nalishni aniqlaydi.

    nF*, nFPro*, 2996, Pro  → frontend
    nBG*, IK*, kids, beginner → beginner
    Aniqlanmasa — frontend (asosiy yo'nalish).
    """
    n = (group_name or "").strip().lower()
    if n.startswith("nbg") or n.startswith("ik") or "kids" in n or "beginner" in n:
        return "beginner"
    if n.startswith("nf") or n.startswith("2996") or "pro" in n:
        return "frontend"
    return "frontend"
