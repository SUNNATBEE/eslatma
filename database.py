"""
database.py — Ma'lumotlar bazasi modellari va CRUD operatsiyalari.

Jadvallar:
  - groups: Guruhlar (tur: Toq/Juft, auditoriya: Ota-ona/O'quvchi)
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Integer, String, delete, select, DateTime, UniqueConstraint
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
    ) -> "Student":
        """Yangi o'quvchi qo'shadi yoki mavjudini yangilaydi."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Student).where(Student.user_id == user_id)
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.telegram_username = telegram_username
                existing.full_name         = full_name
                existing.mars_id           = mars_id
                existing.group_name        = group_name
                if phone_number:
                    existing.phone_number  = phone_number
                await session.commit()
                return existing
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
            return student

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
