"""The fixed list of things the brain may ask for. Each function validates the model's fields,
checks permissions, and does the work. Raise ActionError(text) to tell the user why not.

Each returns optional extra HTML (already escaped) that is appended to the model's reply."""
import logging

from app.brain.context import Turn
from app.llm.schemas import Action
from app.models import Classroom
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


HANDLERS = {
    "setup_class": setup_class,
}
