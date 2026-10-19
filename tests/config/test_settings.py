from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def test_reads_values_and_hides_api_key():
    settings = Settings(_env_file=None, llm_api_key="secret-key", llm_model="m")

    assert settings.llm_api_key.get_secret_value() == "secret-key"
    assert settings.llm_model == "m"
    assert "secret-key" not in repr(settings)


def test_missing_api_key_fails_fast(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_invalid_log_level_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_api_key="k", log_level="INFOO")


@pytest.mark.parametrize("steps", [0, 11])
def test_agent_max_steps_must_stay_in_range(steps):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_api_key="k", agent_max_steps=steps)


def test_catalog_path_points_to_repository_data():
    settings = Settings(_env_file=None, llm_api_key="k")

    assert settings.catalog_path.name == "catalog.json"
    assert settings.catalog_path.parent.name == "data"
    assert settings.catalog_path.is_file()


def test_today_override_is_used_as_current_date():
    settings = Settings(_env_file=None, llm_api_key="k", today_override="2026-10-19")

    assert settings.current_date() == date(2026, 10, 19)


def test_current_date_defaults_to_utc_today(monkeypatch):
    monkeypatch.delenv("TODAY_OVERRIDE", raising=False)
    settings = Settings(_env_file=None, llm_api_key="k")

    assert settings.today_override is None
    assert settings.current_date() == datetime.now(UTC).date()


def test_invalid_today_override_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_api_key="k", today_override="not-a-date")
