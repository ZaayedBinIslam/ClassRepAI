"""Class memory: decisions that must survive (poll results, teacher decisions, announcements).
Written only by code, from DB facts."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MEMORY_IN_PROMPT
from app.models import ClassMemory


async def add_memory(s: AsyncSession, classroom_id: int, kind: str, summary: str, ref: str | None = None) -> None:
    s.add(ClassMemory(classroom_id=classroom_id, kind=kind, summary=summary, source_ref=ref))
    await s.flush()


async def recent_memory(s: AsyncSession, classroom_id: int, limit: int = MEMORY_IN_PROMPT) -> list[ClassMemory]:
    # ponytail: last N entries in the prompt; add keyword/date search when a class has hundreds.
    return list(await s.scalars(select(ClassMemory).where(ClassMemory.classroom_id == classroom_id)
                                .order_by(ClassMemory.id.desc()).limit(limit)))
