from datetime import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.catalog import (
    CatalogData,
    RecordStatus,
    Section,
    SectionKind,
    Term,
    Weekday,
)

CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "catalog.json"


def make_section(**overrides):
    section = {
        "section_id": "S-CS101-L1",
        "course_code": "CS101",
        "term": "2026-fall",
        "kind": "lecture",
        "days": ["sunday", "tuesday"],
        "start": "10:00",
        "end": "11:30",
        "instructor": "Dr. A",
        "capacity": 30,
        "enrolled": 10,
    }
    return section | overrides


def make_catalog(**overrides):
    catalog = {
        "terms": [
            {
                "code": "2026-spring",
                "name": "Spring 2026",
                "starts_on": "2026-02-14",
                "ends_on": "2026-06-11",
            },
            {
                "code": "2026-fall",
                "name": "Fall 2026",
                "starts_on": "2026-09-12",
                "ends_on": "2027-01-15",
            },
        ],
        "courses": [
            {"code": "CS101", "title": "Intro", "credits": 3, "description": "d"},
            {
                "code": "CS201",
                "title": "Data Structures",
                "credits": 3,
                "description": "d",
                "prerequisites": ["CS101"],
            },
        ],
        "sections": [make_section()],
        "students": [
            {
                "student_id": "S1",
                "name": "Student",
                "records": [
                    {"course_code": "CS101", "term": "2026-spring", "status": "passed"}
                ],
            }
        ],
    }
    return catalog | overrides


def test_repository_catalog_file_is_valid():
    data = CatalogData.model_validate_json(CATALOG_PATH.read_text(encoding="utf-8"))

    assert len(data.terms) == 5
    assert len(data.courses) == 10
    assert len(data.sections) == 21
    assert len(data.students) == 5


def test_minimal_catalog_is_valid():
    data = CatalogData.model_validate(make_catalog())

    assert data.students[0].records[0].status is RecordStatus.PASSED
    assert data.courses[0].prerequisites == []


def test_section_parses_enums_and_times():
    section = Section.model_validate(make_section())

    assert section.kind is SectionKind.LECTURE
    assert section.days == [Weekday.SUNDAY, Weekday.TUESDAY]
    assert section.start == time(10, 0)


def test_term_must_end_after_it_starts():
    with pytest.raises(ValidationError, match="ends before it starts"):
        Term(code="t", name="T", starts_on="2026-06-01", ends_on="2026-02-01")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"start": "12:00", "end": "11:00"}, "ends before it starts"),
        ({"start": "12:00", "end": "12:00"}, "ends before it starts"),
        ({"capacity": 20, "enrolled": 21}, "over capacity"),
        ({"days": []}, "at least 1 item"),
        ({"days": ["friday"]}, "Input should be"),
        ({"kind": "seminar"}, "Input should be"),
        ({"capacity": 0}, "greater than 0"),
        ({"enrolled": -1}, "greater than or equal to 0"),
    ],
)
def test_invalid_section_is_rejected(overrides, message):
    with pytest.raises(ValidationError, match=message):
        Section.model_validate(make_section(**overrides))


def test_full_section_is_allowed():
    section = Section.model_validate(make_section(capacity=25, enrolled=25))

    assert section.enrolled == section.capacity


def test_course_credits_must_be_positive():
    courses = [{"code": "CS101", "title": "Intro", "credits": 0, "description": "d"}]

    with pytest.raises(ValidationError, match="greater than 0"):
        CatalogData.model_validate(make_catalog(courses=courses))


def test_invalid_record_status_is_rejected():
    students = [
        {
            "student_id": "S1",
            "name": "Student",
            "records": [
                {"course_code": "CS101", "term": "2026-spring", "status": "dropped"}
            ],
        }
    ]

    with pytest.raises(ValidationError, match="Input should be"):
        CatalogData.model_validate(make_catalog(students=students))


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("terms", "Duplicate term code"),
        ("courses", "Duplicate course code"),
        ("sections", "Duplicate section_id"),
        ("students", "Duplicate student_id"),
    ],
)
def test_duplicate_keys_are_rejected(field, message):
    catalog = make_catalog()
    duplicated = catalog[field] + [catalog[field][-1]]

    with pytest.raises(ValidationError, match=message):
        CatalogData.model_validate(make_catalog(**{field: duplicated}))


def test_overlapping_terms_are_rejected():
    catalog = make_catalog()
    catalog["terms"][1]["starts_on"] = "2026-06-11"

    with pytest.raises(ValidationError, match="must start after 2026-spring"):
        CatalogData.model_validate(catalog)


def test_unsorted_terms_are_rejected():
    catalog = make_catalog()
    reversed_terms = list(reversed(catalog["terms"]))

    with pytest.raises(ValidationError, match="must start after 2026-fall"):
        CatalogData.model_validate(make_catalog(terms=reversed_terms))


def test_unknown_prerequisite_is_rejected():
    catalog = make_catalog()
    catalog["courses"][1]["prerequisites"] = ["CS999"]

    with pytest.raises(ValidationError, match=r"Unknown course codes: \['CS999'\]"):
        CatalogData.model_validate(catalog)


def test_section_for_unknown_course_is_rejected():
    sections = [make_section(course_code="CS999")]

    with pytest.raises(ValidationError, match="Unknown course codes"):
        CatalogData.model_validate(make_catalog(sections=sections))


def test_section_in_unknown_term_is_rejected():
    sections = [make_section(term="2030-fall")]

    with pytest.raises(ValidationError, match=r"Unknown terms: \['2030-fall'\]"):
        CatalogData.model_validate(make_catalog(sections=sections))


def test_record_for_unknown_course_or_term_is_rejected():
    catalog = make_catalog()
    catalog["students"][0]["records"] = [
        {"course_code": "CS999", "term": "2026-spring", "status": "passed"}
    ]
    with pytest.raises(ValidationError, match="Unknown course codes"):
        CatalogData.model_validate(catalog)

    catalog["students"][0]["records"] = [
        {"course_code": "CS101", "term": "1999-fall", "status": "passed"}
    ]
    with pytest.raises(ValidationError, match="Unknown terms"):
        CatalogData.model_validate(catalog)


def test_prerequisite_cycle_is_rejected():
    catalog = make_catalog()
    catalog["courses"][0]["prerequisites"] = ["CS201"]

    with pytest.raises(ValidationError, match="Prerequisite cycle"):
        CatalogData.model_validate(catalog)


def test_course_requiring_itself_is_rejected():
    catalog = make_catalog()
    catalog["courses"][0]["prerequisites"] = ["CS101"]

    with pytest.raises(ValidationError, match="Prerequisite cycle"):
        CatalogData.model_validate(catalog)
