"""Load and validate config.yaml."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Union

import yaml

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_TIME = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


@dataclass(frozen=True)
class Rule:
    rooms: Tuple[str, ...] = ()
    time_from: Optional[str] = None
    time_to: Optional[str] = None
    min_duration_minutes: int = 0
    weekdays: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Config:
    purpose: int
    gyms: Tuple[str, ...]
    rules: Tuple[Rule, ...]
    notify_gone: bool
    notify_no_change: bool
    error_alert_every_hours: int


def _time(value, field: str) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 24 * 60:
        # YAML 1.1 reads an unquoted 13:00 as 780 (minutes): turn it back into a time
        value = f"{value // 60}:{value % 60:02d}"
    value = str(value).strip()
    if not _TIME.match(value):
        raise ValueError(f"config: {field} must look like 7:30 or 19:00, got {value!r}")
    return value


def _rule(raw, i: int) -> Rule:
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config: rules[{i}] must be a mapping")
    unknown = set(raw) - {"rooms", "time_from", "time_to", "min_duration_minutes", "weekdays"}
    if unknown:
        raise ValueError(f"config: rules[{i}] has unknown keys {sorted(unknown)}")
    weekdays = tuple(str(d).strip() for d in (raw.get("weekdays") or ()))
    bad = [d for d in weekdays if d not in WEEKDAYS]
    if bad:
        raise ValueError(f"config: rules[{i}].weekdays must be among {WEEKDAYS}, got {bad}")
    return Rule(
        rooms=tuple(str(r).strip() for r in (raw.get("rooms") or ())),
        time_from=_time(raw.get("time_from"), f"rules[{i}].time_from"),
        time_to=_time(raw.get("time_to"), f"rules[{i}].time_to"),
        min_duration_minutes=int(raw.get("min_duration_minutes") or 0),
        weekdays=weekdays,
    )


def load_config(path: Union[str, Path]) -> Config:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    gyms = tuple(str(g).strip() for g in (data.get("gyms") or ()))
    if not gyms:
        raise ValueError("config: gyms must list at least one gym")
    rules = data.get("rules")
    if not rules:
        raise ValueError("config: rules must contain at least one rule (use '- {}' for everything)")
    return Config(
        purpose=int(data.get("purpose", 5)),
        gyms=gyms,
        rules=tuple(_rule(r, i) for i, r in enumerate(rules)),
        notify_gone=bool(data.get("notify_gone", False)),
        notify_no_change=bool(data.get("notify_no_change", False)),
        error_alert_every_hours=int(data.get("error_alert_every_hours", 6)),
    )
