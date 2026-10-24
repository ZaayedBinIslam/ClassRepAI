from datetime import date, time
from types import SimpleNamespace as NS

from app.services.schedule import build_sessions, match_courses

SUN = date(2026, 10, 25)          # a Sunday
DBMS, LAB = 1, 2
TITLES = {DBMS: "DBMS", LAB: "DBMS Lab"}
SLOTS = [
    NS(course_id=DBMS, weekday=6, start_time=time(10), end_time=time(11, 20), room="305"),   # Sun
    NS(course_id=LAB, weekday=0, start_time=time(9), end_time=time(11, 30), room="Lab 2"),   # Mon
    NS(course_id=DBMS, weekday=1, start_time=time(11, 30), end_time=None, room="305"),       # Tue
]


def change(**kw):
    base = dict(course_id=DBMS, session_date=SUN, change_type="cancelled", new_start_time=None, new_room=None, note=None)
    return NS(**{**base, **kw})


def test_week_expands_routine():
    s = build_sessions(SLOTS, [], TITLES, SUN, 7)
    assert [(x.course, x.day.weekday()) for x in s] == [("DBMS", 6), ("DBMS Lab", 0), ("DBMS", 1)]


def test_cancellation_applies_only_to_that_date():
    s = build_sessions(SLOTS, [change()], TITLES, SUN, 7)
    assert s[0].status == "cancelled"
    assert s[2].status == "normal"


def test_reschedule_and_room_change():
    s = build_sessions(SLOTS, [change(change_type="rescheduled", new_start_time=time(14), new_room="402")],
                       TITLES, SUN, 1)
    assert (s[0].start, s[0].room, s[0].status) == (time(14), "402", "rescheduled")


def test_extra_class_added():
    s = build_sessions(SLOTS, [change(change_type="extra_class", session_date=date(2026, 10, 28),
                                      new_start_time=time(15))], TITLES, SUN, 7)
    assert any(x.status == "extra_class" and x.day == date(2026, 10, 28) for x in s)


def test_no_class_that_day():
    assert build_sessions(SLOTS, [], TITLES, date(2026, 10, 30), 1) == []   # Friday


def test_exact_course_match_beats_partial():
    courses = [NS(title="DBMS", code="CSE-3521"), NS(title="DBMS Lab", code="CSE-3522")]
    assert [c.title for c in match_courses(courses, "dbms")] == ["DBMS"]
    assert [c.title for c in match_courses(courses, "CSE-3522")] == ["DBMS Lab"]
    assert len(match_courses(courses, "DBM")) == 2
    assert match_courses(courses, "Networks") == []
