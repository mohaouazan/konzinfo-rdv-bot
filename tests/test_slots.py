from datetime import date, datetime, time

from konzinfo.config import SlotsConfig
from konzinfo.slots import Slot, choose_first, day_allowed, filter_slots, parse_time, slot_from_label, summarize


def test_parse_time_variants():
    assert parse_time("08:30") == time(8, 30)
    assert parse_time("08:30 - 08:45") == time(8, 30)
    assert parse_time("from 9:05") == time(9, 5)
    assert parse_time("14.15") == time(14, 15)
    assert parse_time("libre") is None
    assert parse_time("25:00") is None


def test_slot_from_label_and_ordering():
    d = date(2026, 12, 1)
    a = slot_from_label(d, "10:00")
    b = slot_from_label(d, "08:30 - 08:45")
    assert a and b and b < a
    assert str(b).endswith("08:30")


def test_filter_by_dates_weekdays_hours():
    now = datetime(2026, 11, 13, 9, 0)
    slots = [
        Slot(datetime(2026, 11, 13, 8, 0)),   # passe (avant now)
        Slot(datetime(2026, 11, 16, 9, 0)),   # lundi
        Slot(datetime(2026, 11, 18, 13, 0)),  # mercredi, apres-midi
        Slot(datetime(2026, 11, 21, 10, 0)),  # samedi
        Slot(datetime(2026, 12, 5, 10, 0)),
    ]
    assert [s.start.day for s in filter_slots(slots, SlotsConfig(), now)] == [16, 18, 21, 5]
    cfg = SlotsConfig(weekdays=[0, 1, 2], hours=("08:00", "12:00"))
    assert [s.start.day for s in filter_slots(slots, cfg, now)] == [16]
    cfg = SlotsConfig(earliest=date(2026, 11, 20), latest=date(2026, 11, 30))
    assert [s.start.day for s in filter_slots(slots, cfg, now)] == [21]
    assert choose_first(slots, SlotsConfig(), now).start == datetime(2026, 11, 16, 9, 0)
    assert choose_first(slots, SlotsConfig(latest=date(2026, 11, 1)), now) is None


def test_day_allowed():
    today = date(2026, 11, 13)
    assert day_allowed(date(2026, 11, 13), SlotsConfig(), today)
    assert not day_allowed(date(2026, 11, 12), SlotsConfig(), today)
    assert not day_allowed(date(2026, 11, 15), SlotsConfig(weekdays=[0]), today)  # dimanche


def test_summarize_groups_by_day():
    slots = [Slot(datetime(2026, 12, 1, 9, 0)), Slot(datetime(2026, 12, 1, 9, 15)), Slot(datetime(2026, 12, 2, 8, 0))]
    text = summarize(slots)
    assert "01/12/2026 : 09:00, 09:15" in text
    assert "02/12/2026 : 08:00" in text
    assert summarize([]) == "aucun"
