"""The fixed list of things the brain may ask for. Each function validates the model's fields,
checks permissions, and does the work. Raise ActionError(text) to tell the user why not.

Each returns optional extra HTML (already escaped) that is appended to the model's reply."""
import logging
import re
from datetime import date

from sqlalchemy import select

from app.brain.context import Turn
from app.config import DEFAULT_POLL_MINUTES, MAX_POLL_MINUTES, MIN_VOTES
from app.llm.schemas import Action
from app.models import ChatMessage, Classroom, Course, Draft, Poll, SessionChange, Teacher, User
from app.services import polls, routine, teachers
from app.services.dates import fmt_clock, fmt_date, fmt_time, now_local
from app.services.memory import add_memory
from app.services.people import ensure_membership
from app.services.schedule import build_sessions, load_class, match_courses
from app.utils.telegram import esc, send

log = logging.getLogger(__name__)


class ActionError(Exception):
    """A user-facing reason why an action could not be done. Replaces the model's reply."""


GROUP_ONLY = {"setup_class", "add_teacher", "read_routine", "routine_draft_reply", "create_poll"}
TEACHER_ONLY = {"teacher_link_reply", "cancel_reply", "draft_announcement", "announcement_draft_reply"}


async def run(action: Action, t: Turn) -> str | None:
    if action.type == "none":
        return None
    handler = HANDLERS.get(action.type)
    if handler is None:
        raise ActionError("Sorry, I can't do that yet.")
    if action.type in GROUP_ONLY and not t.is_group:
        raise ActionError("Let's do that in your class group — mention me there.")
    if action.type in TEACHER_ONLY and t.role != "teacher":
        raise ActionError("Only connected teachers can do that.")
    if t.is_group and t.classroom is None and action.type != "setup_class":
        raise ActionError(f"First tell me which class this group is, e.g. \"@{t.bot.username} this is CSE 7A\".")
    log.info("action %s by user %s", action.type, t.user.id)
    return await handler(action, t)


async def setup_class(a: Action, t: Turn) -> str:
    name = (a.class_name or "").strip()[:100]
    if not name:
        raise ActionError("What's the class name? e.g. CSE 7A")
    if t.classroom:
        raise ActionError(f"This group is already set up as {t.classroom.name}.")
    c = Classroom(telegram_chat_id=t.chat_id, name=name, admin_user_id=t.user.id)
    t.s.add(c)
    await t.s.flush()
    await ensure_membership(t.s, c.id, t.user.id)
    t.classroom = c
    me = esc(f"@{t.bot.username}")
    return (f"✅ This group is now <b>{esc(name)}</b>, and {esc(t.user.full_name)} is the class admin.\n"
            f"Mention me ({me}) to send the routine (photo or text), add teachers "
            f"(<i>add @username as our DBMS teacher</i>), ask questions, or start a poll.")


async def _routine_source(t: Turn) -> tuple[str | None, str]:
    """Find the routine: photo on this message, on the replied-to message, or the sender's latest photo."""
    msg, replied = t.message, t.message.reply_to_message
    text = re.sub(rf"@{re.escape(t.bot.username)}\b", "", msg.text or msg.caption or "", flags=re.I).strip()
    if msg.photo:
        return msg.photo[-1].file_id, text
    if replied and replied.photo:
        return replied.photo[-1].file_id, text
    if replied and replied.text and replied.from_user and replied.from_user.id != t.bot.id:
        return None, replied.text
    if len(text) > 40:                          # the routine is pasted in the message itself
        return None, text
    latest = await t.s.scalar(select(ChatMessage.photo_file_id).where(
        ChatMessage.chat_id == t.chat_id, ChatMessage.user_id == t.user.id,
        ChatMessage.photo_file_id.is_not(None)).order_by(ChatMessage.id.desc()).limit(1))
    return latest, text


async def read_routine(a: Action, t: Turn) -> str:
    file_id, text = await _routine_source(t)
    if not file_id and not text:
        raise ActionError("Send me the routine as a photo (mention me in the caption) or paste it as text.")
    image = None
    if file_id:
        f = await t.bot.get_file(file_id)
        image = bytes(await f.download_as_bytearray())
    extraction = await routine.extract(image, text)
    payload = routine.clean(extraction)
    if not extraction.is_routine or not payload["slots"]:
        raise ActionError("Hmm, that doesn't look like a class routine to me 🤔 Can you send a clearer photo?")
    await routine.new_draft(t.s, t.classroom.id, t.user.id, t.chat_id, payload)
    return routine.summary(t.classroom.name, payload)


async def routine_draft_reply(a: Action, t: Turn) -> str:
    d = await t.s.get(Draft, a.item_id) if a.item_id else None
    if not d or d.kind != "routine" or d.status != "open" or d.chat_id != t.chat_id:
        raise ActionError("I don't have an open routine draft here. Send me the routine again?")
    if d.created_by != t.user.id and t.role != "admin":
        raise ActionError("Only the person who sent the routine or the class admin can decide on this draft.")
    if a.decision == "save":
        n = await routine.save(t.s, t.classroom.id, d.payload)
        d.status = "done"
        return f"✅ Routine saved: {n} classes a week. Ask me anything about it!"
    if a.decision == "edit":
        if not a.instruction:
            raise ActionError("What should I change?")
        d.payload = await routine.edit(d.payload, a.instruction)
        return routine.summary(t.classroom.name, d.payload)
    if a.decision == "discard":
        d.status = "discarded"
        return "🗑 Okay, I threw that draft away."
    raise ActionError("Should I save it, change something, or discard it?")


async def _one_course(t: Turn, hint: str | None, create: bool = False) -> Course:
    """Resolve a course name from the model to exactly one course of this class."""
    courses = list(await t.s.scalars(select(Course).where(Course.classroom_id == t.classroom.id)))
    found = match_courses(courses, hint)
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise ActionError("Which course exactly: " + ", ".join(c.title for c in found) + "?")
    if not create or not (hint or "").strip():
        known = ", ".join(c.title for c in courses) or "none yet"
        raise ActionError(f"I don't know a course called \"{hint or '?'}\". Courses I know: {known}.")
    course = Course(classroom_id=t.classroom.id, title=hint.strip()[:200])
    t.s.add(course)
    await t.s.flush()
    return course


async def add_teacher(a: Action, t: Turn) -> str:
    uname = (a.teacher_username or "").strip().lstrip("@").lower()
    if not re.fullmatch(r"[a-z0-9_]{5,32}", uname):
        raise ActionError("What's the teacher's Telegram username? (something like @rahim_sir)")
    if not a.course_hint:
        raise ActionError(f"Which course does @{uname} teach?")
    course = await _one_course(t, a.course_hint, create=True)
    teacher = await t.s.scalar(select(Teacher).where(Teacher.classroom_id == t.classroom.id,
                                                     Teacher.username == uname))
    if teacher is None:
        teacher = Teacher(classroom_id=t.classroom.id, username=uname, added_by=t.user.id)
        t.s.add(teacher)
    elif teacher.status == "rejected":
        teacher.status, teacher.user_id = "pending", None
    if a.teacher_display_name and not teacher.display_name:
        teacher.display_name = a.teacher_display_name.strip()[:100]
    await t.s.flush()
    course.teacher_id = teacher.id
    await t.s.flush()

    line = f"👍 @{esc(uname)} is now listed as the teacher for <b>{esc(course.title)}</b>."
    if teacher.status == "confirmed":
        return line + " They're already connected."
    known = await t.s.scalar(select(User).where(User.username == uname, User.has_started_bot.is_(True)))
    if known and await teachers.ask_to_confirm(t.bot, t.s, teacher, known):
        return line + " I've messaged them to confirm."
    return line + f" Ask them to open @{esc(t.bot.username)} and press Start so I can reach them."


async def teacher_link_reply(a: Action, t: Turn) -> str:
    tr = next((x for x in t.teacher_rows if x.id == a.item_id and x.status == "awaiting_confirm"), None)
    if tr is None:
        raise ActionError("There's nothing waiting for your confirmation right now.")
    c = await t.s.get(Classroom, tr.classroom_id)
    courses = await teachers.course_names(t.s, tr.id)
    if a.decision == "yes":
        tr.status = "confirmed"
        tr.display_name = tr.display_name or t.user.full_name
        await send(t.bot, c.telegram_chat_id, f"✅ {esc(tr.name)} is now connected for <b>{esc(courses)}</b>.")
        return (f"You're connected to <b>{esc(c.name)}</b> ✅. Message me here anytime to send an "
                f"announcement to the class.")
    if a.decision == "no":
        tr.status = "rejected"
        for co in await t.s.scalars(select(Course).where(Course.teacher_id == tr.id)):
            co.teacher_id = None
        await send(t.bot, c.telegram_chat_id,
                   f"⚠️ @{esc(tr.username)} says they don't teach {esc(courses)} for {esc(c.name)}. "
                   f"Please check the username.")
        return "Sorry for the trouble! I've let the class know."
    raise ActionError("Sorry, I didn't get that — do you teach this course? (yes / no)")


async def create_poll(a: Action, t: Turn) -> str:
    minutes = max(1, min(a.duration_minutes or DEFAULT_POLL_MINUTES, MAX_POLL_MINUTES))
    if a.poll_kind == "general":
        question = (a.question or "").strip()[:300]
        options = list(dict.fromkeys(o.strip()[:100] for o in (a.options or []) if o and o.strip()))[:10]
        if not question or len(options) < 2:
            raise ActionError("What should the poll ask, and what are the options?")
        p = await polls.post(t.bot, t.s, t.classroom, t.user.id, "general", question, options, minutes)
        return f"🗳 Poll is up! It closes at {fmt_clock(p.closes_at)}."
    if a.poll_kind != "cancel":
        raise ActionError("What should the poll be about?")

    # Cancellation: resolve the exact upcoming session.
    course = await _one_course(t, a.course_hint)
    now = now_local()
    data = await load_class(t.s, t.classroom.id, now.date())
    titles = {c.id: c.title for c in data.courses}
    sessions = [x for x in build_sessions(data.slots, data.changes, titles, now.date(), 14)
                if x.course_id == course.id and (x.day > now.date() or (x.start and x.start > now.time()))]
    upcoming = [x for x in sessions if x.status != "cancelled"]
    if not upcoming:
        raise ActionError(f"I don't see any upcoming {course.title} class in the next 2 weeks.")
    nexts = "; ".join(x.label() for x in upcoming[:3])
    try:
        day = date.fromisoformat(a.date) if a.date else None
    except ValueError:
        day = None
    if day is None:
        raise ActionError(f"Which {course.title} class? Next ones: {nexts}.")
    target = [x for x in upcoming if x.day == day]
    if not target:
        if any(x.day == day for x in sessions):
            raise ActionError(f"{course.title} on {fmt_date(day)} is already cancelled 🎉")
        raise ActionError(f"There's no {course.title} class on {fmt_date(day)}. Next ones: {nexts}.")
    session = target[0]   # ponytail: two slots of one course on one day -> first one; ask if that happens

    teacher = data.teachers.get(course.teacher_id)
    if teacher is None or teacher.status != "confirmed":
        raise ActionError(f"{course.title}'s teacher isn't connected yet. Tell me \"add @username as our "
                          f"{course.title} teacher\" and ask them to press Start in my private chat.")
    duplicate = await t.s.scalar(select(Poll.id).where(Poll.course_id == course.id, Poll.session_date == day,
                                                       Poll.status.in_(["open", "awaiting_teacher"])))
    if duplicate:
        raise ActionError(f"There's already a cancellation request for {course.title} on {fmt_date(day)}.")

    question = f"Ask {teacher.name} to cancel {course.title} on {fmt_date(day)} ({fmt_time(session.start)})?"
    p = await polls.post(t.bot, t.s, t.classroom, t.user.id, "cancel", question[:300], polls.CANCEL_OPTIONS,
                         minutes, course_id=course.id, teacher_id=teacher.id, session_date=day,
                         session_time=session.start, reason=(a.reason or "").strip()[:300] or None)
    return (f"🗳 Poll closes at {fmt_clock(p.closes_at)}. It passes with more yes than no "
            f"and at least {MIN_VOTES} votes.")


async def cancel_reply(a: Action, t: Turn) -> str:
    mine = {x.id for x in t.teacher_rows if x.status == "confirmed"}
    p = await t.s.get(Poll, a.item_id) if a.item_id else None
    if p is None or p.teacher_id not in mine or p.status != "awaiting_teacher":
        raise ActionError("There's no cancellation request waiting for you right now.")
    if a.decision not in ("approve", "decline"):
        raise ActionError("Sorry, I didn't get that — should the class be cancelled or not?")
    c = await t.s.get(Classroom, p.classroom_id)
    course = await t.s.get(Course, p.course_id)
    teacher = await t.s.get(Teacher, p.teacher_id)
    note = (a.message_to_class or "").strip()[:500] or None
    p.teacher_note = note
    what = f"{course.title} on {fmt_date(p.session_date)}"
    note_html = f"\n{esc(teacher.name)}'s note: <i>{esc(note)}</i>" if note else ""
    note_mem = f" Note: {note}" if note else ""

    if a.decision == "approve":
        p.status = "approved"
        t.s.add(SessionChange(classroom_id=c.id, course_id=course.id, session_date=p.session_date,
                              change_type="cancelled", source="teacher_approval", note=note))
        await add_memory(t.s, c.id, "teacher_decision", f"{teacher.name} approved cancelling {what}.{note_mem}",
                         f"poll:{p.id}")
        await send(t.bot, c.telegram_chat_id, f"✅ {esc(teacher.name)} approved: <b>{esc(what)}</b> is cancelled."
                                               f"{note_html}")
    else:
        p.status = "declined"
        await add_memory(t.s, c.id, "teacher_decision",
                         f"{teacher.name} declined cancelling {what}; the class happens as usual.{note_mem}",
                         f"poll:{p.id}")
        await send(t.bot, c.telegram_chat_id, f"❌ {esc(teacher.name)} says <b>{esc(what)}</b> will happen as "
                                               f"usual.{note_html}")
    return f"I've told {esc(c.name)} ✅"


HANDLERS = {
    "create_poll": create_poll,
    "cancel_reply": cancel_reply,
    "setup_class": setup_class,
    "read_routine": read_routine,
    "routine_draft_reply": routine_draft_reply,
    "add_teacher": add_teacher,
    "teacher_link_reply": teacher_link_reply,
}
