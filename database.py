"""
database.py — Ma'lumotlar bazasi modellari va CRUD operatsiyalari.

Jadvallar:
  - groups: Guruhlar (tur: Toq/Juft, auditoriya: Ota-ona/O'quvchi)
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Integer, String, delete, select, update, DateTime, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.sql import func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logger = logging.getLogger(__name__)


# ─── Enumlar ──────────────────────────────────────────────────────────────────

class GroupType(str, Enum):
    ODD  = "ODD"   # Toq kunliklar  (1, 3, 5 ...)
    EVEN = "EVEN"  # Juft kunliklar (2, 4, 6 ...)


class AudienceType(str, Enum):
    PARENT  = "PARENT"   # Ota-onalar guruhi
    STUDENT = "STUDENT"  # O'quvchilar guruhi


# ─── SQLAlchemy baza ──────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ─── Model: Bot guruhlari (bot qo'shilgan barcha guruhlar) ───────────────────

class BotChat(Base):
    """Bot a'zo bo'lgan barcha Telegram guruhlar."""
    __tablename__ = "bot_chats"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title:   Mapped[str] = mapped_column(String(255), nullable=False)

    def __repr__(self) -> str:
        return f"<BotChat chat_id={self.chat_id} title={self.title!r}>"


# ─── Model: Guruh ─────────────────────────────────────────────────────────────

class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Telegram chat ID (-1001234567890 ko'rinishida)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)

    # Guruh nomi (admin panel uchun yorliq)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Dars jadvali turi: toq yoki juft kunlar
    group_type: Mapped[GroupType] = mapped_column(SAEnum(GroupType), nullable=False)

    # Auditoriya: ota-onalar yoki o'quvchilar
    audience: Mapped[AudienceType] = mapped_column(
        SAEnum(AudienceType), nullable=False, default=AudienceType.STUDENT
    )

    # Aktiv/nofaol
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Oxirgi yuborilgan xabar ID (o'chirish uchun)
    last_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Group name={self.name!r} type={self.group_type} "
            f"audience={self.audience} active={self.is_active}>"
        )


# ─── Model: O'quvchi ──────────────────────────────────────────────────────────

class Student(Base):
    """Ro'yxatdan o'tgan o'quvchilar."""
    __tablename__ = "students"

    id:                 Mapped[int]           = mapped_column(primary_key=True, autoincrement=True)
    user_id:            Mapped[int]           = mapped_column(BigInteger, unique=True, nullable=False)
    telegram_username:  Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name:          Mapped[str]           = mapped_column(String(255), nullable=False)
    mars_id:            Mapped[str]           = mapped_column(String(50),  nullable=False)
    group_name:         Mapped[str]           = mapped_column(String(50),  nullable=False)
    phone_number:       Mapped[Optional[str]] = mapped_column(String(20),  nullable=True)
    registered_at:      Mapped[datetime]      = mapped_column(DateTime, server_default=func.now())
    last_active:        Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # ── Gamification ──────────────────────────────────────────────────────────
    xp:               Mapped[int]           = mapped_column(Integer, default=0,  nullable=False, server_default="0")
    level:            Mapped[int]           = mapped_column(Integer, default=1,  nullable=False, server_default="1")
    streak_days:      Mapped[int]           = mapped_column(Integer, default=0,  nullable=False, server_default="0")
    last_streak_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    avatar_emoji:     Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    game_wins:        Mapped[int]           = mapped_column(Integer, default=0, nullable=False, server_default="0")
    xp_notice_seen:   Mapped[bool]          = mapped_column(Boolean, default=True, nullable=False, server_default="1")

    def __repr__(self) -> str:
        return f"<Student {self.full_name!r} | {self.group_name}>"


# ─── Model: Uy vazifasi ────────────────────────────────────────────────────────

class Homework(Base):
    """Har guruh uchun oxirgi uy vazifasi (1 ta yozuv).

    from_chat_id + message_id: admin yuborgan xabarni nusxalash (copy_message) uchun.
    Bu yondashuv matn, video, fayl, havola — barchasini qo'llab-quvvatlaydi.
    """
    __tablename__ = "homeworks"

    group_name:   Mapped[str]      = mapped_column(String(50),  primary_key=True)
    from_chat_id: Mapped[int]      = mapped_column(BigInteger,  nullable=False)
    message_id:   Mapped[int]      = mapped_column(Integer,     nullable=False)
    sent_at:      Mapped[datetime] = mapped_column(DateTime,    nullable=False)

    def __repr__(self) -> str:
        return f"<Homework group={self.group_name!r} msg={self.message_id}>"


# ─── Model: Davomat ───────────────────────────────────────────────────────────

class AttendanceRecord(Base):
    """O'quvchilarning darsga kelish tasdiqi."""
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("user_id", "date_str"),)

    id:         Mapped[int]           = mapped_column(primary_key=True, autoincrement=True)
    user_id:    Mapped[int]           = mapped_column(BigInteger, nullable=False)
    date_str:   Mapped[str]           = mapped_column(String(20),  nullable=False)  # "2026-03-16"
    status:     Mapped[str]           = mapped_column(String(20),  nullable=False)  # "yes"/"no"
    reason:     Mapped[Optional[str]] = mapped_column(String(500), nullable=True)   # Kelmaslik sababi
    created_at: Mapped[datetime]      = mapped_column(DateTime, server_default=func.now())


# ─── Model: Dars jadvali ──────────────────────────────────────────────────────

class Schedule(Base):
    """Har guruh uchun dars jadvali (copy_message yondashuvi)."""
    __tablename__ = "schedules"

    group_name:   Mapped[str] = mapped_column(String(50), primary_key=True)
    from_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id:   Mapped[int] = mapped_column(Integer,    nullable=False)
    updated_at:   Mapped[datetime] = mapped_column(DateTime, nullable=False)


# ─── Model: Savol ─────────────────────────────────────────────────────────────

class Question(Base):
    """O'quvchidan kelgan savollar."""
    __tablename__ = "questions"

    id:           Mapped[int]  = mapped_column(primary_key=True, autoincrement=True)
    user_id:      Mapped[int]  = mapped_column(BigInteger, nullable=False)
    student_name: Mapped[str]  = mapped_column(String(255), nullable=False)
    group_name:   Mapped[str]  = mapped_column(String(50),  nullable=False)
    from_chat_id: Mapped[int]  = mapped_column(BigInteger, nullable=False)
    message_id:   Mapped[int]  = mapped_column(Integer,    nullable=False)
    is_answered:  Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at:   Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ─── Model: Uy vazifasi tarixi ────────────────────────────────────────────────

class HomeworkHistory(Base):
    """Har guruh uchun barcha yuborilgan uy vazifalari tarixi."""
    __tablename__ = "homework_history"

    id:           Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_name:   Mapped[str] = mapped_column(String(50), nullable=False)
    from_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id:   Mapped[int] = mapped_column(Integer,    nullable=False)
    sent_at:      Mapped[datetime] = mapped_column(DateTime, nullable=False)


# ─── Model: Bot sozlamalari ───────────────────────────────────────────────────

class BotSetting(Base):
    """Kalit-qiymat ko'rinishidagi bot sozlamalari (SEND_HOUR, SEND_MINUTE va h.k.)"""
    __tablename__ = "bot_settings"

    key:   Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), nullable=False)


# ─── Model: Kurator sessiyasi ─────────────────────────────────────────────────

class CuratorSession(Base):
    """Kurator Telegram ID si ↔ kurator_key ('diyora'/'zuhra') bog'liq."""
    __tablename__ = "curator_sessions"

    telegram_id:  Mapped[int]           = mapped_column(BigInteger, primary_key=True)
    curator_key:  Mapped[str]           = mapped_column(String(50),  nullable=False)
    logged_in_at: Mapped[datetime]      = mapped_column(DateTime, nullable=False)
    last_active:  Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ─── Model: Faol kurator-o'quvchi chat ────────────────────────────────────────

class ActiveCuratorChat(Base):
    """Joriy davom etayotgan kurator ↔ o'quvchi relaye chat."""
    __tablename__ = "active_curator_chats"

    id:                  Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    curator_telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    student_user_id:     Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    curator_key:         Mapped[str] = mapped_column(String(50),  nullable=False)
    started_at:          Mapped[datetime] = mapped_column(DateTime, nullable=False)


# ─── Model: Tugma statistikasi ────────────────────────────────────────────────

class ButtonStat(Base):
    """Qaysi callback tugmalar ko'proq ishlatilganini hisoblaydi."""
    __tablename__ = "button_stats"

    button_name: Mapped[str]           = mapped_column(String(100), primary_key=True)
    count:       Mapped[int]           = mapped_column(Integer, default=0, nullable=False)
    last_used:   Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ─── Model: Qo'shimcha o'quvchi credentials ───────────────────────────────────

class StudentCredential(Base):
    """Admin bot orqali qo'shgan o'quvchilar (credentials.py dan tashqari)."""
    __tablename__ = "student_credentials"

    mars_id:    Mapped[str] = mapped_column(String(50),  primary_key=True)
    name:       Mapped[str] = mapped_column(String(255), nullable=False)
    password:   Mapped[str] = mapped_column(String(50),  nullable=False)
    group_name: Mapped[str] = mapped_column(String(50),  nullable=False)
    added_at:   Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ─── Model: Kunlik kayfiyat ────────────────────────────────────────────────────

class DailyMood(Base):
    """O'quvchining kunlik kayfiyati (emoji tracker)."""
    __tablename__ = "daily_moods"
    __table_args__ = (UniqueConstraint("user_id", "date_str"),)

    id:         Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id:    Mapped[int] = mapped_column(BigInteger, nullable=False)
    date_str:   Mapped[str] = mapped_column(String(20), nullable=False)
    mood:       Mapped[str] = mapped_column(String(20), nullable=False)  # "happy"/"ok"/"sad"
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ─── Model: Uy vazifasi tasdiqi ────────────────────────────────────────────────

class HomeworkConfirmation(Base):
    """O'quvchi uy vazifasini ko'rganligini tasdiqlagan yozuvlar."""
    __tablename__ = "homework_confirmations"
    __table_args__ = (UniqueConstraint("user_id", "date_str"),)

    id:           Mapped[int]      = mapped_column(primary_key=True, autoincrement=True)
    user_id:      Mapped[int]      = mapped_column(BigInteger, nullable=False)
    date_str:     Mapped[str]      = mapped_column(String(20), nullable=False)  # hw.sent_at date
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


# ─── Model: O'quvchilar umumiy chati ─────────────────────────────────────────

class ChatMessage(Base):
    """Barcha o'quvchilar uchun umumiy chat xabarlari."""
    __tablename__ = "chat_messages"

    id:         Mapped[int]           = mapped_column(primary_key=True, autoincrement=True)
    user_id:    Mapped[int]           = mapped_column(BigInteger, nullable=False)
    full_name:  Mapped[str]           = mapped_column(String(255), nullable=False)
    group_name: Mapped[str]           = mapped_column(String(50),  nullable=False)
    avatar:     Mapped[Optional[str]] = mapped_column(String(20),  nullable=True)
    text:       Mapped[str]           = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime]      = mapped_column(DateTime, server_default=func.now())


# ─── Model: O'yin natijalari ──────────────────────────────────────────────────

class GameScore(Base):
    """Solo o'yin natijalari (typing, quiz, chess, memory, 2048)."""
    __tablename__ = "game_scores"

    id:         Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id:    Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    game_type:  Mapped[str] = mapped_column(String(30), nullable=False)  # typing/quiz/chess/memory/2048
    score:      Mapped[int] = mapped_column(Integer, default=0)          # WPM, points va hokazo
    xp_earned:  Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class GameRoom(Base):
    """Multiplayer o'yin xonasi (typing race)."""
    __tablename__ = "game_rooms"

    id:           Mapped[int]           = mapped_column(primary_key=True, autoincrement=True)
    game_type:    Mapped[str]           = mapped_column(String(30), nullable=False)  # typing_race
    player1_id:   Mapped[int]           = mapped_column(BigInteger, nullable=False)
    player1_name: Mapped[str]           = mapped_column(String(255), nullable=False)
    player2_id:   Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    player2_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status:       Mapped[str]           = mapped_column(String(20), default="waiting")  # waiting/active/finished
    text_passage: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    p1_progress:  Mapped[int]           = mapped_column(Integer, default=0)
    p2_progress:  Mapped[int]           = mapped_column(Integer, default=0)
    p1_finished:  Mapped[bool]          = mapped_column(Boolean, default=False)
    p2_finished:  Mapped[bool]          = mapped_column(Boolean, default=False)
    winner_id:    Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at:   Mapped[datetime]      = mapped_column(DateTime, server_default=func.now())


# ─── Model: O'yin o'ynash hisoblagi ──────────────────────────────────────────

class GamePlayCount(Base):
    """Har o'quvchi har o'yin uchun so'nggi o'ynash vaqti (3 soatlik blok)."""
    __tablename__ = "game_play_counts"
    __table_args__ = (UniqueConstraint("user_id", "game_type", "date_str"),)

    id:             Mapped[int]               = mapped_column(primary_key=True, autoincrement=True)
    user_id:        Mapped[int]               = mapped_column(BigInteger, nullable=False, index=True)
    game_type:      Mapped[str]               = mapped_column(String(30), nullable=False)
    date_str:       Mapped[str]               = mapped_column(String(20), nullable=False)  # eski mos. kaliti
    play_count:     Mapped[int]               = mapped_column(Integer, default=0)
    last_played_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ─── Model: Referal o'quvchi ──────────────────────────────────────────────────

class ReferralStudent(Base):
    """Kutilayotgan o'quvchilar (referal yoki to'g'ridan-to'g'ri ariza)."""
    __tablename__ = "referral_students"

    id:                Mapped[int]           = mapped_column(primary_key=True, autoincrement=True)
    referrer_user_id:  Mapped[int]           = mapped_column(BigInteger, nullable=False, index=True)
    # referrer_user_id=0 → to'g'ridan-to'g'ri ariza (referral yo'q)
    telegram_user_id:  Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, unique=True)
    full_name:         Mapped[str]           = mapped_column(String(255), nullable=False)
    age:               Mapped[str]           = mapped_column(String(10),  nullable=False)
    location:          Mapped[str]           = mapped_column(String(255), nullable=False)
    interests:         Mapped[str]           = mapped_column(String(500), nullable=False)
    phone:             Mapped[str]           = mapped_column(String(20),  nullable=False)
    status:            Mapped[str]           = mapped_column(String(20),  default="pending")  # pending/approved/rejected
    group_name:        Mapped[Optional[str]] = mapped_column(String(50),  nullable=True)
    xp_awarded:        Mapped[bool]          = mapped_column(Boolean, default=False)
    created_at:        Mapped[datetime]      = mapped_column(DateTime, server_default=func.now())
    # Yangi fieldlar: rad etish sababi + guruh ma'lumotlari
    reject_reason:     Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    registration_type: Mapped[str]           = mapped_column(String(20),  default="direct", server_default="direct")
    # registration_type: "referral" (taklif orqali) | "direct" (mustaqil ariza)
    has_group:         Mapped[bool]          = mapped_column(Boolean, default=False, server_default="0")
    group_time:        Mapped[Optional[str]] = mapped_column(String(20),  nullable=True)
    group_day_type:    Mapped[Optional[str]] = mapped_column(String(10),  nullable=True)   # ODD/EVEN
    teacher_name:      Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    mars_id:           Mapped[Optional[str]] = mapped_column(String(20),  nullable=True)   # Tasdiqlangandan keyin


# ─── Model: Admin profili ─────────────────────────────────────────────────────

class AdminProfile(Base):
    """Admin Mini App profili."""
    __tablename__ = "admin_profiles"

    telegram_id:  Mapped[int]           = mapped_column(BigInteger, primary_key=True)
    display_name: Mapped[str]           = mapped_column(String(255), nullable=False)
    avatar_emoji: Mapped[str]           = mapped_column(String(20),  default="👨‍💼")
    created_at:   Mapped[datetime]      = mapped_column(DateTime, server_default=func.now())
    last_active:  Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ─── XP Darajalar jadvali ─────────────────────────────────────────────────────

# Level oshganda beriladigan bonus XP
LEVEL_UP_BONUS: dict[int, int] = {
    2: 50,   3: 100,  4: 150,  5: 200,  6: 300,  7: 500,
    8: 600,  9: 700,  10: 1000,
    11: 1200, 12: 1500, 13: 2000, 14: 2500, 15: 3000,
    16: 3500, 17: 4000, 18: 5000, 19: 6000, 20: 8000,
}


def _apply_xp_multiplier(level: int, amount: int) -> int:
    """Darajaga qarab XP multiplier: 6+=2x, 10+=3x, 15+=4x."""
    if level >= 15: return amount * 4
    if level >= 10: return amount * 3
    if level >= 6:  return amount * 2
    return amount


XP_WEEKLY_BONUS: int = 100  # Haftalik 7-kun streak bonusi

XP_LEVELS: list[tuple[int, int, str]] = [
    (0,     1,  "Yangi boshlovchi"),
    (100,   2,  "O'quvchi"),
    (250,   3,  "Faol o'quvchi"),
    (500,   4,  "Bilimdon"),
    (800,   5,  "A'lochi"),
    (1200,  6,  "Yulduz o'quvchi"),
    (1800,  7,  "Ustoz"),
    (2500,  8,  "Mohir"),
    (3500,  9,  "Tajribali"),
    (5000,  10, "Expert"),
    (6500,  11, "Master"),
    (8500,  12, "Grand Master"),
    (11000, 13, "Chempion"),
    (14000, 14, "Super Chempion"),
    (18000, 15, "Professor"),
    (22000, 16, "Elita"),
    (28000, 17, "Legenda"),
    (35000, 18, "Super Legenda"),
    (43000, 19, "Milliy Qahramon"),
    (52000, 20, "Kosmik Daho"),
]


def _calc_level(xp: int) -> int:
    """XP miqdori bo'yicha darajani hisoblaydi."""
    level = 1
    for min_xp, lvl, _ in XP_LEVELS:
        if xp >= min_xp:
            level = lvl
    return level


def _level_name(level: int) -> str:
    """Daraja nomi."""
    _names = {lvl: name for _, lvl, name in XP_LEVELS}
    return _names.get(level, "O'quvchi")


def _next_level_xp(current_level: int) -> Optional[int]:
    """Keyingi daraja uchun kerakli minimal XP."""
    for min_xp, lvl, _ in XP_LEVELS:
        if lvl == current_level + 1:
            return min_xp
    return None  # Max daraja


# ─── Servis ───────────────────────────────────────────────────────────────────

class DatabaseService:

    def __init__(self, database_url: str) -> None:
        self.engine = create_async_engine(database_url, echo=False)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def init_db(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Migration: phone_number ustuni yo'q bo'lsa qo'shamiz
            try:
                await conn.execute(
                    __import__("sqlalchemy").text(
                        "ALTER TABLE students ADD COLUMN phone_number VARCHAR(20)"
                    )
                )
                logger.info("Migration: students.phone_number ustuni qo'shildi.")
            except Exception:
                pass  # Ustun allaqon mavjud — xato e'tiborsiz qoldiriladi
            try:
                await conn.execute(
                    __import__("sqlalchemy").text(
                        "ALTER TABLE attendance ADD COLUMN reason VARCHAR(500)"
                    )
                )
                logger.info("Migration: attendance.reason ustuni qo'shildi.")
            except Exception:
                pass
            try:
                await conn.execute(
                    __import__("sqlalchemy").text(
                        "ALTER TABLE curator_sessions ADD COLUMN last_active DATETIME"
                    )
                )
                logger.info("Migration: curator_sessions.last_active ustuni qo'shildi.")
            except Exception:
                pass
            # Gamification colonlari
            for _col, _def in [
                ("xp",               "INTEGER NOT NULL DEFAULT 0"),
                ("level",            "INTEGER NOT NULL DEFAULT 1"),
                ("streak_days",      "INTEGER NOT NULL DEFAULT 0"),
                ("last_streak_date", "VARCHAR(20)"),
                ("avatar_emoji",     "VARCHAR(20)"),
                ("game_wins",        "INTEGER NOT NULL DEFAULT 0"),
                ("xp_notice_seen",   "BOOLEAN NOT NULL DEFAULT 1"),
            ]:
                try:
                    await conn.execute(
                        __import__("sqlalchemy").text(
                            f"ALTER TABLE students ADD COLUMN {_col} {_def}"
                        )
                    )
                    logger.info(f"Migration: students.{_col} ustuni qo'shildi.")
                except Exception:
                    pass
            # referral_students jadvaliga yangi ustunlar
            for _col, _def in [
                ("reject_reason",     "VARCHAR(500)"),
                ("registration_type", "VARCHAR(20) NOT NULL DEFAULT 'direct'"),
                ("has_group",         "BOOLEAN NOT NULL DEFAULT 0"),
                ("group_time",        "VARCHAR(20)"),
                ("group_day_type",    "VARCHAR(10)"),
                ("teacher_name",      "VARCHAR(100)"),
                ("mars_id",           "VARCHAR(20)"),
            ]:
                try:
                    await conn.execute(
                        __import__("sqlalchemy").text(
                            f"ALTER TABLE referral_students ADD COLUMN {_col} {_def}"
                        )
                    )
                    logger.info(f"Migration: referral_students.{_col} ustuni qo'shildi.")
                except Exception:
                    pass
            # game_play_counts.last_played_at — 3 soatlik cooldown uchun
            try:
                await conn.execute(
                    __import__("sqlalchemy").text(
                        "ALTER TABLE game_play_counts ADD COLUMN last_played_at DATETIME"
                    )
                )
                logger.info("Migration: game_play_counts.last_played_at ustuni qo'shildi.")
            except Exception:
                pass
            # Eski kunlik yozuvlarni tozalash (cooldown tizimiga o'tish)
            try:
                await conn.execute(
                    __import__("sqlalchemy").text(
                        "DELETE FROM game_play_counts WHERE date_str != 'cooldown'"
                    )
                )
                logger.info("Migration: eski game_play_counts yozuvlari tozalandi.")
            except Exception:
                pass
        logger.info("Ma'lumotlar bazasi muvaffaqiyatli ishga tushdi.")

    # ── CREATE / UPDATE ────────────────────────────────────────────────────────

    async def add_group(
        self,
        chat_id: int,
        name: str,
        group_type: GroupType,
        audience: AudienceType,
    ) -> Group:
        """Yangi guruh qo'shadi yoki mavjudini yangilaydi (upsert)."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Group).where(Group.chat_id == chat_id)
            )
            existing: Optional[Group] = result.scalar_one_or_none()

            if existing:
                existing.name       = name
                existing.group_type = group_type
                existing.audience   = audience
                existing.is_active  = True
                await session.commit()
                logger.info(f"Guruh yangilandi: '{name}' ({chat_id})")
                return existing

            group = Group(
                chat_id=chat_id, name=name,
                group_type=group_type, audience=audience,
            )
            session.add(group)
            await session.commit()
            await session.refresh(group)
            logger.info(
                f"Yangi guruh: '{name}' ({chat_id}) | "
                f"{group_type.value} | {audience.value}"
            )
            return group

    async def save_message_id(self, chat_id: int, message_id: int) -> None:
        """Guruhga yuborilgan oxirgi xabar ID sini saqlaydi."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Group).where(Group.chat_id == chat_id)
            )
            group = result.scalar_one_or_none()
            if group:
                group.last_message_id = message_id
                await session.commit()

    async def clear_message_id(self, chat_id: int) -> None:
        """Guruhning last_message_id sini tozalaydi."""
        await self.save_message_id(chat_id, None)

    # ── READ ───────────────────────────────────────────────────────────────────

    async def get_groups_by_type(self, group_type: GroupType) -> list[Group]:
        """Aktiv guruhlarni jadval turi bo'yicha qaytaradi (PARENT + STUDENT)."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Group).where(
                    Group.group_type == group_type,
                    Group.is_active  == True,  # noqa: E712
                )
            )
            return list(result.scalars().all())

    async def get_all_groups(self) -> list[Group]:
        async with self.session_factory() as session:
            result = await session.execute(select(Group))
            return list(result.scalars().all())

    async def get_parent_groups(self) -> list[Group]:
        """Barcha aktiv ota-onalar guruhlarini qaytaradi (AudienceType.PARENT)."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Group).where(
                    Group.audience  == AudienceType.PARENT,
                    Group.is_active == True,  # noqa: E712
                )
            )
            return list(result.scalars().all())

    async def get_group_by_chat_id(self, chat_id: int) -> Optional[Group]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Group).where(Group.chat_id == chat_id)
            )
            return result.scalar_one_or_none()

    # ── BOT CHATS (bot a'zo bo'lgan guruhlar) ──────────────────────────────────

    async def save_bot_chat(self, chat_id: int, title: str) -> None:
        """Bot qo'shilgan guruhni saqlaydi yoki nomini yangilaydi."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(BotChat).where(BotChat.chat_id == chat_id)
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.title = title
            else:
                session.add(BotChat(chat_id=chat_id, title=title))
            await session.commit()
            logger.info(f"BotChat saqlandi: '{title}' ({chat_id})")

    async def remove_bot_chat(self, chat_id: int) -> None:
        """Bot guruhdan chiqarilganda o'chiradi."""
        async with self.session_factory() as session:
            await session.execute(
                delete(BotChat).where(BotChat.chat_id == chat_id)
            )
            await session.commit()

    async def get_bot_chats(self) -> list[BotChat]:
        """Bot a'zo bo'lgan barcha guruhlarni qaytaradi."""
        async with self.session_factory() as session:
            result = await session.execute(select(BotChat).order_by(BotChat.title))
            return list(result.scalars().all())

    async def get_unregistered_bot_chats(self) -> list[BotChat]:
        """Hali ro'yxatga qo'shilmagan bot guruhlarini qaytaradi."""
        async with self.session_factory() as session:
            # groups jadvalidagi chat_id larni olamiz
            registered = await session.execute(select(Group.chat_id))
            registered_ids = {row[0] for row in registered.fetchall()}

            result = await session.execute(select(BotChat).order_by(BotChat.title))
            all_chats = result.scalars().all()
            return [c for c in all_chats if c.chat_id not in registered_ids]

    # ── STUDENTS ───────────────────────────────────────────────────────────────

    async def register_student(
        self,
        user_id: int,
        telegram_username: Optional[str],
        full_name: str,
        mars_id: str,
        group_name: str,
        phone_number: Optional[str] = None,
    ) -> tuple["Student", bool]:
        """Yangi o'quvchi qo'shadi yoki mavjudini yangilaydi.

        Returns: (student, is_new)
          is_new=True  → haqiqatan yangi o'quvchi (XP bonusi berish mumkin)
          is_new=False → mavjud o'quvchi yangilandi (XP, level, streak SAQLANADI)
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(Student).where(Student.user_id == user_id)
            )
            existing = result.scalar_one_or_none()
            if existing:
                # Faqat profil ma'lumotlarini yangilaymiz —
                # xp, level, streak_days, last_streak_date ni TEGINMAYMIZ
                existing.telegram_username = telegram_username
                existing.full_name         = full_name
                existing.mars_id           = mars_id
                existing.group_name        = group_name
                if phone_number:
                    existing.phone_number  = phone_number
                await session.commit()
                logger.info(
                    f"O'quvchi yangilandi (XP saqlanadi): {full_name} | "
                    f"xp={existing.xp} | TG:{user_id}"
                )
                return existing, False
            student = Student(
                user_id=user_id,
                telegram_username=telegram_username,
                full_name=full_name,
                mars_id=mars_id,
                group_name=group_name,
                phone_number=phone_number,
            )
            session.add(student)
            await session.commit()
            await session.refresh(student)
            logger.info(f"Yangi o'quvchi: {full_name} | {group_name} | TG:{user_id}")
            return student, True

    async def update_student_phone(self, user_id: int, phone_number: str) -> bool:
        """O'quvchining telefon raqamini yangilaydi."""
        async with self.session_factory() as session:
            result = await session.execute(select(Student).where(Student.user_id == user_id))
            s = result.scalar_one_or_none()
            if not s:
                return False
            s.phone_number = phone_number
            await session.commit()
            return True

    async def get_student(self, user_id: int) -> Optional["Student"]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Student).where(Student.user_id == user_id)
            )
            return result.scalar_one_or_none()

    async def get_students_by_group(self, group_name: str) -> list["Student"]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Student).where(Student.group_name == group_name)
            )
            return list(result.scalars().all())

    async def get_students_count(self) -> int:
        """Jami ro'yxatdan o'tgan o'quvchilar soni."""
        from sqlalchemy import func as sqlfunc
        async with self.session_factory() as session:
            result = await session.execute(select(sqlfunc.count()).select_from(Student))
            return result.scalar_one() or 0

    async def get_all_students(self) -> list["Student"]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Student).order_by(Student.group_name, Student.full_name)
            )
            return list(result.scalars().all())

    async def get_student_by_mars_id(self, mars_id: str) -> Optional["Student"]:
        """Mars ID bo'yicha o'quvchini qaytaradi."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Student).where(Student.mars_id == mars_id)
            )
            return result.scalar_one_or_none()

    # ── HOMEWORK ───────────────────────────────────────────────────────────────

    async def set_homework(
        self,
        group_name: str,
        from_chat_id: int,
        message_id: int,
    ) -> None:
        """Guruhning uy vazifasini saqlaydi yoki yangilaydi (har guruh uchun 1 ta)."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Homework).where(Homework.group_name == group_name)
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.from_chat_id = from_chat_id
                existing.message_id   = message_id
                existing.sent_at      = datetime.now()
            else:
                session.add(Homework(
                    group_name=group_name,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                    sent_at=datetime.now(),
                ))
            await session.commit()

        # Tarix jadvaliga ham qo'shamiz
        await self.add_homework_history(group_name, from_chat_id, message_id)

    async def delete_homework(self, group_name: str) -> bool:
        """Guruh uy vazifasini o'chiradi."""
        async with self.session_factory() as session:
            result = await session.execute(
                delete(Homework).where(Homework.group_name == group_name)
            )
            await session.commit()
            return result.rowcount > 0

    async def get_homework(self, group_name: str) -> Optional["Homework"]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Homework).where(Homework.group_name == group_name)
            )
            return result.scalar_one_or_none()

    # ── DELETE STUDENT ─────────────────────────────────────────────────────────

    async def delete_student(self, user_id: int) -> bool:
        """O'quvchini ro'yxatdan o'chiradi."""
        async with self.session_factory() as session:
            result = await session.execute(
                delete(Student).where(Student.user_id == user_id)
            )
            await session.commit()
            deleted = result.rowcount > 0
            if deleted:
                logger.info(f"O'quvchi o'chirildi: user_id={user_id}")
            return deleted

    async def get_groups_with_message(self) -> list[Group]:
        """last_message_id mavjud bo'lgan guruhlarni qaytaradi."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Group).where(Group.last_message_id.is_not(None))
            )
            return list(result.scalars().all())

    # ── DELETE ─────────────────────────────────────────────────────────────────

    async def remove_group(self, chat_id: int) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                delete(Group).where(Group.chat_id == chat_id)
            )
            await session.commit()
            deleted = result.rowcount > 0
            if deleted:
                logger.info(f"Guruh o'chirildi: chat_id={chat_id}")
            return deleted

    # ── TOGGLE ─────────────────────────────────────────────────────────────────

    async def set_group_active(self, chat_id: int, is_active: bool) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Group).where(Group.chat_id == chat_id)
            )
            group = result.scalar_one_or_none()
            if not group:
                return False
            group.is_active = is_active
            await session.commit()
            return True

    # ── LAST ACTIVE ────────────────────────────────────────────────────────────

    async def update_last_active(self, user_id: int) -> None:
        async with self.session_factory() as session:
            result = await session.execute(select(Student).where(Student.user_id == user_id))
            s = result.scalar_one_or_none()
            if s:
                s.last_active = datetime.now()
                await session.commit()

    async def get_inactive_students(self, days: int = 7) -> list["Student"]:
        """last_active NULL yoki X kundan ko'p o'tgan o'quvchilar."""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=days)
        async with self.session_factory() as session:
            result = await session.execute(
                select(Student).where(
                    (Student.last_active == None) | (Student.last_active < cutoff)  # noqa
                ).order_by(Student.group_name)
            )
            return list(result.scalars().all())

    # ── ATTENDANCE ─────────────────────────────────────────────────────────────

    async def save_attendance(
        self, user_id: int, date_str: str, status: str, reason: Optional[str] = None
    ) -> None:
        async with self.session_factory() as session:
            existing = await session.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.user_id == user_id,
                    AttendanceRecord.date_str == date_str,
                )
            )
            rec = existing.scalar_one_or_none()
            if rec:
                rec.status = status
                if reason is not None:
                    rec.reason = reason
            else:
                session.add(AttendanceRecord(
                    user_id=user_id, date_str=date_str, status=status, reason=reason
                ))
            await session.commit()

    async def get_absent_students_today(self, date_str: str) -> list[tuple["AttendanceRecord", "Student"]]:
        """Bugungi kelmagan o'quvchilar va ularning sabablari."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(AttendanceRecord, Student).join(
                    Student, Student.user_id == AttendanceRecord.user_id
                ).where(
                    AttendanceRecord.date_str == date_str,
                    AttendanceRecord.status == "no",
                ).order_by(Student.group_name, Student.full_name)
            )
            return list(result.all())

    async def get_attendance_by_date(self, date_str: str) -> list["AttendanceRecord"]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(AttendanceRecord).where(AttendanceRecord.date_str == date_str)
            )
            return list(result.scalars().all())

    async def get_student_attendance(self, user_id: int, date_str: str) -> Optional["AttendanceRecord"]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.user_id == user_id,
                    AttendanceRecord.date_str == date_str,
                )
            )
            return result.scalar_one_or_none()

    # ── SCHEDULE ───────────────────────────────────────────────────────────────

    async def set_schedule(self, group_name: str, from_chat_id: int, message_id: int) -> None:
        async with self.session_factory() as session:
            result = await session.execute(select(Schedule).where(Schedule.group_name == group_name))
            existing = result.scalar_one_or_none()
            if existing:
                existing.from_chat_id = from_chat_id
                existing.message_id   = message_id
                existing.updated_at   = datetime.now()
            else:
                session.add(Schedule(group_name=group_name, from_chat_id=from_chat_id,
                                     message_id=message_id, updated_at=datetime.now()))
            await session.commit()

    async def get_schedule(self, group_name: str) -> Optional["Schedule"]:
        async with self.session_factory() as session:
            result = await session.execute(select(Schedule).where(Schedule.group_name == group_name))
            return result.scalar_one_or_none()

    # ── QUESTIONS ──────────────────────────────────────────────────────────────

    async def save_question(
        self, user_id: int, student_name: str, group_name: str,
        from_chat_id: int, message_id: int,
    ) -> "Question":
        async with self.session_factory() as session:
            q = Question(user_id=user_id, student_name=student_name, group_name=group_name,
                         from_chat_id=from_chat_id, message_id=message_id)
            session.add(q)
            await session.commit()
            await session.refresh(q)
            return q

    async def get_unanswered_questions(self) -> list["Question"]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Question).where(Question.is_answered == False)  # noqa
                .order_by(Question.created_at)
            )
            return list(result.scalars().all())

    async def mark_question_answered(self, question_id: int) -> None:
        async with self.session_factory() as session:
            result = await session.execute(select(Question).where(Question.id == question_id))
            q = result.scalar_one_or_none()
            if q:
                q.is_answered = True
                await session.commit()

    # ── HOMEWORK HISTORY ───────────────────────────────────────────────────────

    async def add_homework_history(self, group_name: str, from_chat_id: int, message_id: int) -> None:
        async with self.session_factory() as session:
            session.add(HomeworkHistory(
                group_name=group_name, from_chat_id=from_chat_id,
                message_id=message_id, sent_at=datetime.now(),
            ))
            await session.commit()

    async def get_homework_history(self, group_name: str, limit: int = 5) -> list["HomeworkHistory"]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(HomeworkHistory).where(HomeworkHistory.group_name == group_name)
                .order_by(HomeworkHistory.sent_at.desc()).limit(limit)
            )
            return list(result.scalars().all())

    # ── BOT SETTINGS ───────────────────────────────────────────────────────────

    async def get_setting(self, key: str, default: str = "") -> str:
        async with self.session_factory() as session:
            result = await session.execute(select(BotSetting).where(BotSetting.key == key))
            s = result.scalar_one_or_none()
            return s.value if s else default

    async def set_setting(self, key: str, value: str) -> None:
        async with self.session_factory() as session:
            result = await session.execute(select(BotSetting).where(BotSetting.key == key))
            s = result.scalar_one_or_none()
            if s:
                s.value = value
            else:
                session.add(BotSetting(key=key, value=value))
            await session.commit()

    # ── STUDENT CREDENTIALS (bot orqali qo'shilganlar) ────────────────────────

    async def add_student_credential(
        self, mars_id: str, name: str, password: str, group_name: str,
    ) -> None:
        async with self.session_factory() as session:
            result = await session.execute(select(StudentCredential).where(StudentCredential.mars_id == mars_id))
            existing = result.scalar_one_or_none()
            if existing:
                existing.name = name; existing.password = password; existing.group_name = group_name
            else:
                session.add(StudentCredential(mars_id=mars_id, name=name, password=password, group_name=group_name))
            await session.commit()

    async def get_student_credential(self, mars_id: str) -> Optional["StudentCredential"]:
        async with self.session_factory() as session:
            result = await session.execute(select(StudentCredential).where(StudentCredential.mars_id == mars_id))
            return result.scalar_one_or_none()

    async def get_all_student_credentials(self) -> list["StudentCredential"]:
        async with self.session_factory() as session:
            result = await session.execute(select(StudentCredential).order_by(StudentCredential.group_name))
            return list(result.scalars().all())

    async def delete_student_credential(self, mars_id: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(delete(StudentCredential).where(StudentCredential.mars_id == mars_id))
            await session.commit()
            return result.rowcount > 0

    # ── CURATOR SESSIONS ───────────────────────────────────────────────────────

    async def get_curator_session(self, telegram_id: int) -> Optional["CuratorSession"]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(CuratorSession).where(CuratorSession.telegram_id == telegram_id)
            )
            return result.scalar_one_or_none()

    async def set_curator_session(self, telegram_id: int, curator_key: str) -> None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(CuratorSession).where(CuratorSession.telegram_id == telegram_id)
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.curator_key  = curator_key
                existing.logged_in_at = datetime.now()
            else:
                session.add(CuratorSession(
                    telegram_id=telegram_id,
                    curator_key=curator_key,
                    logged_in_at=datetime.now(),
                ))
            await session.commit()

    async def remove_curator_session(self, telegram_id: int) -> None:
        async with self.session_factory() as session:
            await session.execute(
                delete(CuratorSession).where(CuratorSession.telegram_id == telegram_id)
            )
            await session.commit()

    # ── ACTIVE CURATOR CHATS ───────────────────────────────────────────────────

    async def get_active_curator_chat_by_curator(
        self, curator_telegram_id: int
    ) -> Optional["ActiveCuratorChat"]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(ActiveCuratorChat).where(
                    ActiveCuratorChat.curator_telegram_id == curator_telegram_id
                )
            )
            return result.scalar_one_or_none()

    async def get_active_curator_chat_by_student(
        self, student_user_id: int
    ) -> Optional["ActiveCuratorChat"]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(ActiveCuratorChat).where(
                    ActiveCuratorChat.student_user_id == student_user_id
                )
            )
            return result.scalar_one_or_none()

    async def start_curator_chat(
        self, curator_telegram_id: int, student_user_id: int, curator_key: str
    ) -> "ActiveCuratorChat":
        async with self.session_factory() as session:
            chat = ActiveCuratorChat(
                curator_telegram_id=curator_telegram_id,
                student_user_id=student_user_id,
                curator_key=curator_key,
                started_at=datetime.now(),
            )
            session.add(chat)
            await session.commit()
            await session.refresh(chat)
            return chat

    async def end_curator_chat_by_curator(self, curator_telegram_id: int) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                delete(ActiveCuratorChat).where(
                    ActiveCuratorChat.curator_telegram_id == curator_telegram_id
                )
            )
            await session.commit()
            return result.rowcount > 0

    # ── BUTTON STATS ───────────────────────────────────────────────────────────

    async def track_button(self, button_name: str) -> None:
        """Tugma bosilganda hisoblagichni oshiradi."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(ButtonStat).where(ButtonStat.button_name == button_name)
            )
            stat = result.scalar_one_or_none()
            if stat:
                stat.count    += 1
                stat.last_used = datetime.now()
            else:
                session.add(ButtonStat(button_name=button_name, count=1, last_used=datetime.now()))
            await session.commit()

    async def get_button_stats(self, limit: int = 30) -> list["ButtonStat"]:
        """Eng ko'p ishlatilgan tugmalar ro'yxatini qaytaradi."""
        from sqlalchemy import desc
        async with self.session_factory() as session:
            result = await session.execute(
                select(ButtonStat).order_by(desc(ButtonStat.count)).limit(limit)
            )
            return list(result.scalars().all())

    # ── CURATOR LAST ACTIVE ────────────────────────────────────────────────────

    async def update_curator_last_active(self, telegram_id: int) -> None:
        """Kurator oxirgi faolligi vaqtini yangilaydi."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(CuratorSession).where(CuratorSession.telegram_id == telegram_id)
            )
            cs = result.scalar_one_or_none()
            if cs:
                cs.last_active = datetime.now()
                await session.commit()

    async def get_all_curator_sessions(self) -> list["CuratorSession"]:
        """Barcha faol kurator sessiyalarini qaytaradi."""
        from sqlalchemy import desc
        async with self.session_factory() as session:
            result = await session.execute(
                select(CuratorSession).order_by(desc(CuratorSession.last_active))
            )
            return list(result.scalars().all())

    # ── GAMIFICATION ───────────────────────────────────────────────────────────

    async def add_xp(self, user_id: int, amount: int) -> tuple[int, int, bool, int]:
        """O'quvchiga XP qo'shadi, darajani yangilaydi.
        Returns: (new_xp, new_level, leveled_up, old_level)
        Lv.6+ uchun 2x multiplikator; level oshsa bonus XP ham qo'shiladi.
        """
        async with self.session_factory() as session:
            result = await session.execute(select(Student).where(Student.user_id == user_id))
            s = result.scalar_one_or_none()
            if not s:
                return 0, 1, False, 1
            old_level      = s.level or 1
            actual_amount  = _apply_xp_multiplier(old_level, amount)
            s.xp           = (s.xp or 0) + actual_amount
            s.level        = _calc_level(s.xp)
            leveled_up     = s.level > old_level
            # Level-up bonus XP
            if leveled_up and s.level in LEVEL_UP_BONUS:
                s.xp    += LEVEL_UP_BONUS[s.level]
                s.level  = _calc_level(s.xp)
            await session.commit()
            return s.xp, s.level, leveled_up, old_level

    async def daily_checkin(self, user_id: int) -> dict:
        """
        Kunlik kirish tekshiruvi: ketma-ketlikni yangilaydi, XP beradi.
        Returns: {already_done, xp_gained, streak_bonus, streak_days}
        """
        from datetime import date, timedelta
        today_str     = date.today().isoformat()
        yesterday_str = (date.today() - timedelta(days=1)).isoformat()
        async with self.session_factory() as session:
            result = await session.execute(select(Student).where(Student.user_id == user_id))
            s = result.scalar_one_or_none()
            if not s:
                return {"already_done": True, "xp_gained": 0, "streak_days": 0, "streak_bonus": 0}
            if s.last_streak_date == today_str:
                return {
                    "already_done": True, "xp_gained": 0,
                    "streak_days": s.streak_days or 0, "streak_bonus": 0,
                }
            # Yangi kun
            if s.last_streak_date == yesterday_str:
                s.streak_days = (s.streak_days or 0) + 1
            else:
                s.streak_days = 1
            s.last_streak_date = today_str
            s.last_active      = datetime.now()
            old_level    = s.level or 1
            xp_gained    = _apply_xp_multiplier(old_level, 5)
            streak_bonus = 0
            if s.streak_days == 7:
                streak_bonus = _apply_xp_multiplier(old_level, 20)
            elif s.streak_days == 30:
                streak_bonus = _apply_xp_multiplier(old_level, 50)
            elif s.streak_days > 7 and s.streak_days % 7 == 0:
                streak_bonus = _apply_xp_multiplier(old_level, 15)
            s.xp    = (s.xp or 0) + xp_gained + streak_bonus
            s.level = _calc_level(s.xp)
            leveled_up = s.level > old_level
            if leveled_up and s.level in LEVEL_UP_BONUS:
                s.xp    += LEVEL_UP_BONUS[s.level]
                s.level  = _calc_level(s.xp)
            await session.commit()
            return {
                "already_done": False,
                "xp_gained":    xp_gained,
                "streak_bonus": streak_bonus,
                "streak_days":  s.streak_days,
                "leveled_up":   leveled_up,
                "new_level":    s.level,
                "old_level":    old_level,
            }

    async def get_leaderboard(self, group_name: str, limit: int = 20) -> list["Student"]:
        """Guruhda XP bo'yicha eng yaxshi o'quvchilar."""
        from sqlalchemy import desc
        async with self.session_factory() as session:
            result = await session.execute(
                select(Student).where(Student.group_name == group_name)
                .order_by(desc(Student.xp)).limit(limit)
            )
            return list(result.scalars().all())

    async def get_student_rank(self, user_id: int, group_name: str) -> int:
        """O'quvchining guruhidagi o'rinini qaytaradi (1 dan boshlanadi). 0 — topilmadi."""
        from sqlalchemy import desc
        async with self.session_factory() as session:
            result = await session.execute(
                select(Student.user_id).where(Student.group_name == group_name)
                .order_by(desc(Student.xp))
            )
            ids = [row[0] for row in result.all()]
            try:
                return ids.index(user_id) + 1
            except ValueError:
                return 0

    async def save_mood(self, user_id: int, date_str: str, mood: str) -> None:
        """Kunlik kayfiyatni saqlaydi yoki yangilaydi."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(DailyMood).where(
                    DailyMood.user_id == user_id, DailyMood.date_str == date_str
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.mood = mood
            else:
                session.add(DailyMood(user_id=user_id, date_str=date_str, mood=mood))
            await session.commit()

    async def get_mood(self, user_id: int, date_str: str) -> Optional[str]:
        """Berilgan kunning kayfiyatini qaytaradi."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(DailyMood.mood).where(
                    DailyMood.user_id == user_id, DailyMood.date_str == date_str
                )
            )
            return result.scalar_one_or_none()

    async def confirm_homework(self, user_id: int, date_str: str) -> bool:
        """
        Uy vazifasini o'qilganligini belgilaydi.
        True — yangi tasdiqlash; False — allaqachon tasdiqlangan.
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(HomeworkConfirmation).where(
                    HomeworkConfirmation.user_id  == user_id,
                    HomeworkConfirmation.date_str == date_str,
                )
            )
            if result.scalar_one_or_none():
                return False
            session.add(HomeworkConfirmation(
                user_id=user_id, date_str=date_str, confirmed_at=datetime.now()
            ))
            await session.commit()
            return True

    async def is_hw_confirmed(self, user_id: int, date_str: str) -> bool:
        """Uy vazifasi tasdiqlangan bo'lsa True qaytaradi."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(HomeworkConfirmation).where(
                    HomeworkConfirmation.user_id  == user_id,
                    HomeworkConfirmation.date_str == date_str,
                )
            )
            return result.scalar_one_or_none() is not None

    async def get_hw_confirm_count(self, user_id: int) -> int:
        """O'quvchi qancha marta uy vazifasini tasdiqlaganligini qaytaradi."""
        from sqlalchemy import func as sa_func
        async with self.session_factory() as session:
            result = await session.execute(
                select(sa_func.count()).select_from(HomeworkConfirmation)
                .where(HomeworkConfirmation.user_id == user_id)
            )
            return result.scalar_one() or 0

    async def get_attend_yes_count(self, user_id: int) -> int:
        """O'quvchi necha marta darsga kelganligini qaytaradi."""
        from sqlalchemy import func as sa_func
        async with self.session_factory() as session:
            result = await session.execute(
                select(sa_func.count()).select_from(AttendanceRecord)
                .where(
                    AttendanceRecord.user_id == user_id,
                    AttendanceRecord.status  == "yes",
                )
            )
            return result.scalar_one() or 0

    # ── GLOBAL LEADERBOARD ─────────────────────────────────────────────────────

    async def get_global_leaderboard(self, limit: int = 50) -> list["Student"]:
        """Barcha guruhlar bo'yicha XP reytingi."""
        from sqlalchemy import desc
        async with self.session_factory() as session:
            result = await session.execute(
                select(Student).order_by(desc(Student.xp)).limit(limit)
            )
            return list(result.scalars().all())

    async def get_global_rank(self, user_id: int) -> int:
        """O'quvchining barcha o'quvchilar orasidagi o'rinini qaytaradi."""
        from sqlalchemy import desc
        async with self.session_factory() as session:
            result = await session.execute(
                select(Student.user_id).order_by(desc(Student.xp))
            )
            ids = [row[0] for row in result.all()]
            try:
                return ids.index(user_id) + 1
            except ValueError:
                return 0

    # ── AVATAR ─────────────────────────────────────────────────────────────────

    async def set_avatar(self, user_id: int, avatar_emoji: str) -> None:
        """O'quvchi emoji avatarini o'zgartiradi."""
        async with self.session_factory() as session:
            result = await session.execute(select(Student).where(Student.user_id == user_id))
            s = result.scalar_one_or_none()
            if s:
                s.avatar_emoji = avatar_emoji
                await session.commit()

    # ── CHAT ───────────────────────────────────────────────────────────────────

    async def get_chat_messages(
        self, limit: int = 50, after_id: int = 0
    ) -> list["ChatMessage"]:
        """Chat xabarlarini qaytaradi."""
        from sqlalchemy import desc
        async with self.session_factory() as session:
            if after_id:
                result = await session.execute(
                    select(ChatMessage).where(ChatMessage.id > after_id)
                    .order_by(ChatMessage.id).limit(limit)
                )
            else:
                result = await session.execute(
                    select(ChatMessage).order_by(desc(ChatMessage.id)).limit(limit)
                )
                msgs = list(result.scalars().all())
                msgs.reverse()
                return msgs
            return list(result.scalars().all())

    async def add_chat_message(
        self, user_id: int, full_name: str, group_name: str,
        avatar: Optional[str], text: str,
    ) -> "ChatMessage":
        """Yangi chat xabari qo'shadi."""
        async with self.session_factory() as session:
            msg = ChatMessage(
                user_id=user_id, full_name=full_name,
                group_name=group_name, avatar=avatar, text=text,
            )
            session.add(msg)
            await session.commit()
            await session.refresh(msg)
            return msg

    # ── GAMES ──────────────────────────────────────────────────────────────────

    async def save_game_score(
        self, user_id: int, game_type: str, score: int, xp_earned: int
    ) -> None:
        """O'yin natijasini saqlaydi va o'quvchiga XP beradi."""
        async with self.session_factory() as session:
            gs = GameScore(user_id=user_id, game_type=game_type, score=score, xp_earned=xp_earned)
            session.add(gs)
            await session.commit()
        if xp_earned > 0:
            await self.add_xp(user_id, xp_earned)

    async def record_game_win(self, user_id: int) -> None:
        """Multiplayer g'alaba — game_wins oshiradi."""
        async with self.session_factory() as session:
            result = await session.execute(select(Student).where(Student.user_id == user_id))
            s = result.scalar_one_or_none()
            if s:
                s.game_wins = (s.game_wins or 0) + 1
                await session.commit()

    async def get_game_best_scores(self, user_id: int) -> dict:
        """O'quvchining har bir o'yindagi eng yaxshi natijasi."""
        from sqlalchemy import func as sqlfunc
        async with self.session_factory() as session:
            result = await session.execute(
                select(GameScore.game_type, sqlfunc.max(GameScore.score))
                .where(GameScore.user_id == user_id)
                .group_by(GameScore.game_type)
            )
            return {row[0]: row[1] for row in result.all()}

    async def get_game_global_scores(self, game_type: str, limit: int = 10) -> list:
        """Global top score list for a game."""
        from sqlalchemy import func as sqlfunc, desc
        async with self.session_factory() as session:
            result = await session.execute(
                select(GameScore.user_id, sqlfunc.max(GameScore.score).label("best"))
                .where(GameScore.game_type == game_type)
                .group_by(GameScore.user_id)
                .order_by(desc("best"))
                .limit(limit)
            )
            rows = result.all()
            out = []
            for uid, best in rows:
                s = await session.get(Student, uid)  # type: ignore
                if s:
                    out.append({"user_id": uid, "full_name": s.full_name,
                                "group_name": s.group_name, "score": best,
                                "avatar": s.avatar_emoji or ""})
            return out

    # ── GAME ROOMS (Multiplayer) ───────────────────────────────────────────────

    _TYPING_TEXTS = [
        "Python dasturlash tili oddiy va o'qishga qulay sintaksisga ega.",
        "Algoritm — muammoni hal qilishning ketma-ket qadamlari to'plami.",
        "Dasturchi yaxshi kod yozish uchun har kuni mashq qilishi kerak.",
        "Loop — kodni bir necha marta takrorlaydigan dasturlash konstruktsiyasi.",
        "Function — qayta ishlatish mumkin bo'lgan kod bloki.",
    ]

    async def create_game_room(self, player1_id: int, player1_name: str, game_type: str) -> "GameRoom":
        """Yangi multiplayer xona yaratadi."""
        import random
        text = random.choice(self._TYPING_TEXTS)
        async with self.session_factory() as session:
            room = GameRoom(
                game_type=game_type, player1_id=player1_id,
                player1_name=player1_name, status="waiting",
                text_passage=text,
            )
            session.add(room)
            await session.commit()
            await session.refresh(room)
            return room

    async def get_open_game_rooms(self, game_type: str) -> list["GameRoom"]:
        """Kutayotgan (waiting) xonalarni qaytaradi."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(GameRoom)
                .where(GameRoom.game_type == game_type, GameRoom.status == "waiting")
                .order_by(GameRoom.created_at.desc())
                .limit(10)
            )
            return list(result.scalars().all())

    async def get_game_room(self, room_id: int) -> Optional["GameRoom"]:
        async with self.session_factory() as session:
            return await session.get(GameRoom, room_id)

    async def join_game_room(self, room_id: int, player2_id: int, player2_name: str) -> Optional["GameRoom"]:
        """2-o'yinchi xonaga qo'shiladi."""
        async with self.session_factory() as session:
            result = await session.execute(select(GameRoom).where(GameRoom.id == room_id))
            room = result.scalar_one_or_none()
            if room and room.status == "waiting" and room.player1_id != player2_id:
                room.player2_id   = player2_id
                room.player2_name = player2_name
                room.status       = "active"
                await session.commit()
                await session.refresh(room)
                return room
            return None

    async def update_game_progress(
        self, room_id: int, player_id: int, progress: int, finished: bool
    ) -> Optional["GameRoom"]:
        """O'yinchi typing progress'ini yangilaydi."""
        async with self.session_factory() as session:
            result = await session.execute(select(GameRoom).where(GameRoom.id == room_id))
            room = result.scalar_one_or_none()
            if not room or room.status == "finished":
                return room
            if room.player1_id == player_id:
                room.p1_progress = progress
                room.p1_finished = finished
            elif room.player2_id == player_id:
                room.p2_progress = progress
                room.p2_finished = finished
            # G'olib aniqlash
            if finished and not room.winner_id:
                room.winner_id = player_id
                room.status    = "finished"
            elif room.p1_finished and room.p2_finished and not room.winner_id:
                room.status = "finished"
            await session.commit()
            await session.refresh(room)
            return room

    # ── DUPLICATE CLEANUP ─────────────────────────────────────────────────────

    async def find_duplicate_students(self) -> list[tuple]:
        """Bir xil (group_name, mars_id) ga ega o'quvchilarni topadi."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Student).order_by(Student.group_name, Student.mars_id, Student.xp.desc())
            )
            all_students = list(result.scalars().all())
        seen: dict[tuple, Student] = {}
        dupes: list[tuple] = []  # (keep, delete) pairs
        for s in all_students:
            key = (s.group_name, s.mars_id)
            if key in seen:
                dupes.append((seen[key], s))
            else:
                seen[key] = s
        return dupes

    async def delete_student_by_id(self, student_id: int) -> None:
        """student.id bo'yicha o'quvchini o'chiradi."""
        async with self.session_factory() as session:
            result = await session.execute(select(Student).where(Student.id == student_id))
            s = result.scalar_one_or_none()
            if s:
                await session.delete(s)
                await session.commit()

    # ── GAME PLAY COUNTS (3 soatlik cooldown) ──────────────────────────────────
    #
    #   3 soatlik cooldown tizimi:
    #   O'yin tugagach, last_played_at yangilanadi.
    #   Agar hozirgi vaqt - last_played_at < 3 soat bo'lsa, o'yin bloklangan.
    #   date_str maydoni mos. kaliti sifatida saqlanadi (har doim "cooldown").
    #
    _COOLDOWN = 10800             # 3 soat (soniyalarda)

    @staticmethod
    def _cooldown_seconds_left(last_played_at) -> int:
        """last_played_at dan beri 3 soatlik blok qolgan soniyalari.
        last_played_at — DB dan kelgan naive datetime (UTC sifatida saqlanadi)."""
        import time as _time
        import calendar as _cal
        import datetime as _dt
        if last_played_at is None:
            return 0
        if not isinstance(last_played_at, _dt.datetime):
            return 0
        # timegm UTC naive datetime ni POSIX timestamp ga aylantiradi (tz-safe)
        stored_ts = _cal.timegm(last_played_at.timetuple())
        elapsed   = _time.time() - stored_ts
        return max(0, int(10800 - elapsed))

    async def get_play_window(self, user_id: int, game_type: str) -> dict:
        """3 soatlik cooldown holatini qaytaradi.
        Qaytaradi: {count, blocked, seconds_left, plays_left}"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(GamePlayCount).where(
                    GamePlayCount.user_id   == user_id,
                    GamePlayCount.game_type == game_type,
                    GamePlayCount.date_str  == "cooldown",
                )
            )
            rec = result.scalar_one_or_none()
        last_played = rec.last_played_at if rec else None
        secs = self._cooldown_seconds_left(last_played)
        blocked = secs > 0
        return {
            "count":        rec.play_count if rec else 0,
            "blocked":      blocked,
            "seconds_left": secs,
            "plays_left":   0 if blocked else 1,
        }

    async def increment_play_in_window(self, user_id: int, game_type: str) -> dict:
        """O'yin tugaganda last_played_at ni hozirgi vaqtga yangilaydi."""
        import datetime as _dt
        now = _dt.datetime.utcnow()
        async with self.session_factory() as session:
            result = await session.execute(
                select(GamePlayCount).where(
                    GamePlayCount.user_id   == user_id,
                    GamePlayCount.game_type == game_type,
                    GamePlayCount.date_str  == "cooldown",
                )
            )
            rec = result.scalar_one_or_none()
            if rec:
                rec.play_count += 1
                rec.last_played_at = now
            else:
                rec = GamePlayCount(
                    user_id=user_id, game_type=game_type,
                    date_str="cooldown", play_count=1,
                    last_played_at=now,
                )
                session.add(rec)
            await session.commit()
            count = rec.play_count
        secs = self._cooldown_seconds_left(now)
        return {
            "count":        count,
            "blocked":      True,
            "seconds_left": secs,
            "plays_left":   0,
        }

    async def get_all_play_windows(self, user_id: int) -> dict:
        """Barcha o'yinlar uchun 3 soatlik cooldown holatini qaytaradi."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(GamePlayCount).where(
                    GamePlayCount.user_id == user_id,
                    GamePlayCount.date_str == "cooldown",
                )
            )
            recs = result.scalars().all()
        out = {}
        for r in recs:
            last_played = r.last_played_at
            secs    = self._cooldown_seconds_left(last_played)
            blocked = secs > 0
            out[r.game_type] = {
                "count":        r.play_count,
                "blocked":      blocked,
                "seconds_left": secs,
                "plays_left":   0 if blocked else 1,
            }
        return out

    # Orqaga moslik uchun (eski API lar ishlashi uchun)
    async def get_or_create_play_count(self, user_id: int, game_type: str, date_str: str) -> int:
        d = await self.get_play_window(user_id, game_type)
        return d["count"]

    async def increment_play_count(self, user_id: int, game_type: str, date_str: str) -> int:
        d = await self.increment_play_in_window(user_id, game_type)
        return d["count"]

    async def get_all_play_counts_today(self, user_id: int, date_str: str) -> dict:
        d = await self.get_all_play_windows(user_id)
        return {gt: v["count"] for gt, v in d.items()}

    # ── REFERRAL ────────────────────────────────────────────────────────────────

    async def create_referral_student(self, data: dict) -> "ReferralStudent":
        """Yangi referal o'quvchini yaratadi."""
        async with self.session_factory() as session:
            rs = ReferralStudent(
                referrer_user_id  = data["referrer_user_id"],
                telegram_user_id  = data.get("telegram_user_id"),
                full_name         = data["full_name"],
                age               = data["age"],
                location          = data["location"],
                interests         = data["interests"],
                phone             = data["phone"],
                registration_type = "referral",
            )
            session.add(rs)
            await session.commit()
            await session.refresh(rs)
            return rs

    async def get_referral_students(self, status: Optional[str] = None) -> list["ReferralStudent"]:
        """Referal o'quvchilarni qaytaradi (ixtiyoriy holat filteri)."""
        from sqlalchemy import desc
        async with self.session_factory() as session:
            q = select(ReferralStudent).order_by(desc(ReferralStudent.created_at))
            if status:
                q = q.where(ReferralStudent.status == status)
            result = await session.execute(q)
            return list(result.scalars().all())

    async def approve_referral_student(self, rs_id: int, group_name: str) -> Optional["ReferralStudent"]:
        """Referal o'quvchini tasdiqlaydi va guruhga qo'shadi."""
        async with self.session_factory() as session:
            result = await session.execute(select(ReferralStudent).where(ReferralStudent.id == rs_id))
            rs = result.scalar_one_or_none()
            if rs:
                rs.status     = "approved"
                rs.group_name = group_name
                await session.commit()
                await session.refresh(rs)
            return rs

    async def reject_referral_student(self, rs_id: int) -> Optional["ReferralStudent"]:
        """Referal o'quvchini rad etadi."""
        async with self.session_factory() as session:
            result = await session.execute(select(ReferralStudent).where(ReferralStudent.id == rs_id))
            rs = result.scalar_one_or_none()
            if rs:
                rs.status = "rejected"
                await session.commit()
                await session.refresh(rs)
            return rs

    async def get_my_referrals(self, referrer_user_id: int) -> list["ReferralStudent"]:
        """Berilgan foydalanuvchi taklif qilgan o'quvchilar ro'yxati."""
        from sqlalchemy import desc
        async with self.session_factory() as session:
            result = await session.execute(
                select(ReferralStudent)
                .where(ReferralStudent.referrer_user_id == referrer_user_id)
                .order_by(desc(ReferralStudent.created_at))
            )
            return list(result.scalars().all())

    async def get_referral_count(self, referrer_user_id: int) -> int:
        """Berilgan foydalanuvchi taklif qilgan o'quvchilar soni."""
        from sqlalchemy import func as sqlfunc
        async with self.session_factory() as session:
            result = await session.execute(
                select(sqlfunc.count()).select_from(ReferralStudent)
                .where(ReferralStudent.referrer_user_id == referrer_user_id)
            )
            return result.scalar_one() or 0

    async def award_referral_xp(self, referrer_id: int, rs_id: int) -> bool:
        """Referal uchun taklif qilganga (referrer) XP beradi — bir marta.

        True  → yangi XP berildi
        False → allaqachon berilgan yoki ariza topilmadi

        MUHIM: faqat referrer +500 XP oladi.
        Yangi o'quvchi bu funksiyada XP OLMAYDI — u keyinchalik
        daily check-in va o'yinlar orqali o'z XP sini to'playdi.
        """
        async with self.session_factory() as session:
            result = await session.execute(select(ReferralStudent).where(ReferralStudent.id == rs_id))
            rs = result.scalar_one_or_none()
            if not rs or rs.xp_awarded:
                return False
            rs.xp_awarded = True
            await session.commit()
        await self.add_xp(referrer_id, 500)
        return True

    # ── ADMIN PROFILE ────────────────────────────────────────────────────────────

    async def get_admin_profile(self, telegram_id: int) -> Optional["AdminProfile"]:
        """Admin profilini qaytaradi."""
        async with self.session_factory() as session:
            return await session.get(AdminProfile, telegram_id)

    async def upsert_admin_profile(self, telegram_id: int, data: dict) -> "AdminProfile":
        """Admin profilini yaratadi yoki yangilaydi."""
        async with self.session_factory() as session:
            ap = await session.get(AdminProfile, telegram_id)
            if ap:
                if "display_name" in data:
                    ap.display_name = data["display_name"]
                if "avatar_emoji" in data:
                    ap.avatar_emoji = data["avatar_emoji"]
                ap.last_active = datetime.now()
            else:
                ap = AdminProfile(
                    telegram_id  = telegram_id,
                    display_name = data.get("display_name", f"Admin {telegram_id}"),
                    avatar_emoji = data.get("avatar_emoji", "👨‍💼"),
                    last_active  = datetime.now(),
                )
                session.add(ap)
            await session.commit()
            await session.refresh(ap)
            return ap

    async def create_direct_registration(self, data: dict) -> "ReferralStudent":
        """Mustaqil (referalsiz) ariza yaratadi."""
        async with self.session_factory() as session:
            rs = ReferralStudent(
                referrer_user_id  = 0,   # 0 = to'g'ridan-to'g'ri ariza
                telegram_user_id  = data.get("telegram_user_id"),
                full_name         = data["full_name"],
                age               = data["age"],
                location          = data["location"],
                interests         = data.get("interests", ""),
                phone             = data["phone"],
                registration_type = "direct",
                has_group         = data.get("has_group", False),
                group_time        = data.get("group_time"),
                group_day_type    = data.get("group_day_type"),
                teacher_name      = data.get("teacher_name"),
            )
            session.add(rs)
            await session.commit()
            await session.refresh(rs)
            return rs

    async def reject_referral_with_reason(self, rs_id: int, reason: str) -> Optional["ReferralStudent"]:
        """Kutayotgan o'quvchini sabab bilan rad etadi."""
        async with self.session_factory() as session:
            result = await session.execute(select(ReferralStudent).where(ReferralStudent.id == rs_id))
            rs = result.scalar_one_or_none()
            if rs:
                rs.status        = "rejected"
                rs.reject_reason = reason
                await session.commit()
                await session.refresh(rs)
            return rs

    async def approve_and_register(
        self, rs_id: int, group_name: str
    ) -> Optional["ReferralStudent"]:
        """
        Kutayotgan o'quvchini tasdiqlaydi, guruhga qo'shadi va
        students jadvaliga qo'shadi (agar telegram_user_id bo'lsa).
        Generated Mars ID: P{id:06d} ko'rinishida.

        Qayta chaqirilsa (allaqachon approved) — hech narsa o'zgarmaydi,
        mavjud rs qaytariladi. Shu sababli XP ikki marta berilmaydi
        (award_referral_xp ichida xp_awarded tekshiruvi bor).
        """
        import hashlib
        async with self.session_factory() as session:
            result = await session.execute(select(ReferralStudent).where(ReferralStudent.id == rs_id))
            rs = result.scalar_one_or_none()
            if not rs:
                return None
            # Allaqachon tasdiqlangan — qayta register qilmaymiz
            if rs.status == "approved":
                logger.warning(
                    f"approve_and_register: rs_id={rs_id} allaqachon approved, "
                    f"qayta register qilinmaydi"
                )
                return rs
            rs.status     = "approved"
            rs.group_name = group_name
            await session.commit()
            await session.refresh(rs)

        if rs.telegram_user_id:
            mars_id  = f"P{rs_id:06d}"
            password = hashlib.md5(f"{rs.telegram_user_id}".encode()).hexdigest()[:6]
            # Student credentials ga qo'shamiz (login uchun)
            await self.add_student_credential(mars_id, rs.full_name, password, group_name)
            # Students jadvaliga qo'shamiz.
            # register_student (student, is_new) qaytaradi:
            #   is_new=True  → yangi o'quvchi
            #   is_new=False → mavjud o'quvchi, xp/level/streak SAQLANADI
            _student, _is_new = await self.register_student(
                user_id           = rs.telegram_user_id,
                telegram_username = None,
                full_name         = rs.full_name,
                mars_id           = mars_id,
                group_name        = group_name,
                phone_number      = rs.phone,
            )
            # Mars ID ni referral_students jadvalida ham saqlaymiz
            async with self.session_factory() as session:
                result = await session.execute(select(ReferralStudent).where(ReferralStudent.id == rs_id))
                rs2 = result.scalar_one_or_none()
                if rs2:
                    rs2.mars_id = mars_id
                    await session.commit()
                    await session.refresh(rs2)
                    return rs2
        return rs

    async def get_pending_registration_by_user(self, telegram_user_id: int) -> Optional["ReferralStudent"]:
        """Telegram user ID bo'yicha kutayotgan arizani qaytaradi."""
        from sqlalchemy import desc
        async with self.session_factory() as session:
            result = await session.execute(
                select(ReferralStudent)
                .where(ReferralStudent.telegram_user_id == telegram_user_id)
                .order_by(desc(ReferralStudent.created_at))
                .limit(1)
            )
            return result.scalar_one_or_none()

    # ── STUDENT PROGRESS HELPER ─────────────────────────────────────────────────

    async def get_student_progress(self, user_id: int) -> Optional[dict]:
        """O'quvchining joriy XP va daraja ma'lumotlarini qaytaradi."""
        async with self.session_factory() as session:
            result = await session.execute(select(Student).where(Student.user_id == user_id))
            s = result.scalar_one_or_none()
            if not s:
                return None
            lvl = s.level or 1
            return {
                "xp":            s.xp or 0,
                "level":         lvl,
                "streak_days":   s.streak_days or 0,
                "level_name":    _level_name(lvl),
                "next_level_xp": _next_level_xp(lvl),
            }

    # ── GROUP LEADERBOARD ────────────────────────────────────────────────────────

    async def get_group_leaderboard(self, group_name: str, limit: int = 20) -> list["Student"]:
        """Guruh ichidagi reyting (XP bo'yicha)."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Student)
                .where(Student.group_name == group_name)
                .order_by(Student.xp.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    # ── MONTHLY LEADERBOARD ──────────────────────────────────────────────────────

    async def get_monthly_leaderboard(self, year_month: str, limit: int = 50) -> list[dict]:
        """Oy bo'yicha o'quvchilar reytingi — o'sha oyda topilgan XP (game_scores dan)."""
        from sqlalchemy import func as sqlfunc
        import calendar
        # Oyning birinchi va oxirgi kunini hisoblash
        year, month = int(year_month.split("-")[0]), int(year_month.split("-")[1])
        _, last_day = calendar.monthrange(year, month)
        date_from = f"{year_month}-01"
        date_to   = f"{year_month}-{last_day:02d} 23:59:59"
        async with self.session_factory() as session:
            # game_scores dan o'sha oy uchun XP summasi
            result = await session.execute(
                select(
                    GameScore.user_id,
                    sqlfunc.sum(GameScore.xp_earned).label("monthly_xp"),
                )
                .where(GameScore.created_at >= date_from)
                .where(GameScore.created_at <= date_to)
                .group_by(GameScore.user_id)
                .order_by(sqlfunc.sum(GameScore.xp_earned).desc())
                .limit(limit)
            )
            rows = result.all()
            user_ids = [r.user_id for r in rows]
            if not user_ids:
                return []
            stu_result = await session.execute(
                select(Student).where(Student.user_id.in_(user_ids))
            )
            stu_map = {s.user_id: s for s in stu_result.scalars().all()}
            out = []
            for i, r in enumerate(rows):
                s = stu_map.get(r.user_id)
                if s:
                    out.append({
                        "rank": i + 1,
                        "user_id": s.user_id,
                        "full_name": s.full_name,
                        "group_name": s.group_name,
                        "monthly_xp": r.monthly_xp or 0,
                        "level": s.level or 1,
                        "avatar": s.avatar_emoji or "",
                    })
            return out

    # ── ADMIN: DAVOMAT O'ZGARTIRISH ──────────────────────────────────────────────

    async def admin_set_attendance(self, user_id: int, date_str: str, status: str) -> bool:
        """Admin tomonidan o'quvchi davomati o'rnatiladi/o'zgartiriladi."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.user_id == user_id,
                    AttendanceRecord.date_str == date_str,
                )
            )
            rec = result.scalar_one_or_none()
            if rec:
                rec.status = status
            else:
                session.add(AttendanceRecord(user_id=user_id, date_str=date_str, status=status))
            await session.commit()
            return True

    # ── ADMIN: OGOHLANTIRISHLAR ──────────────────────────────────────────────────

    async def get_absent_streak_students(self, days: int = 3) -> list[dict]:
        """N kun ketma-ket kelmagan o'quvchilar ro'yxati."""
        from datetime import date, timedelta
        today = date.today()
        check_dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
        async with self.session_factory() as session:
            students = (await session.execute(select(Student))).scalars().all()
            result = []
            for s in students:
                absent_all = True
                for d in check_dates:
                    att = (await session.execute(
                        select(AttendanceRecord).where(
                            AttendanceRecord.user_id == s.user_id,
                            AttendanceRecord.date_str == d,
                        )
                    )).scalar_one_or_none()
                    if not att or att.status == "yes":
                        absent_all = False
                        break
                if absent_all:
                    result.append({
                        "user_id": s.user_id,
                        "full_name": s.full_name,
                        "group_name": s.group_name,
                        "telegram_username": s.telegram_username or "",
                        "absent_days": days,
                    })
            return result

    # ── ADMIN: HAFTALIK DAVOMAT STATISTIKASI ─────────────────────────────────────

    async def get_weekly_attendance_stats(self, days: int = 7) -> list[dict]:
        """Oxirgi N kun uchun davomat foizi."""
        from datetime import date, timedelta
        today = date.today()
        students_count = len((await self.get_all_students()))
        result = []
        day_names = ["Yak", "Dush", "Sesh", "Chor", "Pay", "Juma", "Shan"]
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            date_str = d.strftime("%Y-%m-%d")
            records = await self.get_attendance_by_date(date_str)
            present = sum(1 for r in records if r.status == "yes")
            pct = round((present / students_count * 100) if students_count else 0)
            result.append({
                "date": date_str,
                "label": day_names[d.weekday() % 7] if d.weekday() < 7 else day_names[6],
                "present": present,
                "total": students_count,
                "pct": pct,
            "present_pct": pct,
            })
        return result

    # ── STREAK REMINDER ──────────────────────────────────────────────────────────

    async def get_students_without_checkin_today(self, today_str: str) -> list["Student"]:
        """Bugun hali Mini App ga kirmagan o'quvchilar (streak eslatmasi uchun)."""
        async with self.session_factory() as session:
            # DailyMood yoki streak_date dan bugun kirmagan o'quvchilar
            result = await session.execute(
                select(Student).where(
                    Student.last_streak_date != today_str,
                    Student.user_id != None,
                )
            )
            return list(result.scalars().all())

    # ── WEEKLY BONUS CHECK ────────────────────────────────────────────────────────

    async def get_students_with_7day_streak(self) -> list["Student"]:
        """7 kun ketma-ket streak bo'lgan o'quvchilar (haftalik bonus uchun)."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Student).where(Student.streak_days >= 7)
            )
            return list(result.scalars().all())

    # ── XP RESET ──────────────────────────────────────────────────────────────────

    async def reset_all_xp(self) -> int:
        """Barcha o'quvchilarning XP va level larini 0/1 ga qaytaradi.
        xp_notice_seen=False — keyingi kirishda xabarnoma ko'rsatiladi.
        Qaytaradi: ta'sirlangan o'quvchilar soni."""
        async with self.session_factory() as session:
            result = await session.execute(
                update(Student).values(
                    xp=0,
                    level=1,
                    xp_notice_seen=False,
                )
            )
            await session.commit()
            return result.rowcount

    async def mark_xp_notice_seen(self, user_id: int) -> None:
        """Foydalanuvchi XP reset xabarnomasini ko'rdi deb belgilash."""
        async with self.session_factory() as session:
            await session.execute(
                update(Student)
                .where(Student.user_id == user_id)
                .values(xp_notice_seen=True)
            )
            await session.commit()
