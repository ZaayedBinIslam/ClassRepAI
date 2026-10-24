"""Production entrypoint: FastAPI receives Telegram webhooks; cron-job.org calls /tick every minute.

    uvicorn app.main:api
"""
import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from telegram import Update

from app.bot import ALLOWED_UPDATES, build_application, log_privacy_mode
from app.config import settings
from app.db import SessionLocal, init_db
from app.models import ProcessedUpdate
from app.services.jobs import run_due

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

application = build_application(with_updater=False)
_tasks: set[asyncio.Task] = set()   # keep references so running updates aren't garbage-collected


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    await application.initialize()
    await application.start()
    await log_privacy_mode(application)
    if settings.webhook_mode:
        await application.bot.set_webhook(url=f"{settings.PUBLIC_BASE_URL.rstrip('/')}/webhook",
                                          secret_token=settings.APP_SECRET, allowed_updates=ALLOWED_UPDATES)
    yield
    await application.stop()
    await application.shutdown()


api = FastAPI(lifespan=lifespan)


def _check(given: str | None) -> None:
    if not settings.APP_SECRET or not secrets.compare_digest(given or "", settings.APP_SECRET):
        raise HTTPException(status_code=403)


@api.post("/webhook")
async def webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(None)):
    _check(x_telegram_bot_api_secret_token)
    update = Update.de_json(await request.json(), application.bot)
    async with SessionLocal() as s:              # Telegram retries; handle each update once
        s.add(ProcessedUpdate(update_id=update.update_id))
        try:
            await s.commit()
        except IntegrityError:
            return {"ok": True}
    # Answer Telegram immediately; Gemma calls can take a while.
    task = asyncio.create_task(application.process_update(update))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"ok": True}


@api.get("/tick")
async def tick(secret: str | None = None, x_tick_secret: str | None = Header(None)):
    _check(secret or x_tick_secret)
    return {"ran": await run_due(application.bot)}


@api.get("/health")
async def health():
    try:
        async with SessionLocal() as s:
            await s.execute(text("select 1"))
        db = True
    except Exception:
        db = False
    info = await application.bot.get_webhook_info()
    return {"ok": db, "db": db, "webhook": info.url or None, "pending_updates": info.pending_update_count}
