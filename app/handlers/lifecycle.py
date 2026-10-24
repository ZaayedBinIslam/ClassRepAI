"""Bot added to a group, and private /start."""
from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import ContextTypes

from app.db import SessionLocal
from app.services.people import upsert_user
from app.utils.telegram import esc, send


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Post a welcome when the bot is added to a group."""
    change = update.my_chat_member
    if change.chat.type == ChatType.PRIVATE:
        return
    was_in = change.old_chat_member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR)
    is_in = change.new_chat_member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR)
    if was_in or not is_in:
        return
    me = f"@{context.bot.username}"
    await send(context.bot, change.chat.id,
               f"👋 Hi! I'm <b>ClassRepAI</b>, your AI class rep.\n"
               f"Mention me with your class name to get started, e.g. <i>{me} this is CSE 7A</i>.\n\n"
               f"I read messages here so I understand the context (I keep only the last ~50 messages, "
               f"for up to 3 days), but I only reply when you mention me or reply to me.")


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Private /start: remember that this user can be messaged."""
    tg = update.effective_user
    async with SessionLocal() as s:
        await upsert_user(s, tg, started=True)
        await s.commit()
    await send(context.bot, update.effective_chat.id,
               f"Hi {esc(tg.first_name)}! 👋 I'm ClassRepAI. Add me to your class's Telegram group "
               f"and mention me there — that's where I help out.")
