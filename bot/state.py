"""What the bot saw last time (kept between runs by actions/cache)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

from bot.slots import Slot, sort_slots


@dataclass
class State:
    slots: Optional[List[Slot]] = None      # None = never saw anything -> send a baseline
    failing: bool = False
    last_error_alert: Optional[datetime] = None


def load_state(path: Union[str, Path]) -> State:
    p = Path(path)
    if not p.exists():
        return State()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        slots = raw.get("slots")
        alert = raw.get("last_error_alert")
        return State(
            slots=None if slots is None else [Slot.from_dict(d) for d in slots],
            failing=bool(raw.get("failing", False)),
            last_error_alert=datetime.fromisoformat(alert) if alert else None,
        )
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"warning: ignoring unreadable state file {p}: {e}", file=sys.stderr)
        return State()


def save_state(state: State, path: Union[str, Path]) -> None:
    p = Path(path)
    data = {
        "slots": None if state.slots is None else [s.to_dict() for s in state.slots],
        "failing": state.failing,
        "last_error_alert": state.last_error_alert.isoformat() if state.last_error_alert else None,
    }
    fd, tmp = tempfile.mkstemp(dir=p.parent if str(p.parent) else ".", prefix=".state-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def diff(old: Sequence[Slot], new: Sequence[Slot]) -> Tuple[List[Slot], List[Slot]]:
    old_keys = {s.key for s in old}
    new_keys = {s.key for s in new}
    appeared = sort_slots(s for s in new if s.key not in old_keys)
    gone = sort_slots(s for s in old if s.key not in new_keys)
    return appeared, gone


def should_alert(state: State, now: datetime, every_hours: int) -> bool:
    if state.last_error_alert is None:
        return True
    return now - state.last_error_alert >= timedelta(hours=every_hours)
