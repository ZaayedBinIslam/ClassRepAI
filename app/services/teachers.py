"""Teacher linking: students add a username; the teacher confirms in private chat."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from app.models import Classroom, Course, Teacher, User
from app.utils.telegram import esc, send


async def course_names(s: AsyncSession, teacher_id: int) -> str:
    return ", ".join(c.title for c in await s.scalars(select(Course).where(Course.teacher_id == teacher_id))) \
        or "a course"


async def ask_to_confirm(bot: Bot, s: AsyncSession, teacher: Teacher, user: User) -> bool:
    """DM the teacher asking if they really teach this class. Their plain-text answer is handled by the brain."""
    teacher.user_id, teacher.status = user.id, "awaiting_confirm"
    c = await s.get(Classroom, teacher.classroom_id)
    sent = await send(bot, user.telegram_user_id,
                      f"Assalamu Alaikum! 👋 I'm ClassRepAI, the AI class rep of <b>{esc(c.name)}</b>. "
                      f"The students added you as their teacher for <b>{esc(await course_names(s, teacher.id))}</b>. "
                      f"Is that right?")
    return sent is not None


async def link_on_start(bot: Bot, s: AsyncSession, user: User) -> int:
    """Called on private /start: ask about every pending teacher entry with this username."""
    if not user.username:
        return 0
    rows = list(await s.scalars(select(Teacher).where(Teacher.username == user.username,
                                                      Teacher.status == "pending")))
    for t in rows:
        await ask_to_confirm(bot, s, t, user)
    return len(rows)
