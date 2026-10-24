"""Seeds the invented demo routine.

    python scripts/seed_demo.py               # creates a standalone demo class
    python scripts/seed_demo.py <chat_id>     # fills the routine of a group already set up with the bot
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Classroom, User  # noqa: E402
from app.services import routine  # noqa: E402
from demo_data import CLASS_NAME, ROUTINE  # noqa: E402

DEMO_CHAT_ID = -1000000000001     # fake group id for the standalone demo class


async def main():
    await init_db()
    chat_id = int(sys.argv[1]) if len(sys.argv) > 1 else DEMO_CHAT_ID
    async with SessionLocal() as s:
        c = await s.scalar(select(Classroom).where(Classroom.telegram_chat_id == chat_id))
        if c is None:
            if chat_id != DEMO_CHAT_ID:
                sys.exit("No class for that chat id. Set the group up with the bot first.")
            admin = User(telegram_user_id=1, username="demo_admin", full_name="Demo Admin")
            s.add(admin)
            await s.flush()
            c = Classroom(telegram_chat_id=chat_id, name=CLASS_NAME, admin_user_id=admin.id)
            s.add(c)
            await s.flush()
        payload = {"uncertain_notes": [], "slots": [
            {"weekday": wd, "start_time": st, "end_time": en, "course_title": title, "course_code": code,
             "room": room, "slot_type": kind} for wd, st, en, title, code, room, kind in ROUTINE]}
        n = await routine.save(s, c.id, payload)
        await s.commit()
    print(f"Seeded {n} routine slots for {c.name}")


if __name__ == "__main__":
    asyncio.run(main())
