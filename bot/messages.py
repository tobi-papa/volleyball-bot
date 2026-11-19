"""Telegram message texts (English, so they can be forwarded to the group)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from itertools import groupby
from typing import Collection, Iterable, List, Optional, Sequence

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

JST = timezone(timedelta(hours=9))

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


def _units(s: str) -> int:
    """Length as Telegram counts it: UTF-16 code units (an emoji like 🆕 counts 2)."""
    return len(s.encode("utf-16-le")) // 2


def split_message(text: str, limit: int = LIMIT) -> List[str]:
    parts: List[str] = []
    current = ""
    for line in text.split("\n"):
        while _units(line) > limit:          # a single absurdly long line
            if current:
                parts.append(current)
                current = ""
            cut = limit
            while _units(line[:cut]) > limit:
                cut -= 1
            parts.append(line[:cut])
            line = line[cut:]
        candidate = line if not current else current + "\n" + line
        if _units(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    parts.append(current)
    return parts


def list_message(slots: Sequence[Slot], new_keys: Collection[tuple], taken: Sequence[Slot],
                 checked_at: datetime, gyms: Sequence[str]) -> str:
    """Full availability for /list, grouped by day. 🆕 and 'Taken' are relative to the previous /list."""
    hour = checked_at.astimezone(JST)
    out = [f"📋 Free now at {', '.join(gym_en(g) for g in gyms)} ({len(slots)}) · checked {hour.hour}:{hour.minute:02d} JST"]
    show_gym = len(gyms) > 1
    if not slots:
        out += ["", "No free slots right now."]
    for day, group in groupby(sort_slots(slots), key=lambda s: s.date):
        out += ["", date_en(day)]
        for s in group:
            mark = "🆕 " if s.key in new_keys else ""
            where = f"{gym_en(s.gym)} · {room_en(s.room)}" if show_gym else room_en(s.room)
            out.append(f"  {mark}{s.start}–{s.end} · {where}")
    if taken:
        out += ["", f"Taken since the last /list ({len(taken)}):"] + [f"  {line}" for line in _lines(taken)]
    return "\n".join(out + ["", f"Book: {PORTAL_URL}"])


def list_error_message(err: str) -> str:
    return f"⚠️ Could not read the portal: {err}"


def maintenance_message() -> str:
    return "🔧 The portal is in maintenance, try again later."
