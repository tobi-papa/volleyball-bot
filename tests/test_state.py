from datetime import datetime, timedelta, timezone

from bot.slots import Slot
from bot.state import State, diff, load_state, save_state, should_alert

K = "港北スポーツセンター"
A = Slot("2026-11-30", "7:30", K, "第一体育室Ａ（半面）", "9:00")
B = Slot("2026-11-30", "13:00", K, "第一体育室Ｂ（半面）", "15:00")
C = Slot("2026-12-01", "7:30", K, "第一体育室（全面）", "9:00")
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)


def test_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    save_state(State(slots=[A, B], failing=True, last_error_alert=NOW), p)
    s = load_state(p)
    assert s.slots == [A, B]
    assert s.failing is True
    assert s.last_error_alert == NOW


def test_missing_file(tmp_path):
    assert load_state(tmp_path / "nope.json") == State()


def test_corrupt_file(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_state(p) == State()


def test_wrong_shape_file(tmp_path):
    p = tmp_path / "state.json"
    p.write_text('{"slots": [{"date": 1}]}', encoding="utf-8")
    assert load_state(p) == State()


def test_empty_slot_list_is_not_baseline(tmp_path):
    p = tmp_path / "state.json"
    save_state(State(slots=[]), p)
    assert load_state(p).slots == []


def test_diff():
    assert diff([A, B], [B, C]) == ([C], [A])
    assert diff([], []) == ([], [])


def test_should_alert():
    assert should_alert(State(), NOW, 6) is True
    assert should_alert(State(last_error_alert=NOW - timedelta(hours=5)), NOW, 6) is False
    assert should_alert(State(last_error_alert=NOW - timedelta(hours=6)), NOW, 6) is True
