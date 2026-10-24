"""Every incoming message: log it, decide if we were addressed, then think and act."""
import logging

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from app.db import SessionLocal
from app.services.people import classroom_for_chat, ensure_membership, upsert_user
from app.utils.telegram import is_triggered, log_message, send

log = logging.getLogger(__name__)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if msg is None or msg.from_user is None or msg.from_user.is_bot:
        return
    chat = msg.chat
    is_group = chat.type != ChatType.PRIVATE

    # 1-2. Remember who spoke and what they said (cheap, no LLM).
    async with SessionLocal() as s:
        user = await upsert_user(s, msg.from_user)
        classroom = await classroom_for_chat(s, chat.id) if is_group else None
        if classroom:
            await ensure_membership(s, classroom.id, user.id)
        await s.commit()
    photo_id = msg.photo[-1].file_id if msg.photo else None
    await log_message(chat.id, msg.message_id, user.id, msg.from_user.full_name,
                      msg.text or msg.caption, photo_id,
                      msg.reply_to_message.message_id if msg.reply_to_message else None)

    # 3. Only act when addressed.
    if not is_triggered(msg, context.bot.username, context.bot.id):
        return

    await send(context.bot, chat.id, "I'm here! (brain coming soon)", reply_to=msg.message_id)
