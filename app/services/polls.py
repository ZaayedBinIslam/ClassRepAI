"""Polls: post, close (from a job), decide, ask the teacher, and record results in class memory."""
import logging
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.error import BadRequest

from app.config import MIN_VOTES, TEACHER_DEADLINE_HOURS
from app.llm.client import LLMError, generate_text
from app.llm.prompts import TEACHER_REQUEST_PROMPT
from app.models import Classroom, Course, Poll, Teacher, User
from app.services import jobs
from app.services.dates import fmt_clock, fmt_date, fmt_time, local_to_utc, utcnow
from app.services.memory import add_memory
from app.utils.telegram import BOT_NAME, esc, log_message, send

log = logging.getLogger(__name__)

CANCEL_OPTIONS = ["✅ Yes, request cancellation", "❌ No, keep the class"]


# ---------- pure decision rules (unit tested) ----------

def cancel_passed(yes: int, no: int) -> bool:
    return yes > no and yes + no >= MIN_VOTES


def general_winner(results: list[int]) -> int | None:
    """Index of the winning option, or None if too few votes or a tie at the top."""
    if sum(results) < MIN_VOTES:
        return None
    top = max(results)
    return results.index(top) if results.count(top) == 1 else None


# ---------- posting and closing ----------

async def post(bot: Bot, s: AsyncSession, classroom: Classroom, user_id: int, kind: str, question: str,
               options: list[str], minutes: int, **cancel_fields) -> Poll:
    msg = await bot.send_poll(classroom.telegram_chat_id, question, options, is_anonymous=False)
    p = Poll(classroom_id=classroom.id, kind=kind, created_by=user_id, question=question, options=options,
             telegram_message_id=msg.message_id, closes_at=utcnow() + timedelta(minutes=minutes), **cancel_fields)
    s.add(p)
    await s.flush()
    await jobs.enqueue(s, "close_poll", p.closes_at, {"poll_id": p.id})
    await log_message(classroom.telegram_chat_id, msg.message_id, None, BOT_NAME,
                      f"[poll] {question} Options: {' / '.join(options)}")
    return p


async def close_poll(bot: Bot, s: AsyncSession, payload: dict) -> None:
    p = await s.get(Poll, payload["poll_id"])
    if p is None or p.status != "open":
        return
    c = await s.get(Classroom, p.classroom_id)
    try:
        tg_poll = await bot.stop_poll(c.telegram_chat_id, p.telegram_message_id)
        p.results = [o.voter_count for o in tg_poll.options]
    except BadRequest as e:   # poll message deleted, or already closed by hand
        log.warning("stop_poll failed for poll %s: %s", p.id, e)
        p.results = [0] * len(p.options)
    today = fmt_date(utcnow().date())

    if p.kind == "general":
        p.status = "closed"
        counts = ", ".join(f"{o}: {n}" for o, n in zip(p.options, p.results))
        w = general_winner(p.results)
        outcome = f"→ {p.options[w]}" if w is not None else "→ no clear decision"
        await add_memory(s, c.id, "poll_result", f"Poll ({today}): \"{p.question}\" {outcome} ({counts}).",
                         f"poll:{p.id}")
        await send(bot, c.telegram_chat_id, f"🗳 Poll closed: <b>{esc(p.question)}</b>\n{esc(outcome)} ({esc(counts)})")
        return

    course = await s.get(Course, p.course_id)
    teacher = await s.get(Teacher, p.teacher_id)
    yes, no = p.results[:2]
    what = f"{course.title} on {fmt_date(p.session_date)}"
    if not cancel_passed(yes, no):
        p.status = "failed"
        why = f"only {yes + no} votes (needs {MIN_VOTES})" if yes + no < MIN_VOTES else f"{yes} yes / {no} no"
        await add_memory(s, c.id, "poll_result",
                         f"Poll ({today}): the class did NOT request cancelling {what} ({why}).", f"poll:{p.id}")
        await send(bot, c.telegram_chat_id,
                   f"🗳 Poll closed: {esc(why)}. So I won't ask {esc(teacher.name)} — {esc(what)} stays on.")
        return

    p.status = "awaiting_teacher"
    await add_memory(s, c.id, "poll_result",
                     f"Poll ({today}): the class voted {yes}–{no} to ask {teacher.name} to cancel {what}.",
                     f"poll:{p.id}")
    await send(bot, c.telegram_chat_id,
               f"🗳 Poll passed ({yes}–{no}). I'm asking {esc(teacher.name)} politely now.")
    await ask_teacher(bot, s, p, c, course, teacher)


async def ask_teacher(bot: Bot, s: AsyncSession, p: Poll, c: Classroom, course: Course, teacher: Teacher) -> None:
    yes, no = p.results[:2]
    fields = dict(class_name=c.name, teacher_name=teacher.name, course=course.title,
                  date_str=fmt_date(p.session_date), time_str=fmt_time(p.session_time), yes=yes, total=yes + no)
    try:
        reason = f" Reason given by the students: {p.reason}." if p.reason else ""
        text = (await generate_text(TEACHER_REQUEST_PROMPT.format(reason_line=reason, **fields),
                                    purpose="teacher_request")).strip()
    except LLMError:
        # Fixed fallback template, used only when the model is unavailable.
        text = ("Assalamu Alaikum, {teacher_name}. The students of {class_name} would like to request "
                "cancellation of the {course} class on {date_str} at {time_str}. {yes} of {total} students "
                "voted for it in a class poll. Would it be possible?").format(**fields)

    user = await s.get(User, teacher.user_id)
    if not user or not await send(bot, user.telegram_user_id, esc(text)):
        p.status = "no_response"
        await send(bot, c.telegram_chat_id, f"⚠️ I couldn't reach {esc(teacher.name)} in private chat. "
                                             f"Please contact them directly — assume the class is ON.")
        return

    deadline = utcnow() + timedelta(hours=TEACHER_DEADLINE_HOURS)
    if p.session_time:
        deadline = min(deadline, local_to_utc(p.session_date, p.session_time) - timedelta(minutes=30))
    await jobs.enqueue(s, "teacher_deadline", max(deadline, utcnow() + timedelta(minutes=5)), {"poll_id": p.id})


async def teacher_deadline(bot: Bot, s: AsyncSession, payload: dict) -> None:
    p = await s.get(Poll, payload["poll_id"])
    if p is None or p.status != "awaiting_teacher":
        return
    p.status = "no_response"
    c = await s.get(Classroom, p.classroom_id)
    teacher = await s.get(Teacher, p.teacher_id)
    await send(bot, c.telegram_chat_id, f"⏰ {esc(teacher.name)} hasn't answered yet (asked at "
                                         f"{fmt_clock(p.closes_at)}). Assume the class is ON unless you hear otherwise.")
