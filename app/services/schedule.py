"""Turns the weekly routine + one-off changes into concrete dated sessions."""
from dataclasses import dataclass
from datetime import date, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Course, RoutineSlot, SessionChange, Teacher
from app.services.dates import fmt_date, fmt_time


@dataclass
class Session:
    course_id: int
    course: str
    day: date
    start: time | None
    end: time | None
    room: str | None
    status: str = "normal"        # normal|cancelled|rescheduled|room_change|extra_class
    note: str | None = None

    def label(self) -> str:
        room = f" (Room {self.room})" if self.room else ""
        end = f"–{fmt_time(self.end)}" if self.end else ""
        flag = "" if self.status == "normal" else f" [{self.status.replace('_', ' ').upper()}]"
        return f"{fmt_date(self.day)} {fmt_time(self.start)}{end} {self.course}{room}{flag}"


@dataclass
class ClassData:
    courses: list
    teachers: dict                # teacher_id -> Teacher
    slots: list
    changes: list                 # session changes from today on


async def load_class(s: AsyncSession, classroom_id: int, today: date) -> ClassData:
    courses = list(await s.scalars(select(Course).where(Course.classroom_id == classroom_id)))
    teachers = {t.id: t for t in await s.scalars(select(Teacher).where(Teacher.classroom_id == classroom_id))}
    slots = list(await s.scalars(select(RoutineSlot).where(RoutineSlot.classroom_id == classroom_id)
                                 .order_by(RoutineSlot.weekday, RoutineSlot.start_time)))
    changes = list(await s.scalars(select(SessionChange).where(SessionChange.classroom_id == classroom_id,
                                                                SessionChange.session_date >= today)))
    return ClassData(courses, teachers, slots, changes)


def build_sessions(slots, changes, titles: dict[int, str], first: date, days: int) -> list[Session]:
    """Concrete sessions for `days` days starting at `first`, with changes applied."""
    last = first + timedelta(days=days - 1)
    out = []
    for i in range(days):
        d = first + timedelta(days=i)
        out += [Session(sl.course_id, titles.get(sl.course_id, "?"), d, sl.start_time, sl.end_time, sl.room)
                for sl in slots if sl.weekday == d.weekday()]
    for ch in changes:
        if not first <= ch.session_date <= last:
            continue
        if ch.change_type == "extra_class":
            out.append(Session(ch.course_id, titles.get(ch.course_id, "?"), ch.session_date,
                               ch.new_start_time, None, ch.new_room, "extra_class", ch.note))
            continue
        for sess in out:
            if sess.course_id == ch.course_id and sess.day == ch.session_date and sess.status != "extra_class":
                sess.status, sess.note = ch.change_type, ch.note
                if ch.change_type == "rescheduled" and ch.new_start_time:
                    sess.start, sess.end = ch.new_start_time, None
                if ch.new_room:
                    sess.room = ch.new_room
    out.sort(key=lambda x: (x.day, x.start or time(0)))
    return out


def match_courses(courses, hint: str | None) -> list:
    """Courses matching a name/code hint. An exact title or code match wins over partial matches."""
    if not hint:
        return []
    h = hint.strip().lower()
    exact = [c for c in courses if c.title.lower() == h or (c.code or "").lower() == h]
    if exact:
        return exact
    return [c for c in courses if h in c.title.lower() or c.title.lower() in h]
