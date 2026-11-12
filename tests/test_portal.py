import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from bot import portal
from bot.portal import (
    PortalError,
    SiteClosed,
    batches,
    candidate_cells,
    days_next_fields,
    facility_fields,
    fetch_slots,
    parse_month,
    parse_time_page,
    parse_token,
    search_condition_fields,
    today_jst,
)
from bot.slots import Slot

FIX = Path(__file__).parent / "fixtures"
KOHOKU = "港北スポーツセンター"


def fixture(name):
    return (FIX / name).read_text(encoding="utf-8")


def month():
    return json.loads(fixture("month.json"))


def test_parse_token_days_page():
    assert parse_token(fixture("days_page.html"))


def test_parse_token_missing():
    with pytest.raises(PortalError):
        parse_token("<html></html>")


def test_facility_fields_kohoku():
    f = facility_fields(fixture("facility_page.html"), [KOHOKU])
    i = f.index(("SelectFacilities.Facilities[10].IsChecked", "true"))
    assert f[i + 1] == ("SelectFacilities.Facilities[10].IsChecked", "false")
    assert ("SelectFacilities.Facilities[10].SelectedFacility.Value", "11") in f
    assert ("SelectFacilities.Facilities[10].SelectedFacility.Text", KOHOKU) in f
    assert [k for k, v in f if v == "true"] == ["SelectFacilities.Facilities[10].IsChecked"]


def test_facility_fields_unknown_gym():
    with pytest.raises(PortalError):
        facility_fields(fixture("facility_page.html"), ["Nonexistent"])


def test_month_candidates():
    facs = parse_month(month())
    assert len(facs) == 1
    f = facs[0]
    assert (f.index, f.code, f.name) == (0, 11, KOHOKU)
    assert len(f.rows) == 3
    assert len(candidate_cells(f)) == 25


def test_month_error_result():
    with pytest.raises(PortalError, match="E-203-000014"):
        parse_month([{"Result": "Error", "Information": "E-203-000014"}])


def test_month_without_rows_is_error():
    payload = month()
    payload[1]["Horizontal"][0]["Common"]["Rows"] = []
    with pytest.raises(PortalError):
        parse_month(payload)


def test_month_all_full_is_valid():
    payload = month()
    for row in payload[1]["Horizontal"][0]["Common"]["Rows"]:
        for c in row["Cells"]:
            c["DisplayStatusForUser"] = "full"
    assert candidate_cells(parse_month(payload)[0]) == []


def test_batches():
    cells = [(0, i) for i in range(21)]
    assert batches([]) == []
    assert [len(b) for b in batches(cells[:20])] == [20]
    assert [len(b) for b in batches(cells)] == [20, 1]


def test_days_next_fields():
    f = parse_month(month())[0]
    fields = days_next_fields(date(2026, 11, 12), f, {(0, 5)})
    checked = [(k, v) for k, v in fields if k.endswith(".IsChecked")]
    assert len(checked) == 90
    assert [k for k, v in checked if v == "true"] == ["Horizontal[0].Common.Rows[0].Cells[5].IsChecked"]
    assert ("Horizontal[0].Common.Rows[0].Cells[5].UseDate", "2026-11-17T00:00:00") in fields
    assert ("Horizontal[0].Common.Rows[1].Code", "2") in fields
    assert ("Horizontal[0].Common.Rows[1].IsDisplayGroup", "true") in fields
    assert ("Horizontal[0].Common.FacilityCode", "11") in fields
    assert ("token", "null") in fields
    assert ("SearchCondition.DisplayTerm", "4") in fields


def test_search_condition_fields():
    f = search_condition_fields(date(2026, 11, 12))
    assert ("SearchCondition.DisplayTerm", "4") in f
    assert ("SearchCondition.StartDate", "2026-11-12") in f
    assert ("SearchCondition.WeekList[7].Value", "8") in f
    assert ("SearchCondition.TimeZoneList[3].Value", "0") in f


def test_parse_time_page():
    slots = parse_time_page(fixture("time_page.html"))
    assert len(slots) == 7
    assert slots[0] == Slot("2026-11-30", "7:30", KOHOKU, "第一体育室Ｂ（半面）", "9:00")
    assert Slot("2026-12-09", "13:00", KOHOKU, "第一体育室Ｂ（半面）", "15:00") in slots  # Status 17


def test_parse_time_page_missing_block():
    with pytest.raises(PortalError):
        parse_time_page("<html>maintenance</html>")


def test_start_date_is_jst():
    assert today_jst(datetime(2026, 11, 12, 16, 30, tzinfo=timezone.utc)) == date(2026, 11, 13)
    assert today_jst(datetime(2026, 11, 12, 14, 59, tzinfo=timezone.utc)) == date(2026, 11, 12)


# --- full flow against a fake session -------------------------------------------------

class FakeResponse:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, closing=False, month_payload=None):
        self.closing = closing
        self.month_payload = month_payload
        self.posts = []
        self.headers = {}

    def get(self, url, **kw):
        if url.endswith("AvailabilityCheckApplySelectFacility"):
            return FakeResponse(fixture("facility_page.html"))
        if url.endswith("AvailabilityCheckApplySelectTime"):
            return FakeResponse(fixture("time_page.html"))
        return FakeResponse(fixture("days_page.html"))  # Home and SelectDays both carry a token

    def post(self, url, files=None, **kw):
        self.posts.append((url.rsplit("/user/", 1)[1], files))
        if url.endswith("GetSiteClosing"):
            return FakeResponse(json.dumps({"isClosing": self.closing}))
        if url.endswith("SearchCondition"):
            return FakeResponse(json.dumps(self.month_payload) if self.month_payload else fixture("month.json"))
        if url.endswith("GetAvailability"):
            return FakeResponse("[]")
        return FakeResponse(json.dumps({"Result": "Ok", "Information": "./next"}))


NOW = datetime(2026, 11, 12, 1, 0, tzinfo=timezone.utc)


def test_fetch_slots_site_closed():
    with pytest.raises(SiteClosed):
        fetch_slots(5, [KOHOKU], session=FakeSession(closing=True), now=NOW)


def test_fetch_slots_happy_path():
    s = FakeSession()
    slots = fetch_slots(5, [KOHOKU], session=s, now=NOW)
    assert len(slots) == 7  # both batches serve the same page -> de-duplicated
    paths = [p for p, _ in s.posts]
    assert paths.count("AvailabilityCheckApplySelectDays/Next") == 2
    purpose = dict((k, v[1]) for k, v in s.posts[paths.index("Home/SearchByPurpose")][1])
    assert purpose["HomeModel.SelectedPurpose"] == "5"
    cond = dict((k, v[1]) for k, v in s.posts[paths.index("AvailabilityCheckApplySelectDays/SearchCondition")][1])
    assert cond["SearchCondition.StartDate"] == "2026-11-12"


def test_fetch_slots_error_result_raises():
    class ErrSession(FakeSession):
        def post(self, url, files=None, **kw):
            if url.endswith("Home/SearchByPurpose"):
                return FakeResponse(json.dumps({"Result": "Error", "Information": "E-205-000004"}))
            return super().post(url, files=files, **kw)

    with pytest.raises(PortalError, match="E-205-000004"):
        fetch_slots(5, [KOHOKU], session=ErrSession(), now=NOW)


def test_fetch_slots_no_candidates_skips_time_pages():
    payload = month()
    for row in payload[1]["Horizontal"][0]["Common"]["Rows"]:
        for c in row["Cells"]:
            c["DisplayStatusForUser"] = "full"
    s = FakeSession(month_payload=payload)
    assert fetch_slots(5, [KOHOKU], session=s, now=NOW) == []
    assert "AvailabilityCheckApplySelectDays/Next" not in [p for p, _ in s.posts]


def test_debug_dump_on_error(tmp_path, monkeypatch):
    monkeypatch.setattr(portal, "DEBUG_DIR", tmp_path)
    with pytest.raises(PortalError):
        fetch_slots(5, ["Nonexistent"], session=FakeSession(), now=NOW)
    assert (tmp_path / "last_response.txt").exists()
