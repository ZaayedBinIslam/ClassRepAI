from datetime import date, datetime, time

import pytest

from app.services.dates import fmt_date, local_to_utc, parse_hhmm, weekday_index


def test_weekday_codes():
    assert weekday_index("Sun") == 6
    assert weekday_index("sat") == 5
    assert weekday_index("Monday") == 0


def test_parse_hhmm():
    assert parse_hhmm("9:05") == time(9, 5)
    assert parse_hhmm(" 13:20 ") == time(13, 20)
    with pytest.raises(ValueError):
        parse_hhmm("25:00")
    with pytest.raises(ValueError):
        parse_hhmm("ten")


def test_dhaka_is_utc_plus_6():
    assert local_to_utc(date(2026, 10, 26), time(10, 0)) == datetime(2026, 10, 26, 4, 0)


def test_fmt_date():
    assert fmt_date(date(2026, 10, 25)) == "Sun 25 Oct"
