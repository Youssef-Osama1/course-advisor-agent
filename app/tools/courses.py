from datetime import date
from enum import StrEnum
from graphlib import TopologicalSorter
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.core.exceptions import ToolError
from app.repositories.catalog_repository import CatalogRepository
from app.schemas.catalog import (
    Course,
    CourseRecord,
    RecordStatus,
    Section,
    Student,
    Term,
)

CourseQuery = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
STATUS_RANK = {
    RecordStatus.FAILED: 0,
    RecordStatus.IN_PROGRESS: 1,
    RecordStatus.PASSED: 2,
}


class EligibilityStatus(StrEnum):
    ELIGIBLE = "eligible"
    CONDITIONAL = "conditional"
    MISSING_PREREQUISITES = "missing_prerequisites"
    ALREADY_PASSED = "already_passed"
    IN_PROGRESS = "in_progress"


class GetCourseArgs(BaseModel):
    course: CourseQuery = Field(
        description="Course code or English title, e.g. CS402 or Machine Learning"
    )


class CheckEligibilityArgs(BaseModel):
    course: CourseQuery = Field(
        description="Course code or English title the student wants to register for"
    )


class ListSectionsArgs(BaseModel):
    course: CourseQuery = Field(description="Course code or English title")
    term: str | None = Field(
        default=None, description="Term code such as 2027-spring, or omit for next term"
    )


class GetMyRecordArgs(BaseModel):
    pass


class CourseTools:
    def __init__(
        self, repository: CatalogRepository, student: Student, today: date
    ) -> None:
        self._repository = repository
        self._student = student
        self._today = today
        self._statuses = best_statuses(student.records)

    def get_course(self, course: str) -> dict:
        return course_summary(self._resolve(course), self._repository)

    def check_eligibility(self, course: str) -> dict:
        target = self._resolve(course)
        term = self._registration_term()
        missing, pending = prerequisite_gaps(target, self._statuses, self._repository)
        return {
            "course": target.code,
            "title": target.title,
            "term": term.code,
            "status": eligibility_status(target, self._statuses, missing, pending),
            "missing": [
                course_ref(course) | {"state": self._gap_state(course)}
                for course in missing
            ],
            "pending": [course_ref(course) for course in pending],
            "offered": bool(self._repository.list_sections(target.code, term.code)),
            "retake": self._statuses.get(target.code) is RecordStatus.FAILED,
        }

    def list_sections(self, course: str, term: str | None = None) -> dict:
        target = self._resolve(course)
        selected = self._registration_term() if term is None else self._find_term(term)
        sections = self._repository.list_sections(target.code, selected.code)
        return course_ref(target) | {
            "term": selected.code,
            "sections": [section_summary(section) for section in sections],
        }

    def get_my_record(self) -> dict:
        current = self._repository.current_term(self._today)
        grouped = {status: [] for status in RecordStatus}
        for code, status in self._statuses.items():
            grouped[status].append(course_ref(self._repository.find_course(code)))
        return {
            "name": self._student.name,
            "current_term": current.code if current else None,
        } | {str(status): courses for status, courses in grouped.items()}

    def _resolve(self, query: str) -> Course:
        matches = self._repository.match_courses(query)
        if not matches:
            raise ToolError(
                f"No course matches {query!r}; use a course code or full English title"
            )
        if len(matches) > 1:
            options = ", ".join(f"{course.code} {course.title}" for course in matches)
            raise ToolError(f"{query!r} matches several courses: {options}")
        return matches[0]

    def _registration_term(self) -> Term:
        term = self._repository.next_term(self._today)
        if term is None:
            raise ToolError("No upcoming term is scheduled")
        return term

    def _find_term(self, code: str) -> Term:
        term = self._repository.find_term(code)
        if term is None:
            raise ToolError(f"Unknown term {code!r}; use a code like 2027-spring")
        return term

    def _gap_state(self, course: Course) -> str:
        if self._statuses.get(course.code) is RecordStatus.FAILED:
            return "failed"
        return "not_taken"


def best_statuses(records: list[CourseRecord]) -> dict[str, RecordStatus]:
    statuses = {}
    for record in records:
        current = statuses.get(record.course_code)
        if current is None or STATUS_RANK[record.status] > STATUS_RANK[current]:
            statuses[record.course_code] = record.status
    return statuses


def prerequisite_gaps(
    course: Course,
    statuses: dict[str, RecordStatus],
    repository: CatalogRepository,
) -> tuple[list[Course], list[Course]]:
    missing: dict[str, Course] = {}
    pending: dict[str, Course] = {}
    queue = [course]
    while queue:
        current = queue.pop(0)
        for code in current.prerequisites:
            status = statuses.get(code)
            if status is RecordStatus.PASSED or code in missing or code in pending:
                continue
            prerequisite = repository.find_course(code)
            if status is RecordStatus.IN_PROGRESS:
                pending[code] = prerequisite
            else:
                missing[code] = prerequisite
                queue.append(prerequisite)

    graph = {
        code: [p for p in course.prerequisites if p in missing]
        for code, course in missing.items()
    }
    ordered = [missing[code] for code in TopologicalSorter(graph).static_order()]
    return ordered, list(pending.values())


def eligibility_status(
    course: Course,
    statuses: dict[str, RecordStatus],
    missing: list[Course],
    pending: list[Course],
) -> EligibilityStatus:
    status = statuses.get(course.code)
    if status is RecordStatus.PASSED:
        return EligibilityStatus.ALREADY_PASSED
    if status is RecordStatus.IN_PROGRESS:
        return EligibilityStatus.IN_PROGRESS
    if missing:
        return EligibilityStatus.MISSING_PREREQUISITES
    if pending:
        return EligibilityStatus.CONDITIONAL
    return EligibilityStatus.ELIGIBLE


def course_ref(course: Course) -> dict:
    return {"code": course.code, "title": course.title}


def course_summary(course: Course, repository: CatalogRepository) -> dict:
    prerequisites = [
        course_ref(repository.find_course(code)) for code in course.prerequisites
    ]
    summary = course.model_dump(exclude={"prerequisites"})
    return summary | {"prerequisites": prerequisites}


def section_summary(section: Section) -> dict:
    return {
        "section_id": section.section_id,
        "kind": section.kind,
        "days": section.days,
        "start": section.start.strftime("%H:%M"),
        "end": section.end.strftime("%H:%M"),
        "instructor": section.instructor,
        "seats_left": section.capacity - section.enrolled,
    }
