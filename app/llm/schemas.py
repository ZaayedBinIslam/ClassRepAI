"""Pydantic models for everything Gemma returns. Fields are lenient (strings, optionals);
brain/actions.py does the strict per-action checks."""
from typing import Literal

from pydantic import BaseModel

ActionType = Literal[
    "none",
    "setup_class",               # class_name
    "add_teacher",               # teacher_username, course_hint, teacher_display_name?
    "read_routine",              # uses the attached / replied-to photo, or the text
    "routine_draft_reply",       # item_id, decision save|edit|discard, instruction?
    "create_poll",               # poll_kind cancel|general, course_hint?, date?, reason?, question?, options?, duration_minutes?
    "teacher_link_reply",        # item_id, decision yes|no
    "cancel_reply",              # item_id, decision approve|decline, message_to_class?
    "draft_announcement",        # class_name, text, changes
    "announcement_draft_reply",  # item_id, decision send|edit|discard, text?
]


class ScheduleChangeOut(BaseModel):
    change_type: Literal["cancelled", "rescheduled", "room_change", "extra_class"]
    course_hint: str
    date: str                                  # YYYY-MM-DD
    new_start_time: str | None = None          # HH:MM
    new_room: str | None = None


class Action(BaseModel):
    type: ActionType = "none"
    item_id: int | None = None
    decision: str | None = None
    class_name: str | None = None
    teacher_username: str | None = None
    teacher_display_name: str | None = None
    course_hint: str | None = None
    date: str | None = None                    # YYYY-MM-DD
    reason: str | None = None
    poll_kind: Literal["cancel", "general"] | None = None
    question: str | None = None
    options: list[str] | None = None
    duration_minutes: int | None = None
    text: str | None = None
    instruction: str | None = None
    message_to_class: str | None = None
    changes: list[ScheduleChangeOut] = []


class BrainResult(BaseModel):
    reply: str = ""
    action: Action | None = None


class RoutineSlotOut(BaseModel):
    weekday: Literal["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"]
    start_time: str                            # HH:MM 24h
    end_time: str | None = None
    course_title: str
    course_code: str | None = None
    room: str | None = None
    slot_type: Literal["theory", "lab", "other"] = "theory"


class RoutineExtraction(BaseModel):
    is_routine: bool
    slots: list[RoutineSlotOut] = []
    uncertain_notes: list[str] = []
