"""Routine: extract from photo/text with Gemma, validate, summarise, edit and save."""
import json
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DRAFT_HOURS
from app.llm.client import generate_json
from app.llm.prompts import ROUTINE_EDIT_PROMPT, ROUTINE_EXTRACT_PROMPT, ROUTINE_SHAPE, header
from app.llm.schemas import RoutineExtraction
from app.models import Course, Draft, RoutineSlot
from app.services.dates import parse_hhmm, utcnow, weekday_index
from app.utils.telegram import esc

DAY_ORDER = ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"]


def clean(extraction: RoutineExtraction) -> dict:
    """Drop slots with impossible times; return a JSON-able draft payload."""
    slots, notes = [], list(extraction.uncertain_notes)
    for sl in extraction.slots:
        try:
            start = parse_hhmm(sl.start_time)
            end = parse_hhmm(sl.end_time) if sl.end_time else None
        except (ValueError, TypeError):
            notes.append(f"skipped {sl.course_title} on {sl.weekday}: unreadable time")
            continue
        if end and end <= start:
            end = None
        d = sl.model_dump()
        d["start_time"], d["end_time"] = start.strftime("%H:%M"), end.strftime("%H:%M") if end else None
        slots.append(d)
    slots.sort(key=lambda x: (DAY_ORDER.index(x["weekday"]), x["start_time"]))
    return {"slots": slots, "uncertain_notes": notes}


async def extract(image: bytes | None, text: str) -> RoutineExtraction:
    prompt = ROUTINE_EXTRACT_PROMPT.format(header=header(), text=text or "", shape=ROUTINE_SHAPE)
    return await generate_json(prompt, RoutineExtraction, image=image, purpose="routine_extract")


async def edit(payload: dict, instruction: str) -> dict:
    draft_json = json.dumps({"is_routine": True, **payload}, ensure_ascii=False)
    prompt = ROUTINE_EDIT_PROMPT.format(header=header(), draft_json=draft_json, instruction=instruction)
    return clean(await generate_json(prompt, RoutineExtraction, purpose="routine_edit"))


def summary(class_name: str, payload: dict) -> str:
    lines = [f"📅 Here's what I read for <b>{esc(class_name)}</b>:"]
    for sl in payload["slots"]:
        end = f"–{sl['end_time']}" if sl["end_time"] else ""
        room = f" (Room {esc(sl['room'])})" if sl.get("room") else ""
        lab = " [lab]" if sl.get("slot_type") == "lab" else ""
        lines.append(f"<code>{sl['weekday']} {sl['start_time']}{end}</code> {esc(sl['course_title'])}{lab}{room}")
    for note in payload["uncertain_notes"]:
        lines.append(f"⚠️ Not sure: {esc(note)}")
    lines.append("\nIs this right? Tell me what to fix, or say <i>save</i> (or <i>discard</i>).")
    return "\n".join(lines)


async def new_draft(s: AsyncSession, classroom_id: int, user_id: int, chat_id: int, payload: dict) -> Draft:
    # One open routine draft per chat: a new upload replaces the old one.
    for old in await s.scalars(select(Draft).where(Draft.chat_id == chat_id, Draft.kind == "routine",
                                                   Draft.status == "open")):
        old.status = "discarded"
    d = Draft(kind="routine", classroom_id=classroom_id, created_by=user_id, chat_id=chat_id,
              payload=payload, expires_at=utcnow() + timedelta(hours=DRAFT_HOURS))
    s.add(d)
    await s.flush()
    return d


async def save(s: AsyncSession, classroom_id: int, payload: dict) -> int:
    """Replace the whole weekly routine with the draft. Creates missing courses."""
    courses = {c.title.lower(): c for c in await s.scalars(select(Course).where(Course.classroom_id == classroom_id))}
    await s.execute(delete(RoutineSlot).where(RoutineSlot.classroom_id == classroom_id))
    for sl in payload["slots"]:
        code = (sl.get("course_code") or "").lower()
        course = courses.get(sl["course_title"].lower()) or next(
            (c for c in courses.values() if code and (c.code or "").lower() == code), None)
        if course is None:
            course = Course(classroom_id=classroom_id, title=sl["course_title"], code=sl.get("course_code"))
            s.add(course)
            await s.flush()
            courses[course.title.lower()] = course
        s.add(RoutineSlot(classroom_id=classroom_id, course_id=course.id, weekday=weekday_index(sl["weekday"]),
                          start_time=parse_hhmm(sl["start_time"]),
                          end_time=parse_hhmm(sl["end_time"]) if sl["end_time"] else None,
                          room=sl.get("room"), slot_type=sl.get("slot_type") or "theory"))
    await s.flush()
    return len(payload["slots"])
