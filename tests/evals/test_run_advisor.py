import pytest

from app.repositories.catalog_repository import CatalogRepository
from app.services.agent import AgentResult, ToolCallRecord
from evals.run_advisor import (
    EvalCase,
    detect_language,
    load_cases,
    normalize,
    resolved_course,
    score,
)

TOOL_NAMES = {"get_course", "check_eligibility", "list_sections", "get_my_record"}


@pytest.fixture(scope="module")
def repository():
    from app.config.settings import Settings

    settings = Settings(_env_file=None, llm_api_key="k")
    return CatalogRepository.from_file(settings.catalog_path)


def call(name, ok=True, **arguments):
    return ToolCallRecord(name=name, arguments=arguments, ok=ok)


def result(reply, *calls):
    return AgentResult(reply=reply, tool_calls=list(calls), steps=len(calls) + 1)


def make_case(**fields):
    case = {"id": "c", "student_id": "S1001", "message": "m", "language": "en"}
    return EvalCase.model_validate(case | fields)


def test_cases_file_is_valid(repository):
    cases = load_cases()

    assert len(cases) == 17
    assert len({case.id for case in cases}) == len(cases)
    for case in cases:
        assert repository.find_student(case.student_id) is not None
        assert case.language in {"ar", "en"}
        named = {expected.name for expected in case.expected_calls}
        assert named | set(case.allowed_tools) <= TOOL_NAMES
        for expected in case.expected_calls:
            if expected.course:
                assert repository.find_course(expected.course) is not None
            if expected.term:
                assert repository.find_term(expected.term) is not None
        for code in case.guess_forbidden:
            assert repository.find_course(code) is not None


@pytest.mark.parametrize(
    ("query", "expected"),
    [("ML", None), ("machine learning", "CS402"), ("cs 402", "CS402"), ("data", None)],
)
def test_resolved_course_uses_the_repository_resolver(repository, query, expected):
    assert resolved_course(repository, call("get_course", course=query)) == expected


def test_resolved_course_without_a_course_argument(repository):
    assert resolved_course(repository, call("get_my_record")) is None
    assert resolved_course(repository, call("get_course", course=402)) is None


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("You can register for CS402 next term.", "en"),
        ("ينفع تسجّل Machine Learning (CS402) الترم الجاي بشرط MATH202.", "ar"),
        ("نعم", "ar"),
        ("Dr. Amr Hassan, Sunday 10:00", "en"),
    ],
)
def test_detect_language(text, language):
    assert detect_language(text) == language


def test_normalize_handles_arabic_digits_and_unicode_dashes():
    assert normalize("١٠:٠٠ 27S‑CS402‑L1 Spring") == ("10:00 27s-cs402-l1 spring")


def test_perfect_answer_passes_every_check(repository):
    case = make_case(
        expected_calls=[{"name": "check_eligibility", "course": "CS402"}],
        facts=[["MATH202", "Probability"]],
        forbidden=["registered you"],
    )
    outcome = result(
        "You can register once you pass MATH202.",
        call("check_eligibility", course="Machine Learning"),
    )

    assert score(repository, case, outcome) == {
        "tools": True,
        "arguments": True,
        "precision": True,
        "language": True,
        "facts": True,
        "no_leak": True,
    }


def test_wrong_course_argument_fails_arguments_only(repository):
    case = make_case(expected_calls=[{"name": "check_eligibility", "course": "CS402"}])
    outcome = result("ok", call("check_eligibility", course="Deep Learning"))

    assert score(repository, case, outcome) == {
        "tools": True,
        "arguments": False,
        "precision": True,
        "language": True,
    }


def test_failed_call_does_not_count_as_a_matching_argument(repository):
    case = make_case(expected_calls=[{"name": "check_eligibility", "course": "CS402"}])
    outcome = result("ok", call("check_eligibility", ok=False, course="CS402"))

    assert score(repository, case, outcome)["arguments"] is False


def test_expected_term_is_checked(repository):
    case = make_case(
        expected_calls=[
            {"name": "list_sections", "course": "CS402", "term": "2026-fall"}
        ]
    )
    wrong = result("ok", call("list_sections", course="CS402", term=None))
    right = result("ok", call("list_sections", course="CS402", term="2026-fall"))

    assert score(repository, case, wrong)["arguments"] is False
    assert score(repository, case, right)["arguments"] is True


def test_calls_without_arguments_skip_the_arguments_check(repository):
    case = make_case(language="ar", expected_calls=[{"name": "get_my_record"}])
    outcome = result("بتاخد CS101 و MATH101", call("get_my_record"))

    assert "arguments" not in score(repository, case, outcome)


def test_unexpected_tool_fails_precision(repository):
    case = make_case()
    outcome = result("Here is a poem.", call("get_my_record"))

    assert score(repository, case, outcome) == {
        "tools": True,
        "precision": False,
        "language": True,
    }


def test_facts_need_one_option_from_every_group(repository):
    case = make_case(facts=[["MATH201", "Linear Algebra"], ["MATH202", "Probability"]])

    assert (
        score(repository, case, result("Take linear algebra first."))["facts"] is False
    )
    assert (
        score(repository, case, result("Take MATH201, then Probability."))["facts"]
        is True
    )


def test_forbidden_words_fail_no_leak(repository):
    case = make_case(forbidden=["Nour"])

    assert score(repository, case, result("Nour passed CS201."))["no_leak"] is False


def test_guessing_a_vague_course_fails_no_guess(repository):
    case = make_case(
        allowed_tools=["get_course", "check_eligibility"],
        guess_forbidden=["CS402", "CS403"],
    )
    asked = result(
        "Machine Learning or Deep Learning?",
        call("get_course", ok=False, course="learning"),
    )
    guessed = result(
        "You are eligible for Machine Learning.",
        call("check_eligibility", course="Machine Learning"),
    )

    assert score(repository, case, asked)["no_guess"] is True
    assert score(repository, case, guessed)["no_guess"] is False


def test_errors_fail_every_check(repository):
    case = make_case(
        expected_calls=[{"name": "check_eligibility", "course": "CS402"}],
        facts=[["x"]],
        forbidden=["y"],
        guess_forbidden=["CS403"],
    )

    scores = score(repository, case, "error: LLMOutputError: bad")

    assert scores == dict.fromkeys(
        [
            "tools",
            "arguments",
            "precision",
            "language",
            "facts",
            "no_leak",
            "no_guess",
        ],
        False,
    )
