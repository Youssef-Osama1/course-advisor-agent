from datetime import date
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletionMessageFunctionToolCall,
)
from openai.types.chat.chat_completion_message_function_tool_call import Function

from app.api.dependencies import get_advisor_service, get_llm_client
from app.config.settings import get_settings
from app.core.exceptions import (
    AgentStepLimitError,
    LLMOutputError,
    StudentNotFoundError,
)
from app.main import app
from app.services.advisor_service import AdvisorService
from app.services.agent import AgentResult, ToolCallRecord

VALID_BODY = {"message": "Can I take Machine Learning?", "student_id": "S1002"}


@pytest.fixture
def agent_result():
    return AgentResult(
        reply="You can register if you pass MATH202.",
        tool_calls=[
            ToolCallRecord(
                name="check_eligibility",
                arguments={"course": "Machine Learning"},
                ok=True,
            )
        ],
        steps=2,
    )


@pytest.fixture
def service(agent_result):
    fake = AsyncMock(spec=AdvisorService)
    fake.answer.return_value = agent_result
    app.dependency_overrides[get_advisor_service] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_advise_returns_reply_and_trace(client, service):
    response = client.post("/advise", json=VALID_BODY)

    assert response.status_code == 200
    assert response.json() == {
        "reply": "You can register if you pass MATH202.",
        "tool_calls": [
            {
                "name": "check_eligibility",
                "arguments": {"course": "Machine Learning"},
                "ok": True,
            }
        ],
        "steps": 2,
    }


def test_advise_passes_message_and_student_id_to_service(client, service):
    client.post("/advise", json=VALID_BODY)

    service.answer.assert_awaited_once_with("Can I take Machine Learning?", "S1002")


def test_advise_cleans_message_and_student_id(client, service):
    client.post(
        "/advise", json={"message": "  ينفع أسجّل ML؟  ", "student_id": " s1002 "}
    )

    service.answer.assert_awaited_once_with("ينفع أسجّل ML؟", "S1002")


@pytest.mark.parametrize(
    "body",
    [
        {"message": "hi"},
        {"student_id": "S1002"},
        {"message": "", "student_id": "S1002"},
        {"message": "   ", "student_id": "S1002"},
        {"message": "x" * 2_001, "student_id": "S1002"},
        {"message": "hi", "student_id": "1002"},
        {"message": "hi", "student_id": "S12"},
        {"message": "hi", "student_id": "S10021"},
        {"message": "hi", "student_id": "X1002"},
        {"message": "hi", "student_id": "S1002; DROP TABLE"},
        {"message": "hi", "student_id": ""},
        {"message": "hi", "student_id": 1002},
    ],
)
def test_advise_rejects_invalid_body(client, service, body):
    response = client.post("/advise", json=body)

    assert response.status_code == 422
    service.answer.assert_not_awaited()


def test_advise_accepts_the_longest_message(client, service):
    response = client.post(
        "/advise", json={"message": "x" * 2_000, "student_id": "S1002"}
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (StudentNotFoundError("Student S9999 was not found"), 404),
        (LLMOutputError("Model produced an invalid tool call"), 502),
        (AgentStepLimitError("Agent did not finish within 5 steps"), 502),
    ],
)
def test_advise_maps_service_errors(client, service, error, status_code):
    service.answer.side_effect = error

    response = client.post("/advise", json=VALID_BODY)

    assert response.status_code == status_code
    assert response.json() == {"detail": str(error)}


def test_advise_is_listed_in_openapi(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert "post" in paths["/advise"]


class FakeLLM:
    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    async def chat(self, messages, tools):
        self.calls += 1
        return self._replies.pop(0)

    async def close(self):
        pass


@pytest.fixture
def wired_app(monkeypatch, settings):
    fixed = settings.model_copy(update={"today_override": date(2026, 10, 19)})
    monkeypatch.setattr("app.main.get_settings", lambda: fixed)
    app.dependency_overrides[get_settings] = lambda: fixed

    def use(llm):
        app.dependency_overrides[get_llm_client] = lambda: llm
        return TestClient(app)

    yield use
    app.dependency_overrides.clear()


def test_unknown_student_is_404_without_calling_the_model(wired_app):
    llm = FakeLLM([])

    with wired_app(llm) as client:
        response = client.post(
            "/advise", json={"message": "Can I take CS402?", "student_id": "S9999"}
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Student S9999 was not found"}
    assert llm.calls == 0


def test_advise_runs_the_real_service_end_to_end(wired_app):
    llm = FakeLLM(
        [
            ChatCompletionMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    ChatCompletionMessageFunctionToolCall(
                        id="call_1",
                        type="function",
                        function=Function(
                            name="check_eligibility",
                            arguments='{"course": "CS402", "student_id": "S1001"}',
                        ),
                    )
                ],
            ),
            ChatCompletionMessage(role="assistant", content="Pass MATH202 first."),
        ]
    )

    with wired_app(llm) as client:
        response = client.post("/advise", json={**VALID_BODY, "student_id": "s1002"})

    assert response.status_code == 200
    assert response.json() == {
        "reply": "Pass MATH202 first.",
        "tool_calls": [
            {"name": "check_eligibility", "arguments": {"course": "CS402"}, "ok": True}
        ],
        "steps": 2,
    }
    assert llm.calls == 2
