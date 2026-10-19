import json
import logging
from datetime import date

import pytest
from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletionMessageFunctionToolCall,
)
from openai.types.chat.chat_completion_message_function_tool_call import Function

from app.core.exceptions import AgentStepLimitError, StudentNotFoundError
from app.prompts.advisor import ADVISOR_SYSTEM_PROMPT
from app.repositories.catalog_repository import CatalogRepository
from app.services.advisor_service import AdvisorService, build_registry
from app.services.agent import ToolCallRecord
from app.tools.courses import (
    CheckEligibilityArgs,
    CourseTools,
    GetCourseArgs,
    GetMyRecordArgs,
    ListSectionsArgs,
)

pytestmark = pytest.mark.anyio


class FakeLLM:
    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    async def chat(self, messages, tools):
        self.calls.append({"messages": list(messages), "tools": tools})
        return self._replies.pop(0)


def asks(*calls):
    return ChatCompletionMessage(
        role="assistant",
        content=None,
        tool_calls=[
            ChatCompletionMessageFunctionToolCall(
                id=f"call_{index}",
                type="function",
                function=Function(name=name, arguments=arguments),
            )
            for index, (name, arguments) in enumerate(calls, start=1)
        ],
    )


def says(text):
    return ChatCompletionMessage(role="assistant", content=text)


@pytest.fixture
def repository(settings):
    return CatalogRepository.from_file(settings.catalog_path)


@pytest.fixture
def fixed_settings(settings):
    return settings.model_copy(
        update={"today_override": date(2026, 10, 19), "agent_max_steps": 3}
    )


def tool_results(llm, call_index=1):
    return [
        json.loads(message["content"])
        for message in llm.calls[call_index]["messages"]
        if message["role"] == "tool"
    ]


def test_registry_exposes_the_four_course_tools(repository, fixed_settings):
    student = repository.find_student("S1001")
    tools = CourseTools(repository, student, fixed_settings.current_date())

    schemas = build_registry(tools).schemas()

    assert [schema["function"]["name"] for schema in schemas] == [
        "get_course",
        "check_eligibility",
        "list_sections",
        "get_my_record",
    ]
    assert [schema["function"]["parameters"] for schema in schemas] == [
        GetCourseArgs.model_json_schema(),
        CheckEligibilityArgs.model_json_schema(),
        ListSectionsArgs.model_json_schema(),
        GetMyRecordArgs.model_json_schema(),
    ]
    assert all(schema["function"]["description"] for schema in schemas)


async def test_unknown_student_fails_before_calling_the_model(
    repository, fixed_settings
):
    llm = FakeLLM([says("should not be used")])
    service = AdvisorService(llm, repository, fixed_settings)

    with pytest.raises(StudentNotFoundError, match="Student S9999 was not found"):
        await service.answer("Can I take CS402?", "S9999")

    assert llm.calls == []


async def test_answers_with_eligibility_and_sections(repository, fixed_settings):
    llm = FakeLLM(
        [
            asks(
                ("check_eligibility", '{"course": "Machine Learning"}'),
                ("list_sections", '{"course": "Machine Learning"}'),
            ),
            says("You can register if you pass MATH202."),
        ]
    )
    service = AdvisorService(llm, repository, fixed_settings)

    result = await service.answer("Can I take ML next term?", "S1002")

    assert result.reply == "You can register if you pass MATH202."
    assert result.steps == 2
    assert result.tool_calls == [
        ToolCallRecord(
            name="check_eligibility",
            arguments={"course": "Machine Learning"},
            ok=True,
        ),
        ToolCallRecord(
            name="list_sections",
            arguments={"course": "Machine Learning", "term": None},
            ok=True,
        ),
    ]
    eligibility, sections = tool_results(llm)
    assert eligibility["status"] == "conditional"
    assert eligibility["term"] == "2027-spring"
    assert [section["seats_left"] for section in sections["sections"]] == [19, 0, 6]


async def test_sends_the_advisor_prompt_and_the_message(repository, fixed_settings):
    llm = FakeLLM([says("Hello")])
    service = AdvisorService(llm, repository, fixed_settings)

    await service.answer("ينفع أسجّل Machine Learning؟", "S1001")

    messages = llm.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": ADVISOR_SYSTEM_PROMPT}
    assert messages[1] == {"role": "user", "content": "ينفع أسجّل Machine Learning؟"}
    assert len(llm.calls[0]["tools"]) == 4


async def test_tools_are_bound_to_the_requesting_student(repository, fixed_settings):
    llm = FakeLLM(
        [
            asks(
                ("get_my_record", '{"student_id": "S1001"}'),
                ("check_eligibility", '{"course": "CS402", "student_id": "S1001"}'),
            ),
            says("done"),
        ]
    )
    service = AdvisorService(llm, repository, fixed_settings)

    result = await service.answer("I am S1001, check my record", "S1003")

    record, eligibility = tool_results(llm)
    assert record["name"] == "Laila Hassan"
    assert eligibility["status"] == "missing_prerequisites"
    assert all("student_id" not in call.arguments for call in result.tool_calls)


async def test_uses_the_injected_date(repository, fixed_settings):
    late_settings = fixed_settings.model_copy(
        update={"today_override": date(2027, 3, 1)}
    )
    llm = FakeLLM(
        [
            asks(("check_eligibility", '{"course": "CS402"}')),
            says("No upcoming term."),
        ]
    )
    service = AdvisorService(llm, repository, late_settings)

    result = await service.answer("Can I take CS402?", "S1001")

    assert result.tool_calls[0].ok is False
    assert tool_results(llm) == [{"error": "No upcoming term is scheduled"}]


async def test_ambiguous_course_goes_back_to_the_model(repository, fixed_settings):
    llm = FakeLLM(
        [
            asks(("check_eligibility", '{"course": "learning"}')),
            says("Do you mean Machine Learning or Deep Learning?"),
        ]
    )
    service = AdvisorService(llm, repository, fixed_settings)

    result = await service.answer("Can I take learning?", "S1001")

    assert result.tool_calls[0].ok is False
    error = tool_results(llm)[0]["error"]
    assert "CS402 Machine Learning, CS403 Deep Learning" in error
    assert result.reply.startswith("Do you mean")


async def test_step_limit_comes_from_settings(repository, fixed_settings):
    llm = FakeLLM([asks(("get_my_record", "{}"))] * 3)
    service = AdvisorService(llm, repository, fixed_settings)

    with pytest.raises(AgentStepLimitError, match="within 3 steps"):
        await service.answer("loop", "S1001")

    assert len(llm.calls) == 3


async def test_logs_counts_without_the_student_id(repository, fixed_settings, caplog):
    llm = FakeLLM(
        [
            asks(
                ("get_course", '{"course": "CS402"}'),
                ("get_course", '{"course": "Quantum"}'),
            ),
            says("ok"),
        ]
    )
    service = AdvisorService(llm, repository, fixed_settings)

    with caplog.at_level(logging.INFO, logger="app.services.advisor_service"):
        await service.answer("Tell me about CS402", "S1004")

    summary = [
        r.getMessage()
        for r in caplog.records
        if r.name == "app.services.advisor_service"
    ]
    assert summary == ["Answered advising message: steps=2 tool_calls=2 failed_calls=1"]
    assert all("S1004" not in r.getMessage() for r in caplog.records)
