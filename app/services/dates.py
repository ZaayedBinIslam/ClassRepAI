"""Time helpers. The DB stores naive UTC datetimes; everything shown to users is Dhaka time."""
from datetime import UTC, date, datetime, time

from app.config import TZ

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]   # index = Python weekday()


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def now_local() -> datetime:
    return datetime.now(TZ)


def to_local(dt_utc: datetime) -> datetime:
    return dt_utc.replace(tzinfo=UTC).astimezone(TZ)


def local_to_utc(d: date, t: time) -> datetime:
    """A Dhaka date + time -> naive UTC datetime."""
    return datetime.combine(d, t, tzinfo=TZ).astimezone(UTC).replace(tzinfo=None)


def weekday_index(code: str) -> int:
    """'Sun' -> 6."""
    return WEEKDAYS.index(code[:3].title())


def parse_hhmm(s: str) -> time:
    """'9:05' / '09:05' -> time. Raises ValueError on nonsense like '25:00'."""
    h, m = s.strip().split(":")[:2]
    return time(int(h), int(m))


def fmt_date(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d.day} {d.strftime('%b')}"      # "Sun 26 Oct"


def fmt_time(t: time | None) -> str:
    return t.strftime("%H:%M") if t else "?"


def fmt_clock(dt_utc: datetime) -> str:
    return to_local(dt_utc).strftime("%I:%M %p").lstrip("0")         # "2:45 PM"
