"""Every incoming message: log it, decide if we were addressed, then think (one Gemma call) and act."""
import logging

from sqlalchemy import select
from telegram import Update
from telegram.constants import ChatAction, ChatType
from telegram.ext import ContextTypes

from app.brain.actions import ActionError, run
from app.brain.context import Turn, build_prompt
from app.db import SessionLocal
from app.llm.client import LLMError, generate_json
from app.llm.schemas import Action, BrainResult
from app.models import Teacher
from app.services.people import classroom_for_chat, ensure_membership, upsert_user
from app.utils.telegram import esc, is_triggered, log_message, send

log = logging.getLogger(__name__)

OVERLOADED = "I'm a bit overloaded right now, please try again in a minute."


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if msg is None or msg.from_user is None or msg.from_user.is_bot:
        return
    chat, bot = msg.chat, context.bot
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
    if not is_triggered(msg, bot.username, bot.id):
        return

    async with SessionLocal() as s:
        user = await upsert_user(s, msg.from_user)
        teacher_rows = []
        if is_group:
            classroom = await classroom_for_chat(s, chat.id)
            role = "admin" if classroom and classroom.admin_user_id == user.id else "student"
        else:
            classroom = None
            teacher_rows = list(await s.scalars(select(Teacher).where(
                Teacher.user_id == user.id, Teacher.status.in_(["awaiting_confirm", "confirmed"]))))
            if not teacher_rows:
                # Student private chat is a later feature; no LLM call.
                await send(bot, chat.id, "Talk to me in your class group by mentioning me — "
                                         "private chat for students is coming later 🙂")
                return
            role = "teacher"

        turn = Turn(bot=bot, s=s, user=user, message=msg, chat_id=chat.id,
                    chat_title=chat.title or "private", is_group=is_group, role=role,
                    classroom=classroom, teacher_rows=teacher_rows)
        has_photo = bool(msg.photo or (msg.reply_to_message and msg.reply_to_message.photo))

        # 4. Think.
        try:
            await bot.send_chat_action(chat.id, ChatAction.TYPING)
            prompt = await build_prompt(turn, msg.text or msg.caption or "", has_photo)
            result = await generate_json(prompt, BrainResult, purpose="brain")
        except LLMError:
            await send(bot, chat.id, OVERLOADED, reply_to=msg.message_id)
            return

        # 5. Act. If the action fails, its reason replaces the model's reply.
        try:
            extra = await run(result.action or Action(), turn)
            await s.commit()
            text = "\n\n".join(p for p in [esc(result.reply.strip()), extra] if p)
        except ActionError as e:
            await s.rollback()
            text = esc(str(e))
        except LLMError:
            await s.rollback()
            text = OVERLOADED

    if text:
        await send(bot, chat.id, text, reply_to=msg.message_id)
