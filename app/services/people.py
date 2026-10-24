"""Users, memberships and classroom lookups (no LLM)."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import User as TgUser

from app.models import Classroom, Membership, User


async def upsert_user(s: AsyncSession, tg: TgUser, started: bool = False) -> User:
    user = await s.scalar(select(User).where(User.telegram_user_id == tg.id))
    if user is None:
        user = User(telegram_user_id=tg.id)
        s.add(user)
    user.username = tg.username.lower() if tg.username else None
    user.full_name = tg.full_name
    if started:
        user.has_started_bot = True
    await s.flush()
    return user


async def classroom_for_chat(s: AsyncSession, chat_id: int) -> Classroom | None:
    return await s.scalar(select(Classroom).where(Classroom.telegram_chat_id == chat_id))


async def ensure_membership(s: AsyncSession, classroom_id: int, user_id: int) -> None:
    exists = await s.scalar(select(Membership.id).where(Membership.classroom_id == classroom_id,
                                                        Membership.user_id == user_id))
    if not exists:
        s.add(Membership(classroom_id=classroom_id, user_id=user_id))
        await s.flush()
