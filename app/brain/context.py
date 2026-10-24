"""Builds the brain prompt for one triggered message: class info, memory, open items, recent chat.
The data is small, so we simply put all of it in the prompt (no vector search)."""
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot, Message

from app.config import HISTORY_IN_PROMPT
from app.llm.prompts import BRAIN_PROMPT, header
from app.models import ChatMessage, Classroom, Course, Draft, Poll, Teacher, User
from app.services.dates import WEEKDAYS, fmt_clock, fmt_date, fmt_time, now_local, utcnow
from app.services.memory import recent_memory
from app.services.schedule import build_sessions, load_class


@dataclass
class Turn:
    """Everything about the message we are responding to."""
    bot: Bot
    s: AsyncSession
    user: User
    message: Message
    chat_id: int
    chat_title: str
    is_group: bool
    role: str                                   # student | admin | teacher
    classroom: Classroom | None = None          # group chats
    teacher_rows: list[Teacher] = field(default_factory=list)   # teacher DMs: this user's teacher links


async def class_block(s: AsyncSession, c: Classroom) -> str:
    today = now_local().date()
    data = await load_class(s, c.id, today)
    titles = {co.id: co.title for co in data.courses}
    admin = await s.get(User, c.admin_user_id)
    lines = [f"Class: {c.name} (class admin: {admin.full_name if admin else '?'})", "Courses:"]
    for co in data.courses:
        t = data.teachers.get(co.teacher_id)
        if t is None:
            who = "no teacher added yet"
        elif t.status == "confirmed":
            who = f"teacher {t.name} (connected)"
        else:
            who = f"teacher {t.name} (not connected yet: they must press Start in my private chat)"
        code = f" [{co.code}]" if co.code else ""
        lines.append(f"- {co.title}{code}: {who}")
    if not data.courses:
        lines.append("- (none yet)")

    lines.append("Weekly routine:")
    for sl in data.slots:
        end = f"–{fmt_time(sl.end_time)}" if sl.end_time else ""
        room = f", Room {sl.room}" if sl.room else ""
        lines.append(f"- {WEEKDAYS[sl.weekday]} {fmt_time(sl.start_time)}{end} {titles.get(sl.course_id)} "
                     f"({sl.slot_type}{room})")
    if not data.slots:
        lines.append("- (no routine saved yet; a student can send me a photo or text of it)")

    sessions = build_sessions(data.slots, data.changes, titles, today, 7)
    if sessions:
        lines.append("Sessions in the next 7 days (changes applied):")
        lines += [f"- {x.label()}" + (f" note: {x.note}" if x.note else "") for x in sessions]
    later = [ch for ch in data.changes if ch.session_date >= today + timedelta(days=7)]
    if later:
        lines.append("Later changes:")
        lines += [f"- {fmt_date(ch.session_date)} {titles.get(ch.course_id)}: {ch.change_type}" for ch in later]

    polls = list(await s.scalars(select(Poll).where(Poll.classroom_id == c.id,
                                                    Poll.status.in_(["open", "awaiting_teacher"]))))
    lines.append("Open polls / requests:")
    for p in polls:
        state = f"voting, closes {fmt_clock(p.closes_at)}" if p.status == "open" else "waiting for the teacher's answer"
        lines.append(f'- "{p.question}" ({state})')
    if not polls:
        lines.append("- (none)")
    return "\n".join(lines)


async def open_items(t: Turn) -> list[str]:
    s, items = t.s, []
    q = select(Draft).where(Draft.status == "open", Draft.chat_id == t.chat_id, Draft.expires_at > utcnow())
    if t.role != "admin":                       # the class admin may answer anyone's draft in the group
        q = q.where(Draft.created_by == t.user.id)
    for d in await s.scalars(q):
        if d.kind == "routine":
            items.append(f"[routine_draft:{d.id}] routine draft ({len(d.payload['slots'])} classes) - "
                         "waiting for: save it, an edit request, or discard")
        else:
            items.append(f"[announcement_draft:{d.id}] announcement draft for {d.payload['class_name']}: "
                         f"\"{d.payload['text']}\" - waiting for: send, an edit, or discard")

    for tr in t.teacher_rows:
        if tr.status == "awaiting_confirm":
            c = await s.get(Classroom, tr.classroom_id)
            courses = ", ".join(co.title for co in await s.scalars(select(Course).where(Course.teacher_id == tr.id)))
            items.append(f"[teacher_link:{tr.id}] students of {c.name} added you as the teacher for "
                         f"{courses or 'a course'} - waiting for you to confirm (yes) or deny (no)")

    ids = [tr.id for tr in t.teacher_rows if tr.status == "confirmed"]
    if ids:
        for p in await s.scalars(select(Poll).where(Poll.teacher_id.in_(ids), Poll.status == "awaiting_teacher")):
            c = await s.get(Classroom, p.classroom_id)
            course = await s.get(Course, p.course_id)
            yes, no = (p.results or [0, 0])[:2]
            items.append(f"[cancel_poll:{p.id}] students of {c.name} ask you to cancel {course.title} on "
                         f"{fmt_date(p.session_date)} at {fmt_time(p.session_time)}. Class vote: {yes} yes / {no} no. "
                         f"Reason: {p.reason or 'not given'} - waiting for you to approve or decline")
    return items


async def history(s: AsyncSession, chat_id: int, skip_message_id: int) -> str:
    rows = list(await s.scalars(select(ChatMessage).where(ChatMessage.chat_id == chat_id,
                                                          ChatMessage.telegram_message_id != skip_message_id)
                                .order_by(ChatMessage.id.desc()).limit(HISTORY_IN_PROMPT)))
    lines = []
    for m in reversed(rows):
        photo = " [sent a photo]" if m.photo_file_id else ""
        lines.append(f"{m.sender_name}: {(m.text or '').strip()}{photo}")
    return "\n".join(lines) or "(nothing yet)"


async def build_prompt(t: Turn, message_text: str, has_photo: bool) -> str:
    classrooms = [t.classroom] if t.classroom else [await t.s.get(Classroom, tr.classroom_id)
                                                     for tr in t.teacher_rows]
    if classrooms:
        blocks, memories = [], []
        for c in classrooms:
            blocks.append(await class_block(t.s, c))
            mem = await recent_memory(t.s, c.id)
            memories += [f"- [{c.name}] {fmt_date(m.created_at.date())}: {m.summary}" for m in mem]
        class_text, memory_text = "\n\n".join(blocks), "\n".join(memories) or "(nothing decided yet)"
    else:
        class_text = "This group is not set up as a class yet. Ask them to tell you the class name (e.g. CSE 7A)."
        memory_text = "(none)"

    items = await open_items(t)
    return BRAIN_PROMPT.format(
        header=header(),
        chat_type="group chat" if t.is_group else "private chat",
        chat_title=t.chat_title,
        sender_name=t.user.full_name,
        sender_role=t.role,
        class_block=class_text,
        memory_block=memory_text,
        open_items_block="\n".join(items) or "(nothing)",
        history_block=await history(t.s, t.chat_id, t.message.message_id),
        message=message_text,
        photo_note="(This message includes or replies to a photo.)" if has_photo else "",
    )
