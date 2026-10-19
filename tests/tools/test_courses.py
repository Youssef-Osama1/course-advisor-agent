import json
from datetime import date

import pytest

from app.config.settings import Settings
from app.core.exceptions import ToolError
from app.repositories.catalog_repository import CatalogRepository
from app.schemas.catalog import CourseRecord, RecordStatus, Student
from app.services.agent import Tool, ToolRegistry
from app.tools.courses import (
    CheckEligibilityArgs,
    CourseTools,
    EligibilityStatus,
    GetCourseArgs,
    GetMyRecordArgs,
    ListSectionsArgs,
    best_statuses,
    eligibility_status,
    prerequisite_gaps,
)

TODAY = date(2026, 10, 19)


@pytest.fixture(scope="module")
def repository():
    settings = Settings(_env_file=None, llm_api_key="k")
    return CatalogRepository.from_file(settings.catalog_path)


@pytest.fixture
def tools_for(repository):
    def build(student_id, today=TODAY):
        return CourseTools(repository, repository.find_student(student_id), today)

    return build


def record(code, status, term="2026-spring"):
    return CourseRecord(course_code=code, term=term, status=status)


def codes(items):
    return [item["code"] for item in items]


def test_best_status_prefers_passed_then_in_progress_then_failed():
    records = [
        record("CS201", "passed"),
        record("CS201", "failed"),
        record("MATH201", "failed"),
        record("MATH201", "in_progress"),
        record("CS305", "failed"),
    ]

    assert best_statuses(records) == {
        "CS201": RecordStatus.PASSED,
        "MATH201": RecordStatus.IN_PROGRESS,
        "CS305": RecordStatus.FAILED,
    }


def test_prerequisite_gaps_follow_the_chain_in_take_order(repository):
    course = repository.find_course("CS403")

    missing, pending = prerequisite_gaps(course, {}, repository)

    order = [course.code for course in missing]
    assert set(order) == {"CS101", "CS201", "MATH101", "MATH201", "MATH202", "CS402"}
    assert order.index("CS101") < order.index("CS201") < order.index("CS402")
    assert order.index("MATH101") < order.index("MATH201") < order.index("MATH202")
    assert order.index("MATH202") < order.index("CS402")
    assert order[-1] == "CS402"
    assert pending == []


def test_prerequisite_gaps_stop_at_passed_and_in_progress_courses(repository):
    course = repository.find_course("CS402")
    statuses = {"CS201": RecordStatus.PASSED, "MATH201": RecordStatus.IN_PROGRESS}

    missing, pending = prerequisite_gaps(course, statuses, repository)

    assert [course.code for course in missing] == ["MATH202"]
    assert [course.code for course in pending] == ["MATH201"]


def test_course_without_prerequisites_has_no_gaps(repository):
    assert prerequisite_gaps(repository.find_course("CS101"), {}, repository) == (
        [],
        [],
    )


@pytest.mark.parametrize(
    ("status", "missing", "pending", "expected"),
    [
        (RecordStatus.PASSED, [], [], EligibilityStatus.ALREADY_PASSED),
        (RecordStatus.IN_PROGRESS, [], [], EligibilityStatus.IN_PROGRESS),
        (None, ["x"], ["y"], EligibilityStatus.MISSING_PREREQUISITES),
        (RecordStatus.FAILED, ["x"], [], EligibilityStatus.MISSING_PREREQUISITES),
        (None, [], ["y"], EligibilityStatus.CONDITIONAL),
        (None, [], [], EligibilityStatus.ELIGIBLE),
        (RecordStatus.FAILED, [], [], EligibilityStatus.ELIGIBLE),
    ],
)
def test_eligibility_status_priority(repository, status, missing, pending, expected):
    course = repository.find_course("CS402")
    statuses = {"CS402": status} if status else {}

    assert eligibility_status(course, statuses, missing, pending) is expected


def test_eligible_student(tools_for):
    result = tools_for("S1001").check_eligibility("Machine Learning")

    assert result == {
        "course": "CS402",
        "title": "Machine Learning",
        "term": "2027-spring",
        "status": "eligible",
        "missing": [],
        "pending": [],
        "offered": True,
        "retake": False,
    }


def test_prerequisite_in_progress_is_conditional(tools_for):
    result = tools_for("S1002").check_eligibility("CS402")

    assert result["status"] == "conditional"
    assert result["missing"] == []
    assert codes(result["pending"]) == ["MATH202"]


def test_failed_prerequisite_reports_the_whole_chain(tools_for):
    result = tools_for("S1003").check_eligibility("CS402")

    assert result["status"] == "missing_prerequisites"
    assert result["missing"] == [
        {"code": "MATH201", "title": "Linear Algebra", "state": "failed"},
        {
            "code": "MATH202",
            "title": "Probability and Statistics",
            "state": "not_taken",
        },
    ]
    assert result["pending"] == []


def test_new_student_has_missing_and_pending_courses(tools_for):
    result = tools_for("S1004").check_eligibility("Deep Learning")

    assert result["status"] == "missing_prerequisites"
    assert set(codes(result["missing"])) == {"CS201", "MATH201", "MATH202", "CS402"}
    assert codes(result["missing"])[-1] == "CS402"
    assert codes(result["pending"]) == ["CS101", "MATH101"]


def test_course_in_progress(tools_for):
    assert tools_for("S1005").check_eligibility("CS402")["status"] == "in_progress"


def test_course_after_one_in_progress_is_conditional(tools_for):
    result = tools_for("S1005").check_eligibility("Deep Learning")

    assert result["status"] == "conditional"
    assert codes(result["pending"]) == ["CS402"]


def test_already_passed_course(tools_for):
    result = tools_for("S1001").check_eligibility("Data Structures")

    assert result["status"] == "already_passed"
    assert result["retake"] is False


def test_failed_then_passed_counts_as_passed(tools_for):
    result = tools_for("S1005").check_eligibility("CS201")

    assert result["status"] == "already_passed"
    assert result["retake"] is False


def test_failed_course_can_be_retaken(tools_for):
    result = tools_for("S1001").check_eligibility("Databases")

    assert result["status"] == "eligible"
    assert result["retake"] is True


def test_course_not_offered_next_term(tools_for):
    result = tools_for("S1005").check_eligibility("Computer Vision")

    assert result["offered"] is False
    assert result["status"] == "conditional"


def test_eligibility_targets_the_term_after_today(tools_for):
    assert tools_for("S1001", date(2027, 1, 20)).check_eligibility("CS402")["term"] == (
        "2027-spring"
    )


def test_no_upcoming_term_is_a_tool_error(tools_for):
    tools = tools_for("S1001", date(2027, 3, 1))

    with pytest.raises(ToolError, match="No upcoming term"):
        tools.check_eligibility("CS402")
    with pytest.raises(ToolError, match="No upcoming term"):
        tools.list_sections("CS402")


def test_unknown_course_is_a_tool_error(tools_for):
    with pytest.raises(ToolError, match="No course matches 'ML'; use a course code"):
        tools_for("S1001").check_eligibility("ML")


@pytest.mark.parametrize(
    ("query", "options"),
    [
        ("learning", "CS402 Machine Learning, CS403 Deep Learning"),
        ("data", "CS201 Data Structures, CS305 Databases"),
    ],
)
def test_ambiguous_course_lists_the_candidates(tools_for, query, options):
    tools = tools_for("S1001")

    for call in (tools.get_course, tools.check_eligibility, tools.list_sections):
        with pytest.raises(ToolError, match=f"matches several courses: {options}"):
            call(query)


def test_get_course_returns_details_with_prerequisite_titles(tools_for):
    assert tools_for("S1001").get_course("cs 402") == {
        "code": "CS402",
        "title": "Machine Learning",
        "credits": 3,
        "description": (
            "Supervised and unsupervised learning, model evaluation and regularization."
        ),
        "prerequisites": [
            {"code": "CS201", "title": "Data Structures"},
            {"code": "MATH202", "title": "Probability and Statistics"},
        ],
    }


def test_list_sections_defaults_to_next_term(tools_for):
    result = tools_for("S1002").list_sections("Machine Learning")

    assert result["code"] == "CS402"
    assert result["term"] == "2027-spring"
    assert result["sections"][0] == {
        "section_id": "27S-CS402-L1",
        "kind": "lecture",
        "days": ["sunday", "tuesday"],
        "start": "10:00",
        "end": "11:30",
        "instructor": "Dr. Amr Hassan",
        "seats_left": 19,
    }
    assert [s["seats_left"] for s in result["sections"]] == [19, 0, 6]


def test_list_sections_for_a_given_term(tools_for):
    result = tools_for("S1002").list_sections("CS402", term="2026-fall")

    assert result["term"] == "2026-fall"
    assert [s["section_id"] for s in result["sections"]] == ["26F-CS402-L1"]


def test_list_sections_is_empty_when_not_offered(tools_for):
    assert tools_for("S1001").list_sections("Computer Vision")["sections"] == []


def test_unknown_term_is_a_tool_error(tools_for):
    with pytest.raises(ToolError, match="Unknown term 'next'; use a code like"):
        tools_for("S1001").list_sections("CS402", term="next")


def test_get_my_record_groups_courses_by_best_status(tools_for):
    result = tools_for("S1005").get_my_record()

    assert result["name"] == "Mariam Khaled"
    assert result["current_term"] == "2026-fall"
    assert codes(result["passed"]) == [
        "CS101",
        "MATH101",
        "CS201",
        "MATH201",
        "MATH202",
    ]
    assert result["failed"] == []
    assert codes(result["in_progress"]) == ["CS402", "CS305"]


def test_get_my_record_lists_failed_courses(tools_for):
    assert codes(tools_for("S1003").get_my_record()["failed"]) == ["MATH201"]


def test_get_my_record_between_terms(tools_for):
    assert tools_for("S1001", date(2027, 1, 20)).get_my_record()["current_term"] is None


def test_tools_only_see_the_bound_student(repository):
    student = Student(
        student_id="S9",
        name="Other",
        records=[record("CS201", "passed"), record("MATH202", "passed")],
    )
    tools = CourseTools(repository, student, TODAY)

    assert tools.check_eligibility("CS402")["status"] == "eligible"
    assert codes(tools.get_my_record()["passed"]) == ["CS201", "MATH202"]


def test_tool_results_are_json_serializable(tools_for):
    tools = tools_for("S1004")

    for result in (
        tools.get_course("CS402"),
        tools.check_eligibility("CS403"),
        tools.list_sections("CS402"),
        tools.get_my_record(),
    ):
        json.dumps(result)


def test_course_argument_is_stripped_and_required():
    assert GetCourseArgs(course="  CS402 ").course == "CS402"
    with pytest.raises(ValueError):
        CheckEligibilityArgs(course="   ")
    with pytest.raises(ValueError):
        ListSectionsArgs(course="x" * 101)


def test_no_tool_schema_accepts_a_student():
    for args_model in (
        GetCourseArgs,
        CheckEligibilityArgs,
        ListSectionsArgs,
        GetMyRecordArgs,
    ):
        properties = args_model.model_json_schema().get("properties", {})
        assert "student_id" not in properties
        assert all("student" not in name for name in properties)

    assert GetMyRecordArgs.model_json_schema().get("properties", {}) == {}


def test_student_id_sent_by_the_model_is_ignored(tools_for):
    tools = tools_for("S1003")
    registry = ToolRegistry(
        [
            Tool(
                "check_eligibility", "d", CheckEligibilityArgs, tools.check_eligibility
            ),
            Tool("get_my_record", "d", GetMyRecordArgs, tools.get_my_record),
        ]
    )

    result, call = registry.execute(
        "check_eligibility", '{"course": "CS402", "student_id": "S1001"}'
    )
    record_result, _ = registry.execute("get_my_record", '{"student_id": "S1001"}')

    assert call.ok
    assert call.arguments == {"course": "CS402"}
    assert result["status"] == "missing_prerequisites"
    assert record_result["name"] == "Laila Hassan"
