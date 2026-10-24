"""The fixed list of things the brain may ask for. Each function validates the model's fields,
checks permissions, and does the work. Raise ActionError(text) to tell the user why not.

Each returns optional extra HTML (already escaped) that is appended to the model's reply."""
import logging
import re

from sqlalchemy import select

from app.brain.context import Turn
from app.llm.schemas import Action
from app.models import ChatMessage, Classroom, Draft
from app.services import routine
from app.services.people import ensure_membership
from app.utils.telegram import esc

log = logging.getLogger(__name__)


class ActionError(Exception):
    """A user-facing reason why an action could not be done. Replaces the model's reply."""


GROUP_ONLY = {"setup_class", "add_teacher", "read_routine", "routine_draft_reply", "create_poll"}
TEACHER_ONLY = {"teacher_link_reply", "cancel_reply", "draft_announcement", "announcement_draft_reply"}


async def run(action: Action, t: Turn) -> str | None:
    if action.type == "none":
        return None
    handler = HANDLERS.get(action.type)
    if handler is None:
        raise ActionError("Sorry, I can't do that yet.")
    if action.type in GROUP_ONLY and not t.is_group:
        raise ActionError("Let's do that in your class group — mention me there.")
    if action.type in TEACHER_ONLY and t.role != "teacher":
        raise ActionError("Only connected teachers can do that.")
    if t.is_group and t.classroom is None and action.type != "setup_class":
        raise ActionError(f"First tell me which class this group is, e.g. \"@{t.bot.username} this is CSE 7A\".")
    log.info("action %s by user %s", action.type, t.user.id)
    return await handler(action, t)


async def setup_class(a: Action, t: Turn) -> str:
    name = (a.class_name or "").strip()[:100]
    if not name:
        raise ActionError("What's the class name? e.g. CSE 7A")
    if t.classroom:
        raise ActionError(f"This group is already set up as {t.classroom.name}.")
    c = Classroom(telegram_chat_id=t.chat_id, name=name, admin_user_id=t.user.id)
    t.s.add(c)
    await t.s.flush()
    await ensure_membership(t.s, c.id, t.user.id)
    t.classroom = c
    me = esc(f"@{t.bot.username}")
    return (f"✅ This group is now <b>{esc(name)}</b>, and {esc(t.user.full_name)} is the class admin.\n"
            f"Mention me ({me}) to send the routine (photo or text), add teachers "
            f"(<i>add @username as our DBMS teacher</i>), ask questions, or start a poll.")


async def _routine_source(t: Turn) -> tuple[str | None, str]:
    """Find the routine: photo on this message, on the replied-to message, or the sender's latest photo."""
    msg, replied = t.message, t.message.reply_to_message
    text = re.sub(rf"@{re.escape(t.bot.username)}\b", "", msg.text or msg.caption or "", flags=re.I).strip()
    if msg.photo:
        return msg.photo[-1].file_id, text
    if replied and replied.photo:
        return replied.photo[-1].file_id, text
    if replied and replied.text and replied.from_user and replied.from_user.id != t.bot.id:
        return None, replied.text
    if len(text) > 40:                          # the routine is pasted in the message itself
        return None, text
    latest = await t.s.scalar(select(ChatMessage.photo_file_id).where(
        ChatMessage.chat_id == t.chat_id, ChatMessage.user_id == t.user.id,
        ChatMessage.photo_file_id.is_not(None)).order_by(ChatMessage.id.desc()).limit(1))
    return latest, text


async def read_routine(a: Action, t: Turn) -> str:
    file_id, text = await _routine_source(t)
    if not file_id and not text:
        raise ActionError("Send me the routine as a photo (mention me in the caption) or paste it as text.")
    image = None
    if file_id:
        f = await t.bot.get_file(file_id)
        image = bytes(await f.download_as_bytearray())
    extraction = await routine.extract(image, text)
    payload = routine.clean(extraction)
    if not extraction.is_routine or not payload["slots"]:
        raise ActionError("Hmm, that doesn't look like a class routine to me 🤔 Can you send a clearer photo?")
    await routine.new_draft(t.s, t.classroom.id, t.user.id, t.chat_id, payload)
    return routine.summary(t.classroom.name, payload)


async def routine_draft_reply(a: Action, t: Turn) -> str:
    d = await t.s.get(Draft, a.item_id) if a.item_id else None
    if not d or d.kind != "routine" or d.status != "open" or d.chat_id != t.chat_id:
        raise ActionError("I don't have an open routine draft here. Send me the routine again?")
    if d.created_by != t.user.id and t.role != "admin":
        raise ActionError("Only the person who sent the routine or the class admin can decide on this draft.")
    if a.decision == "save":
        n = await routine.save(t.s, t.classroom.id, d.payload)
        d.status = "done"
        return f"✅ Routine saved: {n} classes a week. Ask me anything about it!"
    if a.decision == "edit":
        if not a.instruction:
            raise ActionError("What should I change?")
        d.payload = await routine.edit(d.payload, a.instruction)
        return routine.summary(t.classroom.name, d.payload)
    if a.decision == "discard":
        d.status = "discarded"
        return "🗑 Okay, I threw that draft away."
    raise ActionError("Should I save it, change something, or discard it?")


HANDLERS = {
    "setup_class": setup_class,
    "read_routine": read_routine,
    "routine_draft_reply": routine_draft_reply,
}
