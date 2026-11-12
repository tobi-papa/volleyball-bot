"""Telegram message texts (English, so they can be forwarded to the group)."""
from __future__ import annotations

from datetime import date
from typing import Iterable, List, Optional, Sequence

from bot.slots import Slot, sort_slots

PORTAL_URL = "https://www.shisetsu.city.yokohama.lg.jp/user/Home"
LIMIT = 4096

GYMS = {
    "神奈川スポーツセンター": "Kanagawa",
    "南スポーツセンター": "Minami",
    "旭スポーツセンター": "Asahi",
    "港北スポーツセンター": "Kohoku",
    "緑スポーツセンター": "Midori",
    "戸塚スポーツセンター": "Totsuka",
}

# applied in order to the room name
ROOMS = [
    ("第一体育室", "Gym 1"),
    ("第二体育室", "Gym 2"),
    ("体育室", "Gym"),
    ("（全面）", " (full)"),
    ("（半面）", " (half)"),
    ("Ａ", " A"),
    ("Ｂ", " B"),
    ("Ｃ", " C"),
]

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def gym_en(name: str) -> str:
    return GYMS.get(name, name)


def room_en(name: str) -> str:
    for jp, en in ROOMS:
        name = name.replace(jp, en)
    return " ".join(name.split())


def date_en(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{_DAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]} {d.year}"


def slot_line(s: Slot) -> str:
    return f"{date_en(s.date)} · {s.start}–{s.end} · {gym_en(s.gym)} · {room_en(s.room)}"


def _gyms(slots: Iterable[Slot]) -> str:
    return ", ".join(dict.fromkeys(gym_en(s.gym) for s in slots))


def _lines(slots: Iterable[Slot]) -> List[str]:
    return [slot_line(s) for s in sort_slots(slots)]


def new_slots_message(new: Sequence[Slot], gone: Sequence[Slot] = ()) -> str:
    n = len(new)
    if n:
        out = [f"🏐 {n} new slot{'s' if n != 1 else ''} at {_gyms(new)}", ""] + _lines(new)
    else:
        out = [f"🏐 Slots taken at {_gyms(gone)}"]
    if gone:
        out += ["", f"Gone ({len(gone)})"] + _lines(gone)
    return "\n".join(out + ["", f"Book: {PORTAL_URL}"])


def baseline_message(slots: Sequence[Slot]) -> str:
    out = ["🏐 Volleyball bot is running. I'll message you when a new slot appears.", ""]
    out += [f"Currently free ({len(slots)}):"] + _lines(slots) if slots else ["No free slots right now."]
    return "\n".join(out + ["", f"Book: {PORTAL_URL}"])


def no_change_message(slots: Sequence[Slot]) -> str:
    return "\n".join([f"🏐 No change. Free now ({len(slots)}):"] + _lines(slots) + ["", f"Book: {PORTAL_URL}"])


def error_message(err: str, run_url: Optional[str] = None) -> str:
    out = ["⚠️ Volleyball bot failed:", err]
    if run_url:
        out += ["", run_url]
    return "\n".join(out)


def recovered_message() -> str:
    return "✅ Volleyball bot is working again."


def split_message(text: str, limit: int = LIMIT) -> List[str]:
    parts: List[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:          # a single absurdly long line
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = line if not current else current + "\n" + line
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    parts.append(current)
    return parts
