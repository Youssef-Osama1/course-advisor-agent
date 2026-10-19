from datetime import date

import pytest

from app.config.settings import Settings
from app.repositories.catalog_repository import CatalogRepository
from app.schemas.catalog import CatalogData


@pytest.fixture(scope="module")
def repository():
    settings = Settings(_env_file=None, llm_api_key="k")
    return CatalogRepository.from_file(settings.catalog_path)


def codes(courses):
    return [course.code for course in courses]


def test_from_file_rejects_invalid_catalog(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text('{"terms": [], "courses": []}', encoding="utf-8")

    with pytest.raises(ValueError):
        CatalogRepository.from_file(path)


def test_find_course_by_exact_code(repository):
    assert repository.find_course("CS402").title == "Machine Learning"
    assert repository.find_course("cs402") is None
    assert repository.find_course("CS999") is None


@pytest.mark.parametrize("query", ["CS402", "cs402", "CS 402", " cs402 "])
def test_match_courses_by_code_ignores_case_and_spaces(repository, query):
    assert codes(repository.match_courses(query)) == ["CS402"]


@pytest.mark.parametrize(
    "query", ["Machine Learning", "machine learning", "  MACHINE LEARNING  "]
)
def test_match_courses_by_exact_title(repository, query):
    assert codes(repository.match_courses(query)) == ["CS402"]


def test_exact_title_wins_over_partial_matches():
    data = CatalogData.model_validate(
        {
            "terms": [],
            "courses": [
                {"code": "A1", "title": "Statistics", "credits": 3, "description": "d"},
                {
                    "code": "A2",
                    "title": "Applied Statistics",
                    "credits": 3,
                    "description": "d",
                },
            ],
            "sections": [],
            "students": [],
        }
    )
    repository = CatalogRepository(data)

    assert codes(repository.match_courses("statistics")) == ["A1"]
    assert codes(repository.match_courses("stat")) == ["A1", "A2"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("probability", ["MATH202"]),
        ("vision", ["CS410"]),
        ("learning", ["CS402", "CS403"]),
        ("data", ["CS201", "CS305"]),
    ],
)
def test_match_courses_by_partial_title(repository, query, expected):
    assert codes(repository.match_courses(query)) == expected


@pytest.mark.parametrize("query", ["", "   ", "Quantum Computing", "تعلم الآلة"])
def test_match_courses_returns_nothing_without_a_match(repository, query):
    assert repository.match_courses(query) == []


def test_find_student(repository):
    assert repository.find_student("S1002").name == "Karim Mostafa"
    assert repository.find_student("S9999") is None
    assert repository.find_student("s1002") is None


def test_find_term(repository):
    assert repository.find_term("2027-spring").name == "Spring 2027"
    assert repository.find_term("2030-fall") is None


@pytest.mark.parametrize(
    ("today", "current", "upcoming"),
    [
        (date(2026, 10, 19), "2026-fall", "2027-spring"),
        (date(2026, 9, 12), "2026-fall", "2027-spring"),
        (date(2027, 1, 15), "2026-fall", "2027-spring"),
        (date(2027, 1, 20), None, "2027-spring"),
        (date(2027, 2, 13), "2027-spring", None),
        (date(2025, 1, 1), None, "2025-spring"),
        (date(2028, 1, 1), None, None),
    ],
)
def test_current_and_next_term_follow_today(repository, today, current, upcoming):
    current_term = repository.current_term(today)
    next_term = repository.next_term(today)

    assert (current_term.code if current_term else None) == current
    assert (next_term.code if next_term else None) == upcoming


def test_list_sections_filters_by_course_and_term(repository):
    spring = repository.list_sections("CS402", "2027-spring")
    fall = repository.list_sections("CS402", "2026-fall")

    assert [section.section_id for section in spring] == [
        "27S-CS402-L1",
        "27S-CS402-T1",
        "27S-CS402-T2",
    ]
    assert [section.section_id for section in fall] == ["26F-CS402-L1"]


def test_list_sections_is_empty_when_not_offered(repository):
    assert repository.list_sections("CS410", "2027-spring") == []
    assert repository.list_sections("CS999", "2027-spring") == []
