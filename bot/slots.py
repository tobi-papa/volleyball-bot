"""Free slot model and config rule filtering."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date as Date
from typing import Iterable, List, Sequence, Tuple, Union

from bot.config import WEEKDAYS, Rule


def minutes(hhmm_text: str) -> int:
    """'13:30' -> 810"""
    h, m = hhmm_text.split(":")
    return int(h) * 60 + int(m)


def hhmm(value: Union[float, int]) -> str:
    """Portal times: 730.0 -> '7:30', 1300 -> '13:00'"""
    v = int(value)
    return f"{v // 100}:{v % 100:02d}"


@dataclass(frozen=True)
class Slot:
    date: str   # ISO, e.g. 2026-11-30
    start: str  # e.g. 7:30
    gym: str    # Japanese name as on the portal
    room: str
    end: str

    @property
    def key(self) -> Tuple[str, str, str, str, str]:
        return (self.gym, self.room, self.date, self.start, self.end)

    @property
    def sort_key(self):
        return (self.date, minutes(self.start), self.gym, self.room, minutes(self.end))

    @property
    def weekday(self) -> str:
        return WEEKDAYS[Date.fromisoformat(self.date).weekday()]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Slot":
        return cls(d["date"], d["start"], d["gym"], d["room"], d["end"])


def sort_slots(slots: Iterable[Slot]) -> List[Slot]:
    """Chronological, de-duplicated."""
    return sorted(set(slots), key=lambda s: s.sort_key)


def matches(slot: Slot, rule: Rule) -> bool:
    if rule.rooms and slot.room not in rule.rooms:
        return False
    if rule.time_from and minutes(slot.start) < minutes(rule.time_from):
        return False
    if rule.time_to and minutes(slot.end) > minutes(rule.time_to):
        return False
    if minutes(slot.end) - minutes(slot.start) < rule.min_duration_minutes:
        return False
    if rule.weekdays and slot.weekday not in rule.weekdays:
        return False
    return True


def apply_rules(slots: Iterable[Slot], rules: Sequence[Rule]) -> List[Slot]:
    return sort_slots(s for s in slots if any(matches(s, r) for r in rules))
