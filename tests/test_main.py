from datetime import datetime, timedelta, timezone

import pytest

from bot import main as main_mod
from bot.config import Config, Rule
from bot.portal import PortalError, SiteClosed
from bot.slots import Slot
from bot.state import State, load_state, save_state
from bot.telegram import TelegramError

K = "港北スポーツセンター"
A = Slot("2026-11-30", "7:30", K, "第一体育室Ａ（半面）", "9:00")
B = Slot("2026-11-30", "13:00", K, "第一体育室Ｂ（半面）", "15:00")
NOW = datetime(2026, 11, 12, 1, 0, tzinfo=timezone.utc)
CFG = Config(purpose=5, gyms=(K,), rules=(Rule(),), notify_gone=False,
             notify_no_change=False, error_alert_every_hours=6)


def fetch_returning(slots):
    def fetch(purpose, gyms, now=None):
        return list(slots)
    return fetch


def fetch_raising(exc):
    def fetch(purpose, gyms, now=None):
        raise exc
    return fetch


class Inbox:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def __call__(self, text):
        if self.fail:
            raise TelegramError("Telegram API 500: down")
        self.sent.append(text)


def run(path, fetch, inbox, now=NOW, cfg=CFG):
    return main_mod.run(cfg, path, fetch=fetch, notify=inbox, now=now)


def test_first_run_sends_one_baseline(tmp_path):
    p, inbox = tmp_path / "state.json", Inbox()
    assert run(p, fetch_returning([A, B]), inbox) == 0
    assert len(inbox.sent) == 1
    assert inbox.sent[0].startswith("🏐 Volleyball bot is running")
    assert load_state(p).slots == [A, B]


def test_new_slot_notified_once(tmp_path):
    p, inbox = tmp_path / "state.json", Inbox()
    save_state(State(slots=[A]), p)
    assert run(p, fetch_returning([A, B]), inbox) == 0
    assert len(inbox.sent) == 1
    assert "13:00–15:00" in inbox.sent[0] and "7:30–9:00" not in inbox.sent[0]
    assert run(p, fetch_returning([A, B]), inbox) == 0
    assert len(inbox.sent) == 1


def test_rules_filter_before_diff(tmp_path):
    p, inbox = tmp_path / "state.json", Inbox()
    save_state(State(slots=[]), p)
    cfg = Config(5, (K,), (Rule(time_from="13:00"),), False, False, 6)
    run(p, fetch_returning([A, B]), inbox, cfg=cfg)
    assert len(inbox.sent) == 1 and "7:30" not in inbox.sent[0]
    assert load_state(p).slots == [B]


def test_gone_silent_by_default(tmp_path):
    p, inbox = tmp_path / "state.json", Inbox()
    save_state(State(slots=[A, B]), p)
    assert run(p, fetch_returning([A]), inbox) == 0
    assert inbox.sent == []
    assert load_state(p).slots == [A]


def test_gone_notified_when_enabled(tmp_path):
    p, inbox = tmp_path / "state.json", Inbox()
    save_state(State(slots=[A, B]), p)
    cfg = Config(5, (K,), (Rule(),), True, False, 6)
    run(p, fetch_returning([A]), inbox, cfg=cfg)
    assert len(inbox.sent) == 1 and "Gone (1)" in inbox.sent[0]


def test_no_change_message_when_enabled(tmp_path):
    p, inbox = tmp_path / "state.json", Inbox()
    save_state(State(slots=[A]), p)
    cfg = Config(5, (K,), (Rule(),), False, True, 6)
    run(p, fetch_returning([A]), inbox, cfg=cfg)
    assert len(inbox.sent) == 1 and "No change" in inbox.sent[0]


def test_single_failure_is_silent(tmp_path):
    p, inbox = tmp_path / "state.json", Inbox()
    save_state(State(slots=[A]), p)
    assert run(p, fetch_raising(PortalError("timeout")), inbox) == 0
    assert inbox.sent == []
    st = load_state(p)
    assert st.slots == [A] and st.fail_count == 1


def test_portal_error_keeps_state_and_alerts_once(tmp_path):
    p, inbox = tmp_path / "state.json", Inbox()
    save_state(State(slots=[A]), p)
    for minutes in (0, 10, 20):
        assert run(p, fetch_raising(PortalError("E-203-000017")), inbox, now=NOW + timedelta(minutes=minutes)) == 0
    assert len(inbox.sent) == 1 and inbox.sent[0].startswith("⚠️")
    st = load_state(p)
    assert st.slots == [A] and st.fail_count == 3 and st.alerted is True
    assert run(p, fetch_returning([A]), inbox, now=NOW + timedelta(minutes=30)) == 0
    assert inbox.sent[-1] == "✅ Volleyball bot is working again."
    st = load_state(p)
    assert st.fail_count == 0 and st.alerted is False
    assert st.last_error_alert == NOW + timedelta(minutes=10)   # kept: limits flapping


def test_flapping_portal_alerts_at_most_once(tmp_path):
    p, inbox = tmp_path / "state.json", Inbox()
    save_state(State(slots=[A]), p)
    t = 0
    for _ in range(4):   # fail, fail, ok -> 30 min cycles over 2 hours
        for fetch in (fetch_raising(PortalError("x")), fetch_raising(PortalError("x")), fetch_returning([A])):
            run(p, fetch, inbox, now=NOW + timedelta(minutes=t))
            t += 10
    assert len(inbox.sent) == 2
    assert inbox.sent[0].startswith("⚠️") and inbox.sent[1].startswith("✅")


def test_error_alert_repeats_after_interval(tmp_path):
    p, inbox = tmp_path / "state.json", Inbox()
    for minutes in (0, 10, 20, 6 * 60 + 10):
        run(p, fetch_raising(PortalError("x")), inbox, now=NOW + timedelta(minutes=minutes))
    assert len(inbox.sent) == 2


def test_error_on_first_run_then_baseline(tmp_path):
    p, inbox = tmp_path / "state.json", Inbox()
    run(p, fetch_raising(PortalError("x")), inbox)
    run(p, fetch_raising(PortalError("x")), inbox, now=NOW + timedelta(minutes=10))
    run(p, fetch_returning([A]), inbox, now=NOW + timedelta(minutes=20))
    assert inbox.sent[1] == "✅ Volleyball bot is working again."
    assert inbox.sent[2].startswith("🏐 Volleyball bot is running")


def test_site_closed_is_silent(tmp_path):
    p, inbox = tmp_path / "state.json", Inbox()
    save_state(State(slots=[A]), p)
    before = p.read_text()
    assert run(p, fetch_raising(SiteClosed()), inbox) == 0
    assert inbox.sent == [] and p.read_text() == before


def test_telegram_failure_does_not_save(tmp_path):
    p = tmp_path / "state.json"
    save_state(State(slots=[A]), p)
    assert run(p, fetch_returning([A, B]), Inbox(fail=True)) == 1
    assert load_state(p).slots == [A]


def test_telegram_failure_during_error_alert(tmp_path):
    p = tmp_path / "state.json"
    assert run(p, fetch_raising(PortalError("x")), Inbox(fail=True)) == 0
    assert run(p, fetch_raising(PortalError("x")), Inbox(fail=True), now=NOW + timedelta(minutes=10)) == 1
    st = load_state(p)
    assert st.last_error_alert is None and st.alerted is False   # retry the alert next time


def test_corrupt_state_gives_baseline(tmp_path):
    p, inbox = tmp_path / "state.json", Inbox()
    p.write_text("garbage")
    run(p, fetch_returning([A]), inbox)
    assert len(inbox.sent) == 1 and inbox.sent[0].startswith("🏐 Volleyball bot is running")


def test_dry_run_needs_no_secrets(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(main_mod, "fetch_slots", fetch_returning([A]))
    assert main_mod.main(["--dry-run", "--state", str(tmp_path / "s.json")]) == 0
    assert "Volleyball bot is running" in capsys.readouterr().out


def test_missing_secrets_fail_clearly(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(SystemExit, match="TELEGRAM_BOT_TOKEN"):
        main_mod.main(["--state", str(tmp_path / "s.json")])


# --- --mode list ------------------------------------------------------------

from bot.state import load_listed, save_listed


def run_list(tmp_path, fetch, inbox, now=NOW):
    return main_mod.run_list(CFG, tmp_path / "state.json", tmp_path / "list_state.json",
                             fetch=fetch, notify=inbox, now=now)


def test_list_first_time_no_marks(tmp_path):
    inbox = Inbox()
    assert run_list(tmp_path, fetch_returning([A, B]), inbox) == 0
    assert len(inbox.sent) == 1
    assert inbox.sent[0].startswith("📋 Free now at Kohoku (2)")
    assert "🆕" not in inbox.sent[0] and "Taken" not in inbox.sent[0]
    assert load_listed(tmp_path / "list_state.json") == [A, B]
    assert load_state(tmp_path / "state.json").slots == [A, B]


def test_list_marks_new_and_taken(tmp_path):
    inbox = Inbox()
    save_listed([A], tmp_path / "list_state.json")
    run_list(tmp_path, fetch_returning([B]), inbox)
    assert "🆕 13:00–15:00" in inbox.sent[0]
    assert "Taken since the last /list (1):" in inbox.sent[0]
    assert "7:30–9:00 · Kohoku · Gym 1 A (half)" in inbox.sent[0]


def test_list_then_scan_is_silent(tmp_path):
    inbox = Inbox()
    run_list(tmp_path, fetch_returning([A, B]), inbox)
    assert run(tmp_path / "state.json", fetch_returning([A, B]), inbox) == 0
    assert len(inbox.sent) == 1


def test_list_keeps_failure_fields(tmp_path):
    save_state(State(slots=[A], fail_count=3, alerted=True, last_error_alert=NOW), tmp_path / "state.json")
    run_list(tmp_path, fetch_returning([A, B]), Inbox())
    st = load_state(tmp_path / "state.json")
    assert (st.slots, st.fail_count, st.alerted, st.last_error_alert) == ([A, B], 3, True, NOW)


def test_list_portal_error_reports_immediately(tmp_path):
    inbox = Inbox()
    save_state(State(slots=[A]), tmp_path / "state.json")
    before = (tmp_path / "state.json").read_text()
    assert run_list(tmp_path, fetch_raising(PortalError("boom")), inbox) == 0
    assert inbox.sent == ["⚠️ Could not read the portal: PortalError: boom"]
    assert (tmp_path / "state.json").read_text() == before
    assert not (tmp_path / "list_state.json").exists()


def test_list_site_closed(tmp_path):
    inbox = Inbox()
    assert run_list(tmp_path, fetch_raising(SiteClosed()), inbox) == 0
    assert inbox.sent == ["🔧 The portal is in maintenance, try again later."]


def test_list_telegram_failure_saves_nothing(tmp_path):
    assert run_list(tmp_path, fetch_returning([A]), Inbox(fail=True)) == 1
    assert not (tmp_path / "list_state.json").exists()
    assert not (tmp_path / "state.json").exists()


def test_list_error_and_telegram_down_is_red(tmp_path):
    assert run_list(tmp_path, fetch_raising(PortalError("boom")), Inbox(fail=True)) == 1


def test_main_mode_list_dry_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(main_mod, "fetch_slots", fetch_returning([A]))
    code = main_mod.main(["--dry-run", "--mode", "list", "--state", str(tmp_path / "s.json"),
                          "--list-state", str(tmp_path / "l.json")])
    assert code == 0
    assert "📋 Free now" in capsys.readouterr().out
