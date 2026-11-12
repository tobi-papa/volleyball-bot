from bot.config import Rule
from bot.slots import Slot, apply_rules, hhmm, matches, minutes

KOHOKU = "港北スポーツセンター"
B_HALF = "第一体育室Ｂ（半面）"
FULL = "第一体育室（全面）"


def slot(date="2026-11-30", start="7:30", end="9:00", room=B_HALF):
    return Slot(date, start, KOHOKU, room, end)


def test_hhmm():
    assert hhmm(730.0) == "7:30"
    assert hhmm(1300) == "13:00"
    assert hhmm(900.0) == "9:00"
    assert minutes("13:30") == 810


def test_key_and_dict_roundtrip():
    s = slot()
    assert s.key == (KOHOKU, B_HALF, "2026-11-30", "7:30", "9:00")
    assert Slot.from_dict(s.to_dict()) == s


def test_empty_rule_matches_everything():
    assert matches(slot(), Rule()) is True


def test_time_window():
    assert matches(slot(), Rule(time_from="19:00")) is False
    assert matches(slot(start="19:00", end="21:00"), Rule(time_from="19:00")) is True
    assert matches(slot(start="11:00", end="13:00"), Rule(time_to="13:00")) is True
    assert matches(slot(start="13:00", end="15:00"), Rule(time_to="13:00")) is False


def test_min_duration():
    assert matches(slot(), Rule(min_duration_minutes=120)) is False
    assert matches(slot(start="9:00", end="11:00"), Rule(min_duration_minutes=120)) is True


def test_weekdays_and_rooms():
    # 2026-11-30 is a Monday
    assert matches(slot(), Rule(weekdays=("Sat",))) is False
    assert matches(slot(), Rule(weekdays=("Mon",))) is True
    assert matches(slot(), Rule(rooms=(FULL,))) is False
    assert matches(slot(room=FULL), Rule(rooms=(FULL,))) is True


def test_apply_rules_union_dedup_sorted():
    late = slot(date="2026-12-01", start="9:00", end="11:00")
    early_day = slot(date="2026-11-30", start="13:00", end="15:00")
    first = slot()
    out = apply_rules([late, early_day, first, first], [Rule(), Rule(weekdays=("Mon",))])
    assert out == [first, early_day, late]


def test_sort_is_chronological_not_lexical():
    a = slot(start="7:30", end="9:00")
    b = slot(start="13:00", end="15:00")
    assert apply_rules([b, a], [Rule()]) == [a, b]
