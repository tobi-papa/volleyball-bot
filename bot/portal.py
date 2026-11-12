"""Read free slots from the Yokohama facility portal over plain HTTP (no login, no browser).

Flow (see docs/design.md, "Come funziona il sito"):
Home -> Home/SearchByPurpose -> SelectFacility(/Next) -> SelectDays (month JSON)
-> SelectDays/Next in batches of <= 20 day-cells -> SelectTime (slot JSON in the HTML).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set, Tuple

import requests
from bs4 import BeautifulSoup

from bot.slots import Slot, hhmm, sort_slots

BASE = "https://www.shisetsu.city.yokohama.lg.jp/user/"
JST = timezone(timedelta(hours=9))
BATCH_SIZE = 20          # the portal accepts at most 20 ticked day-cells per request
TIMEOUT = 30
USER_AGENT = "volleyball-availability-bot/1.0 (+https://github.com/jeremynata/volleyball-bot)"
DEBUG_DIR = Path("debug")

Fields = List[Tuple[str, str]]
Cell = Tuple[int, int]   # (row index, cell index) in the month table


class PortalError(Exception):
    """The portal answered something we cannot use."""


class SiteClosed(Exception):
    """The portal is in maintenance."""


@dataclass
class MonthFacility:
    index: int   # position in Horizontal[]
    code: int
    name: str
    rows: list   # raw Rows[] from the month JSON


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def today_jst(now: Optional[datetime] = None) -> date:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(JST).date()


def parse_token(html: str) -> str:
    tag = BeautifulSoup(html, "html.parser").select_one("input[name=__RequestVerificationToken]")
    if not tag or not tag.get("value"):
        raise PortalError("no __RequestVerificationToken in page")
    return tag["value"]


def facility_fields(html: str, gyms: Sequence[str]) -> Fields:
    soup = BeautifulSoup(html, "html.parser")
    wanted = {g.strip() for g in gyms}
    found = set()
    fields: Fields = []
    for text in soup.select("input[name$='.SelectedFacility.Text']"):
        prefix = text["name"][: -len(".SelectedFacility.Text")]
        value = soup.select_one(f"input[name='{prefix}.SelectedFacility.Value']")
        name = text.get("value", "").strip()
        if name in wanted:
            found.add(name)
            fields.append((f"{prefix}.IsChecked", "true"))
        fields += [
            (f"{prefix}.IsChecked", "false"),
            (f"{prefix}.SelectedFacility.Value", value["value"] if value else ""),
            (f"{prefix}.SelectedFacility.Text", name),
        ]
    missing = wanted - found
    if missing:
        raise PortalError(f"gym(s) not found on the portal: {sorted(missing)}")
    return fields


def search_condition_fields(start: date) -> Fields:
    f: Fields = [
        ("SearchCondition.StartDate", start.isoformat()),
        ("SearchCondition.DisplayTerm", "4"),       # 1 month
        ("SearchCondition.DisplayCalendar", "0"),
        ("SearchCondition.TimeZone", "0"),
    ]
    f += [(f"SearchCondition.DisplayTermList[{i}].Value", str(v)) for i, v in enumerate([1, 2, 3, 4])]
    f += [(f"SearchCondition.DisplayCalendarList[{i}].Value", str(v)) for i, v in enumerate([0, 1])]
    f += [(f"SearchCondition.TimeZoneList[{i}].Value", str(v)) for i, v in enumerate([1, 2, 3, 0])]
    f += [(f"SearchCondition.WeekList[{i}].Value", str(v)) for i, v in enumerate(range(1, 9))]
    return f


def _check_result(obj, where: str) -> None:
    if isinstance(obj, dict) and obj.get("Result") not in (None, "Ok"):
        info = obj.get("Information")
        if isinstance(info, dict):
            info = info.get("MessageId")
        raise PortalError(f"{where}: portal error {info}")


def parse_month(payload) -> List[MonthFacility]:
    if not isinstance(payload, list) or not payload:
        raise PortalError("month: unexpected payload")
    _check_result(payload[0], "month")
    try:
        horizontal = payload[1]["Horizontal"]
    except (IndexError, KeyError, TypeError):
        raise PortalError("month: no Horizontal table")
    facs = []
    for i, h in enumerate(horizontal):
        common = h["Common"]
        rows = common.get("Rows") or []
        if not rows or not any(r.get("Cells") for r in rows):
            raise PortalError(f"month: no rows/cells for {common.get('FacilityName')}")
        facs.append(MonthFacility(i, int(common["FacilityCode"]), common["FacilityName"], rows))
    if not facs:
        raise PortalError("month: no facilities")
    return facs


def candidate_cells(fac: MonthFacility) -> List[Cell]:
    return [
        (ri, ci)
        for ri, row in enumerate(fac.rows)
        for ci, cell in enumerate(row["Cells"])
        if cell.get("DisplayStatusForUser") in ("some", "vacant") and cell.get("IsEnabledForUser")
    ]


def batches(cells: List[Cell], size: int = BATCH_SIZE) -> List[List[Cell]]:
    return [cells[i:i + size] for i in range(0, len(cells), size)]


def _facility_body(fac: MonthFacility, picked: Set[Cell]) -> Fields:
    p = f"Horizontal[{fac.index}].Common"
    f: Fields = []
    for ri, row in enumerate(fac.rows):
        for ci, cell in enumerate(row["Cells"]):
            f.append((f"{p}.Rows[{ri}].Cells[{ci}].IsChecked", "true" if (ri, ci) in picked else "false"))
            f.append((f"{p}.Rows[{ri}].Cells[{ci}].UseDate", cell["UseDate"]))
    for ri, row in enumerate(fac.rows):
        f.append((f"{p}.Rows[{ri}].Code", str(row["Code"])))
        f.append((f"{p}.Rows[{ri}].IsDisplayGroup", "true" if row.get("IsDisplayGroup") else "false"))
    f.append((f"{p}.FacilityCode", str(fac.code)))
    return f


def days_next_fields(start: date, fac: MonthFacility, picked: Set[Cell],
                     others: Iterable[MonthFacility] = ()) -> Fields:
    """Body for SelectDays/Next: every cell of every facility, only `picked` ticked (in `fac`)."""
    f = search_condition_fields(start)
    for other in sorted([fac, *others], key=lambda x: x.index):
        f += _facility_body(other, picked if other is fac else set())
    f.append(("token", "null"))
    return f


_TIME_JSON = re.compile(r'JSON\.parse\("(\{\\u0022AvailabilityTime.*?)"\)', re.S)


def parse_time_page(html: str) -> List[Slot]:
    m = _TIME_JSON.search(html)
    if not m:
        raise PortalError("time page: availability data not found")
    data = json.loads(json.loads('"' + m.group(1) + '"'))
    slots = []
    for fac in data["AvailabilityTime"]["FacilityList"]:
        gym = fac["Common"]["Name"]
        for day in fac["Days"]:
            for row in day["DisplayRows"]:
                for c in row["DisplayCells"]:
                    if c.get("IsEnabledForUser"):
                        slots.append(Slot(day["UseDate"][:10], hhmm(c["TimeFrom"]), gym,
                                          row["ObjectName"], hhmm(c["TimeTo"])))
    return sort_slots(slots)


# ---------------------------------------------------------------------------
# HTTP flow
# ---------------------------------------------------------------------------
class _Client:
    def __init__(self, session):
        self.s = session
        self.last = ""

    def get(self, path: str) -> str:
        r = self.s.get(BASE + path, timeout=TIMEOUT)
        self.last = f"GET {path} -> {r.status_code}\n{r.text}"
        r.raise_for_status()
        return r.text

    def post(self, path: str, fields: Fields, token: str):
        files = [(k, (None, v)) for k, v in fields] + [("__RequestVerificationToken", (None, token))]
        r = self.s.post(BASE + path, files=files, timeout=TIMEOUT,
                        headers={"X-Requested-With": "XMLHttpRequest", "RequestVerificationToken": token})
        self.last = f"POST {path} -> {r.status_code}\n{r.text}"
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError:
            raise PortalError(f"{path}: response is not JSON")
        if isinstance(data, str):   # some endpoints return JSON encoded twice
            data = json.loads(data)
        _check_result(data, path)
        return data


def _dump(text: str) -> None:
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        (DEBUG_DIR / "last_response.txt").write_text(text, encoding="utf-8")
    except OSError:
        pass


def fetch_slots(purpose: int, gyms: Sequence[str], *, session=None,
                now: Optional[datetime] = None) -> List[Slot]:
    if session is None:
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT
    c = _Client(session)
    try:
        return _flow(c, purpose, gyms, today_jst(now))
    except (PortalError, SiteClosed):
        _dump(c.last)
        raise
    except Exception as e:
        _dump(c.last)
        raise PortalError(f"{type(e).__name__}: {e}") from e


def _flow(c: _Client, purpose: int, gyms: Sequence[str], start: date) -> List[Slot]:
    token = parse_token(c.get("Home"))
    if c.post("api/Header/GetSiteClosing", [], token).get("isClosing"):
        raise SiteClosed()
    c.post("Home/SearchByPurpose", [
        ("HomeModel.SearchByDateTimeModel.SelectedPurposeCategory", "1"),
        ("HomeModel.DateFrom", ""), ("HomeModel.DateTo", ""),
        ("HomeModel.SelectedSearchTarget", "0"),
        ("HomeModel.SearchByDateTimeModel.SelectedPlaceClassCategory", "1"),
        ("HomeModel.SelectedPurposeCategory", "1"),
        ("HomeModel.SelectedPurpose", str(purpose)),
        ("HomeModel.SelectedPlaceClassCategory", "1"),
        ("SelectedLanguageCode", "0"),
    ], token)

    fac_html = c.get("AvailabilityCheckApplySelectFacility")
    c.post("AvailabilityCheckApplySelectFacility/Next", facility_fields(fac_html, gyms), parse_token(fac_html))

    token = parse_token(c.get("AvailabilityCheckApplySelectDays"))
    c.post("AvailabilityCheckApplySelectDays/GetAvailability", [], token)
    facs = parse_month(c.post("AvailabilityCheckApplySelectDays/SearchCondition",
                              search_condition_fields(start), token))

    slots: List[Slot] = []
    for fac in facs:
        others = [f for f in facs if f is not fac]
        for lot in batches(candidate_cells(fac)):
            c.post("AvailabilityCheckApplySelectDays/Next",
                   days_next_fields(start, fac, set(lot), others), token)
            slots += parse_time_page(c.get("AvailabilityCheckApplySelectTime"))
            token = parse_token(c.get("AvailabilityCheckApplySelectDays"))
    return sort_slots(slots)
