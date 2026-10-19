from datetime import date, time
from graphlib import CycleError, TopologicalSorter
from enum import StrEnum
from itertools import pairwise
from typing import Self

from pydantic import BaseModel, Field, model_validator


class RecordStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    IN_PROGRESS = "in_progress"


class SectionKind(StrEnum):
    LECTURE = "lecture"
    TUTORIAL = "tutorial"
    LAB = "lab"


class Weekday(StrEnum):
    SATURDAY = "saturday"
    SUNDAY = "sunday"
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"


class Term(BaseModel):
    code: str
    name: str
    starts_on: date
    ends_on: date

    @model_validator(mode="after")
    def check_dates(self) -> Self:
        if self.starts_on >= self.ends_on:
            raise ValueError(f"Term {self.code} ends before it starts")
        return self


class Course(BaseModel):
    code: str
    title: str
    credits: int = Field(gt=0)
    description: str
    prerequisites: list[str] = []


class Section(BaseModel):
    section_id: str
    course_code: str
    term: str
    kind: SectionKind
    days: list[Weekday] = Field(min_length=1)
    start: time
    end: time
    instructor: str
    capacity: int = Field(gt=0)
    enrolled: int = Field(ge=0)

    @model_validator(mode="after")
    def check_schedule(self) -> Self:
        if self.start >= self.end:
            raise ValueError(f"Section {self.section_id} ends before it starts")
        if self.enrolled > self.capacity:
            raise ValueError(f"Section {self.section_id} is over capacity")
        return self


class CourseRecord(BaseModel):
    course_code: str
    term: str
    status: RecordStatus


class Student(BaseModel):
    student_id: str
    name: str
    records: list[CourseRecord] = []


class CatalogData(BaseModel):
    terms: list[Term]
    courses: list[Course]
    sections: list[Section]
    students: list[Student]

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        term_codes = unique_keys("term code", [term.code for term in self.terms])
        course_codes = unique_keys("course code", [c.code for c in self.courses])
        unique_keys("section_id", [s.section_id for s in self.sections])
        unique_keys("student_id", [s.student_id for s in self.students])

        for previous, current in pairwise(self.terms):
            if current.starts_on <= previous.ends_on:
                raise ValueError(f"Term {current.code} must start after {previous.code}")

        records = [record for student in self.students for record in student.records]
        used_courses = {
            *(code for course in self.courses for code in course.prerequisites),
            *(section.course_code for section in self.sections),
            *(record.course_code for record in records),
        }
        if unknown := used_courses - course_codes:
            raise ValueError(f"Unknown course codes: {sorted(unknown)}")
        used_terms = {s.term for s in self.sections} | {r.term for r in records}
        if unknown := used_terms - term_codes:
            raise ValueError(f"Unknown terms: {sorted(unknown)}")

        graph = {course.code: course.prerequisites for course in self.courses}
        try:
            TopologicalSorter(graph).prepare()
        except CycleError as error:
            raise ValueError(f"Prerequisite cycle: {error.args[1]}") from error
        return self


def unique_keys(label: str, keys: list[str]) -> set[str]:
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ValueError(f"Duplicate {label}: {duplicates}")
    return set(keys)
