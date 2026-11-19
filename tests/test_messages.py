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


# --- /list ------------------------------------------------------------------

from datetime import datetime, timezone

from bot.messages import list_error_message, list_message, maintenance_message

LA = Slot("2026-11-30", "7:30", K, "第一体育室Ａ（半面）", "9:00")
LB = Slot("2026-11-30", "13:00", K, "第一体育室Ｂ（半面）", "15:00")
LC = Slot("2026-12-01", "7:30", K, "第一体育室（全面）", "9:00")
CHECKED = datetime(2026, 11, 19, 5, 5, tzinfo=timezone.utc)


def test_list_message_groups_by_day():
    msg = list_message([LC, LB, LA], {LC.key}, [], CHECKED, (K,))
    lines = msg.splitlines()
    assert lines[0] == "📋 Free now at Kohoku (3) · checked 14:05 JST"
    i = lines.index("Mon 30 Nov 2026")
    assert lines[i + 1] == "  7:30–9:00 · Gym 1 A (half)"
    assert lines[i + 2] == "  13:00–15:00 · Gym 1 B (half)"
    j = lines.index("Tue 1 Dec 2026")
    assert lines[j + 1] == "  🆕 7:30–9:00 · Gym 1 (full)"
    assert "Taken since" not in msg
    assert PORTAL_URL in lines[-1]


def test_list_message_taken_section():
    msg = list_message([LA], set(), [LB], CHECKED, (K,))
    assert "Taken since the last /list (1):" in msg
    assert "  Mon 30 Nov 2026 · 13:00–15:00 · Kohoku · Gym 1 B (half)" in msg.splitlines()


def test_list_message_empty():
    msg = list_message([], set(), [], CHECKED, (K,))
    assert msg.splitlines()[0] == "📋 Free now at Kohoku (0) · checked 14:05 JST"
    assert "No free slots right now." in msg


def test_list_message_multi_gym_shows_gym():
    other = Slot("2026-11-30", "9:00", "緑スポーツセンター", "第一体育室（全面）", "11:00")
    msg = list_message([LA, other], set(), [], CHECKED, (K, "緑スポーツセンター"))
    assert msg.splitlines()[0].startswith("📋 Free now at Kohoku, Midori (2)")
    assert "  7:30–9:00 · Kohoku · Gym 1 A (half)" in msg.splitlines()
    assert "  9:00–11:00 · Midori · Gym 1 (full)" in msg.splitlines()


def test_list_error_and_maintenance():
    assert list_error_message("PortalError: boom") == "⚠️ Could not read the portal: PortalError: boom"
    assert maintenance_message() == "🔧 The portal is in maintenance, try again later."


def test_split_message_counts_utf16_units():
    # Telegram counts UTF-16 code units; 🆕 is 2 units but 1 Python character
    text = "\n".join("  🆕 13:00–15:00 · Gym 1 B (half) " + "x" * 10 for _ in range(200))
    for part in split_message(text):
        assert len(part.encode("utf-16-le")) // 2 <= 4096
