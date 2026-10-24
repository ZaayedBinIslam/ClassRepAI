"""Telegram helpers: trigger detection, safe sending (which also logs bot messages for context)."""
import asyncio
import html
import logging
import re

from sqlalchemy import update
from telegram import Bot, Message, ReplyParameters
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter

from app.db import SessionLocal
from app.models import ChatMessage, User

log = logging.getLogger(__name__)

esc = html.escape
BOT_NAME = "ClassRepAI"


def is_triggered(message: Message, bot_username: str, bot_id: int) -> bool:
    """Private chat, an @mention of the bot (text or caption), or a reply to one of the bot's messages."""
    if message.chat.type == ChatType.PRIVATE:
        return True
    text = message.text or message.caption or ""
    if re.search(rf"@{re.escape(bot_username)}\b", text, re.IGNORECASE):
        return True
    replied = message.reply_to_message
    return bool(replied and replied.from_user and replied.from_user.id == bot_id)


async def log_message(chat_id: int, message_id: int, user_id: int | None, sender_name: str,
                      text: str | None, photo_file_id: str | None = None,
                      reply_to: int | None = None) -> None:
    async with SessionLocal() as s:
        s.add(ChatMessage(chat_id=chat_id, telegram_message_id=message_id, user_id=user_id,
                          sender_name=sender_name, text=text, photo_file_id=photo_file_id,
                          reply_to_message_id=reply_to))
        await s.commit()


async def send(bot: Bot, chat_id: int, text: str, reply_to: int | None = None) -> Message | None:
    """Send an HTML message (caller escapes user/model text). Never raises; logs the message for context."""
    reply = ReplyParameters(message_id=reply_to, allow_sending_without_reply=True) if reply_to else None
    for attempt in range(2):
        try:
            msg = await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_parameters=reply)
            break
        except RetryAfter as e:
            wait = getattr(e.retry_after, "total_seconds", lambda: e.retry_after)()
            await asyncio.sleep(float(wait) + 1)
        except Forbidden:
            log.info("Forbidden sending to %s (blocked or removed)", chat_id)
            if chat_id > 0:   # a private chat: the user blocked the bot
                async with SessionLocal() as s:
                    await s.execute(update(User).where(User.telegram_user_id == chat_id)
                                    .values(has_started_bot=False))
                    await s.commit()
            return None
        except BadRequest as e:
            log.warning("BadRequest sending to %s: %s", chat_id, e)
            return None
    else:
        return None
    # Strip tags so the history the model sees is plain text.
    await log_message(chat_id, msg.message_id, None, BOT_NAME, re.sub(r"<[^>]+>", "", text),
                      reply_to=reply_to)
    return msg
