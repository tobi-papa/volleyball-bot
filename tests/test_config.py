from pathlib import Path

import pytest

from bot.config import Config, Rule, load_config

ROOT = Path(__file__).resolve().parent.parent


def write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


BASE = """
purpose: 5
gyms: [港北スポーツセンター]
notify_gone: false
notify_no_change: false
error_alert_every_hours: 6
"""


def test_repo_config_loads():
    c = load_config(ROOT / "config.yaml")
    assert isinstance(c, Config)
    assert c.gyms and c.rules   # the user edits this file: only check that it loads


def test_rule_fields_parsed(tmp_path):
    p = write(tmp_path, BASE + """
rules:
  - rooms: [第一体育室（全面）]
    time_from: "19:00"
    min_duration_minutes: 120
    weekdays: [Sat, Sun]
""")
    assert load_config(p).rules == (Rule(("第一体育室（全面）",), "19:00", None, 120, ("Sat", "Sun")),)


def test_empty_gyms_rejected(tmp_path):
    p = write(tmp_path, BASE.replace("gyms: [港北スポーツセンター]", "gyms: []") + "rules: [{}]\n")
    with pytest.raises(ValueError):
        load_config(p)


def test_bad_time_rejected(tmp_path):
    p = write(tmp_path, BASE + 'rules:\n  - time_from: "7pm"\n')
    with pytest.raises(ValueError):
        load_config(p)


def test_bad_weekday_rejected(tmp_path):
    p = write(tmp_path, BASE + "rules:\n  - weekdays: [Sabato]\n")
    with pytest.raises(ValueError):
        load_config(p)


def test_missing_rules_rejected(tmp_path):
    p = write(tmp_path, BASE)
    with pytest.raises(ValueError):
        load_config(p)


def test_unquoted_time_accepted(tmp_path):
    # YAML 1.1 reads an unquoted 13:00 as the number 780 (sexagesimal)
    p = write(tmp_path, BASE + "rules:\n  - time_from: 13:00\n    time_to: 7:30\n")
    r = load_config(p).rules[0]
    assert (r.time_from, r.time_to) == ("13:00", "7:30")


def test_readme_is_utf8():
    (ROOT / "README.md").read_bytes().decode("utf-8")
