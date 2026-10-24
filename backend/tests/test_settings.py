"""Файл настроек settings.toml: приоритеты, проверка опечаток, секреты, настройки интерфейса."""
import pytest

from app import config
from app.config import Settings, SettingsFileError, problems, read_settings_file


def write(tmp_path, text):
    p = tmp_path / "settings.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_repo_settings_file_is_valid_and_matches_defaults():
    data = read_settings_file(config.SETTINGS_FILE)
    defaults = {k: f.default for k, f in Settings.model_fields.items()}
    assert set(data) == {k for keys in config.SECTIONS.values() for k in keys}, "в файле перечислены все настройки"
    assert {k: v for k, v in data.items() if v != defaults[k]} == {}, "значения в файле = умолчания в коде"


def test_typo_and_wrong_section_and_secret(tmp_path):
    with pytest.raises(SettingsFileError, match="может быть, «session_hours»"):
        read_settings_file(write(tmp_path, "[auth]\nsesion_hours = 3\n"))
    with pytest.raises(SettingsFileError, match=r"\[ldap\]"):
        read_settings_file(write(tmp_path, "[auth]\nldap_url = 'x'\n"))
    with pytest.raises(SettingsFileError, match="может быть, \\[limits\\]"):
        read_settings_file(write(tmp_path, "[limit]\nfacet_limit = 3\n"))
    with pytest.raises(SettingsFileError, match="LAWDESK_SECRET_KEY"):
        read_settings_file(write(tmp_path, "[auth]\nsecret_key = 'x'\n"))


def test_env_beats_file_beats_default(tmp_path, monkeypatch):
    monkeypatch.setenv("LAWDESK_SETTINGS_FILE", str(write(tmp_path, "[auth]\nsession_hours = 3\n[limits]\nfacet_limit = 7\n")))
    monkeypatch.setenv("LAWDESK_FACET_LIMIT", "9")
    s = Settings()
    assert s.session_hours == 3 and s.facet_limit == 9 and s.page_size_max == 500


def test_problems_found():
    s = Settings(auth_mode="x", fallback_holidays=["13-40"], facet_limit=0)
    bad = " ".join(problems(s))
    assert "auth_mode" in bad and "13-40" in bad and "facet_limit" in bad


def test_source_trust_from_settings(svc, monkeypatch):
    from app.config import get_settings
    from test_api import ingest_case, obs

    monkeypatch.setattr(get_settings(), "source_trust", ["OCR", "1С"])
    cid = ingest_case(svc)
    obs(svc, "judge", "1С", "Иванова А.А.")
    obs(svc, "judge", "OCR", "ИВАНОВА А.А.")  # то же после приведения; показывается более надёжный — OCR
    v = next(x for x in svc.get(f"/api/v1/cases/{cid}").json()["values"] if x["field"] == "judge")
    assert v["status"] == "confirmed" and v["value"] == "ИВАНОВА А.А."


def test_client_settings_endpoint(viewer):
    r = viewer.get("/api/v1/settings/client").json()
    assert r["desk_pile_size"] == 60 and r["goal_conflicts"] == 50 and r["soon_days"] == 7
