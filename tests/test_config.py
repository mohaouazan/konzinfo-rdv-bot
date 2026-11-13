import os
from pathlib import Path

import pytest

from konzinfo.config import ConfigError, load_config

ROOT = Path(__file__).resolve().parents[1]


def _clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("KONZINFO_") or key.startswith("TELEGRAM_"):
            monkeypatch.delenv(key, raising=False)


def test_example_config_loads_without_person(monkeypatch):
    _clean_env(monkeypatch)
    cfg = load_config(ROOT / "config.example.yaml", root=ROOT, require_person=False)
    assert cfg.booking.consulate == "Morocco - Rabat"
    assert cfg.booking.applications == ["Schengen"]
    assert cfg.booking.person is None  # placeholders ignores


def test_example_config_requires_real_person(monkeypatch):
    _clean_env(monkeypatch)
    with pytest.raises(ConfigError):
        load_config(ROOT / "config.example.yaml", root=ROOT, require_person=True)


def test_person_from_environment(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("KONZINFO_PERSON_NAME", "TEST NOM")
    monkeypatch.setenv("KONZINFO_PERSON_BIRTH_DATE", "1999-01-02")
    monkeypatch.setenv("KONZINFO_PERSON_PHONE", "+212600000000")
    monkeypatch.setenv("KONZINFO_PERSON_EMAIL", "test@example.com")
    monkeypatch.setenv("KONZINFO_PERSON_PASSPORT", "AB123456")
    cfg = load_config(ROOT / "config.watch.yaml", root=ROOT, require_person=True)
    assert cfg.booking.person.name == "TEST NOM"
    assert cfg.booking.person.birth_date.isoformat() == "1999-01-02"
    assert cfg.booking.person.passport_number == "AB123456"
    assert cfg.polling.interval_minutes == 5


def test_env_overrides_and_telegram(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("KONZINFO_CONSULATE", "Algeria - Algiers")
    monkeypatch.setenv("KONZINFO_APPLICATIONS", "Visa, Passport")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    cfg = load_config(ROOT / "config.watch.yaml", root=ROOT)
    assert cfg.booking.consulate == "Algeria - Algiers"
    assert cfg.booking.applications == ["Visa", "Passport"]
    assert cfg.telegram.enabled


def test_invalid_values(tmp_path, monkeypatch):
    _clean_env(monkeypatch)
    bad = tmp_path / "c.yaml"
    bad.write_text("booking:\n  consulate: X\n  applications: [A]\nslots:\n  hours: ['8h', '12:00']\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(bad, root=tmp_path)
    bad.write_text("booking:\n  consulate: X\n  applications: [A]\npolling:\n  interval_minutes: 0.2\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(bad, root=tmp_path)
    bad.write_text("booking:\n  consulate: ''\n  applications: [A]\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(bad, root=tmp_path)
