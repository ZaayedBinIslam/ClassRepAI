"""SQLAlchemy models. All datetimes are naive UTC (see services/dates.py)."""
from datetime import date, datetime, time

from sqlalchemy import JSON, BigInteger, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.services.dates import utcnow


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(64))       # lowercase, no '@'
    full_name: Mapped[str] = mapped_column(String(200), default="")
    has_started_bot: Mapped[bool] = mapped_column(default=False)    # pressed Start in private chat
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Classroom(Base):
    __tablename__ = "classrooms"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    name: Mapped[str] = mapped_column(String(100))
    admin_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("classroom_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    first_seen_at: Mapped[datetime] = mapped_column(default=utcnow)


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"))
    code: Mapped[str | None] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id"))


class Teacher(Base):
    __tablename__ = "teachers"
    __table_args__ = (UniqueConstraint("classroom_id", "username"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"))
    username: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    display_name: Mapped[str | None] = mapped_column(String(100))
    # pending -> awaiting_confirm (we asked them in DM) -> confirmed | rejected
    status: Mapped[str] = mapped_column(String(20), default="pending")
    added_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    @property
    def name(self) -> str:
        return self.display_name or f"@{self.username}"


class RoutineSlot(Base):
    __tablename__ = "routine_slots"
    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    weekday: Mapped[int]                                  # 0=Mon ... 6=Sun
    start_time: Mapped[time]
    end_time: Mapped[time | None]
    room: Mapped[str | None] = mapped_column(String(100))
    slot_type: Mapped[str] = mapped_column(String(10), default="theory")


class SessionChange(Base):
    __tablename__ = "session_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    session_date: Mapped[date]
    change_type: Mapped[str] = mapped_column(String(20))  # cancelled|rescheduled|room_change|extra_class
    new_start_time: Mapped[time | None]
    new_room: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(20))       # teacher_approval|announcement
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Poll(Base):
    __tablename__ = "polls"
    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"))
    kind: Mapped[str] = mapped_column(String(10))         # cancel|general
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    question: Mapped[str] = mapped_column(String(300))
    options: Mapped[list] = mapped_column(JSON)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    closes_at: Mapped[datetime]
    results: Mapped[list | None] = mapped_column(JSON)
    # open -> failed|closed (general) ; open -> failed|awaiting_teacher -> approved|declined|no_response
    status: Mapped[str] = mapped_column(String(20), default="open")
    # cancel polls only
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"))
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id"))
    session_date: Mapped[date | None]
    session_time: Mapped[time | None]
    reason: Mapped[str | None] = mapped_column(Text)
    teacher_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Draft(Base):
    """Model output waiting for a human 'yes' (routine or teacher announcement)."""
    __tablename__ = "drafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))         # routine|announcement
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|done|discarded|expired
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ClassMemory(Base):
    """Persistent decisions, fed into every brain call. Written only by code."""
    __tablename__ = "class_memory"
    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"))
    kind: Mapped[str] = mapped_column(String(20))         # poll_result|teacher_decision|announcement
    summary: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ChatMessage(Base):
    """Rolling context window (last ~50 messages per chat, max 3 days). Not an archive."""
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # None = the bot
    sender_name: Mapped[str] = mapped_column(String(200))
    text: Mapped[str | None] = mapped_column(Text)
    photo_file_id: Mapped[str | None] = mapped_column(String(200))
    reply_to_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))         # close_poll|teacher_deadline
    run_at: Mapped[datetime] = mapped_column(index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|done|failed
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class ProcessedUpdate(Base):
    """Telegram retries webhooks; we skip update_ids we've already seen."""
    __tablename__ = "processed_updates"
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    received_at: Mapped[datetime] = mapped_column(default=utcnow)
