"""Timers live in the `jobs` table (survives restarts). /tick (or the local JobQueue) runs due jobs."""
import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from app.config import HISTORY_DAYS, HISTORY_KEEP
from app.db import SessionLocal
from app.models import ChatMessage, Draft, Job, ProcessedUpdate
from app.services.dates import utcnow

log = logging.getLogger(__name__)


async def enqueue(s: AsyncSession, kind: str, run_at: datetime, payload: dict) -> None:
    s.add(Job(kind=kind, run_at=run_at, payload=payload))
    await s.flush()


async def run_due(bot: Bot) -> int:
    from app.services import polls   # avoid a circular import (polls enqueues jobs)
    runners = {"close_poll": polls.close_poll, "teacher_deadline": polls.teacher_deadline}

    async with SessionLocal() as s:
        due = list(await s.scalars(select(Job).where(Job.status == "pending", Job.run_at <= utcnow())
                                   .order_by(Job.run_at).limit(20).with_for_update(skip_locked=True)))
        for job in due:
            job_id, kind, payload = job.id, job.kind, job.payload
            try:
                await runners[kind](bot, s, payload)
                job.status = "done"
                await s.commit()
            except Exception as e:
                log.exception("job %s (%s) failed", job_id, kind)
                await s.rollback()
                job = await s.get(Job, job_id)
                job.attempts += 1
                job.last_error = str(e)[:500]
                if job.attempts >= 3:
                    job.status = "failed"
                await s.commit()
    await prune()
    return len(due)


async def prune() -> None:
    """Keep the chat window small and drop stale rows."""
    now = utcnow()
    async with SessionLocal() as s:
        await s.execute(delete(ProcessedUpdate).where(ProcessedUpdate.received_at < now - timedelta(days=2)))
        await s.execute(delete(ChatMessage).where(ChatMessage.created_at < now - timedelta(days=HISTORY_DAYS)))
        busy = await s.scalars(select(ChatMessage.chat_id).group_by(ChatMessage.chat_id)
                               .having(func.count() > HISTORY_KEEP))
        for chat_id in list(busy):
            cutoff = await s.scalar(select(ChatMessage.id).where(ChatMessage.chat_id == chat_id)
                                    .order_by(ChatMessage.id.desc()).offset(HISTORY_KEEP - 1).limit(1))
            await s.execute(delete(ChatMessage).where(ChatMessage.chat_id == chat_id, ChatMessage.id < cutoff))
        await s.execute(update(Draft).where(Draft.status == "open", Draft.expires_at < now).values(status="expired"))
        await s.commit()
