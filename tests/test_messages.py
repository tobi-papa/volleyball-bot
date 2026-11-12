from bot.messages import (
    PORTAL_URL,
    baseline_message,
    error_message,
    new_slots_message,
    no_change_message,
    recovered_message,
    slot_line,
    split_message,
)
from bot.slots import Slot

K = "港北スポーツセンター"


def s(date="2026-11-30", start="7:30", end="9:00", room="第一体育室Ｂ（半面）", gym=K):
    return Slot(date, start, gym, room, end)


def test_slot_line():
    assert slot_line(s()) == "Mon 30 Nov 2026 · 7:30–9:00 · Kohoku · Gym 1 B (half)"
    assert slot_line(s(room="第一体育室（全面）")).endswith("· Kohoku · Gym 1 (full)")
    assert "未知センター" in slot_line(s(gym="未知センター"))


def test_new_slots_message():
    three = [s(), s(start="9:00", end="11:00"), s(date="2026-12-01")]
    msg = new_slots_message(three)
    lines = msg.splitlines()
    assert lines[0] == "🏐 3 new slots at Kohoku"
    assert slot_line(three[0]) in msg
    assert PORTAL_URL in lines[-1]
    assert new_slots_message([s()]).splitlines()[0] == "🏐 1 new slot at Kohoku"


def test_new_slots_message_with_gone():
    msg = new_slots_message([s()], gone=[s(date="2026-12-07")])
    assert "Gone (1)" in msg
    assert "Mon 7 Dec 2026" in msg


def test_baseline():
    assert "No free slots right now." in baseline_message([])
    msg = baseline_message([s()])
    assert msg.startswith("🏐 Volleyball bot is running")
    assert slot_line(s()) in msg


def test_other_messages():
    assert "No change" in no_change_message([s()])
    assert error_message("PortalError: boom", "https://x/run/1").startswith("⚠️ Volleyball bot failed")
    assert "https://x/run/1" in error_message("boom", "https://x/run/1")
    assert recovered_message() == "✅ Volleyball bot is working again."


def test_split_message():
    text = "\n".join(f"line {i:03d} " + "x" * 20 for i in range(300))
    parts = split_message(text)
    assert len(parts) > 1
    assert all(len(p) <= 4096 for p in parts)
    assert "\n".join(parts) == text
    assert split_message("short") == ["short"]
