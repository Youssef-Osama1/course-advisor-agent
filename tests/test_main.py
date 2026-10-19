import json

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import (
    AgentStepLimitError,
    LLMOutputError,
    StudentNotFoundError,
)
from app.main import app, handle_model_failure, handle_student_not_found
from app.repositories.catalog_repository import CatalogRepository
from app.services.llm_client import LLMClient


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error", [LLMOutputError("refused"), AgentStepLimitError("too many steps")]
)
async def test_model_failures_become_502(error):
    response = await handle_model_failure(None, error)

    assert response.status_code == 502
    assert json.loads(response.body) == {"detail": str(error)}


def test_lifespan_creates_llm_client(monkeypatch, settings):
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    with TestClient(app):
        assert isinstance(app.state.llm_client, LLMClient)


@pytest.mark.anyio
async def test_student_not_found_becomes_404():
    response = await handle_student_not_found(
        None, StudentNotFoundError("Student S9999 was not found")
    )

    assert response.status_code == 404
    assert json.loads(response.body) == {"detail": "Student S9999 was not found"}


def test_lifespan_loads_the_catalog_repository(monkeypatch, settings):
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    with TestClient(app):
        repository = app.state.catalog_repository
        assert isinstance(repository, CatalogRepository)
        assert repository.find_student("S1001") is not None


def test_lifespan_fails_on_invalid_catalog(monkeypatch, settings, tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text('{"terms": []}', encoding="utf-8")
    broken = settings.model_copy(update={"catalog_path": path})
    monkeypatch.setattr("app.main.get_settings", lambda: broken)

    with pytest.raises(ValueError), TestClient(app):
        pass
