from datetime import date
from pathlib import Path
from typing import Self

from app.schemas.catalog import CatalogData, Course, Section, Student, Term


class CatalogRepository:
    def __init__(self, data: CatalogData) -> None:
        self._terms = data.terms
        self._courses = {course.code: course for course in data.courses}
        self._sections = data.sections
        self._students = {student.student_id: student for student in data.students}

    @classmethod
    def from_file(cls, path: Path) -> Self:
        return cls(CatalogData.model_validate_json(path.read_text(encoding="utf-8")))

    def find_course(self, code: str) -> Course | None:
        return self._courses.get(code)

    def match_courses(self, query: str) -> list[Course]:
        code = query.replace(" ", "").upper()
        if code in self._courses:
            return [self._courses[code]]
        title = query.strip().casefold()
        if not title:
            return []
        courses = self._courses.values()
        exact = [course for course in courses if course.title.casefold() == title]
        if exact:
            return exact
        return [course for course in courses if title in course.title.casefold()]

    def find_student(self, student_id: str) -> Student | None:
        return self._students.get(student_id)

    def find_term(self, code: str) -> Term | None:
        return next((term for term in self._terms if term.code == code), None)

    def current_term(self, today: date) -> Term | None:
        return next(
            (term for term in self._terms if term.starts_on <= today <= term.ends_on),
            None,
        )

    def next_term(self, today: date) -> Term | None:
        return next((term for term in self._terms if term.starts_on > today), None)

    def list_sections(self, course_code: str, term: str) -> list[Section]:
        return [
            section
            for section in self._sections
            if section.course_code == course_code and section.term == term
        ]
