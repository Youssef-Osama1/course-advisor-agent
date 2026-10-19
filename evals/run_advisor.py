import asyncio
import re
from collections import Counter
from datetime import date
from pathlib import Path

from openai import APIError
from pydantic import BaseModel

from app.config.settings import get_settings
from app.core.exceptions import AgentStepLimitError, LLMOutputError
from app.repositories.catalog_repository import CatalogRepository
from app.services.advisor_service import AdvisorService
from app.services.agent import AgentResult, ToolCallRecord
from app.services.llm_client import LLMClient

CASES_PATH = Path(__file__).parent / "advisor_cases.jsonl"
REPEATS = 2
MAX_CONCURRENCY = 1
MAX_RETRIES = 10
EVAL_DATE = date(2026, 10, 19)
ARABIC_LETTER = re.compile(r"[؀-ۿ]")
LATIN_LETTER = re.compile(r"[a-z]", re.IGNORECASE)
NORMALIZE = str.maketrans("٠١٢٣٤٥٦٧٨٩‐‑–—  ", "0123456789----  ")


class ExpectedCall(BaseModel):
    name: str
    course: str | None = None
    term: str | None = None


class EvalCase(BaseModel):
    id: str
    student_id: str
    message: str
    language: str
    expected_calls: list[ExpectedCall] = []
    allowed_tools: list[str] = []
    facts: list[list[str]] = []
    forbidden: list[str] = []
    guess_forbidden: list[str] = []


def load_cases() -> list[EvalCase]:
    lines = CASES_PATH.read_text(encoding="utf-8").splitlines()
    return [EvalCase.model_validate_json(line) for line in lines if line.strip()]


async def predict(service: AdvisorService, case: EvalCase) -> AgentResult | str:
    try:
        return await service.answer(case.message, case.student_id)
    except (LLMOutputError, AgentStepLimitError, APIError) as error:
        return f"error: {type(error).__name__}: {error}"


def resolved_course(repository: CatalogRepository, call: ToolCallRecord) -> str | None:
    query = call.arguments.get("course")
    if not isinstance(query, str):
        return None
    courses = repository.match_courses(query)
    return courses[0].code if len(courses) == 1 else None


def matches(
    repository: CatalogRepository, call: ToolCallRecord, expected: ExpectedCall
) -> bool:
    if call.name != expected.name or not call.ok:
        return False
    if expected.course and resolved_course(repository, call) != expected.course:
        return False
    return not expected.term or call.arguments.get("term") == expected.term


def detect_language(text: str) -> str:
    arabic = len(ARABIC_LETTER.findall(text))
    return "ar" if arabic > len(LATIN_LETTER.findall(text)) / 2 else "en"


def normalize(text: str) -> str:
    return text.translate(NORMALIZE).casefold()


def score(
    repository: CatalogRepository, case: EvalCase, outcome: AgentResult | str
) -> dict[str, bool]:
    checks = ["tools", "precision", "language"]
    if any(expected.course or expected.term for expected in case.expected_calls):
        checks.insert(1, "arguments")
    if case.facts:
        checks.append("facts")
    if case.forbidden:
        checks.append("no_leak")
    if case.guess_forbidden:
        checks.append("no_guess")
    if not isinstance(outcome, AgentResult):
        return dict.fromkeys(checks, False)

    called = {call.name for call in outcome.tool_calls}
    allowed = {call.name for call in case.expected_calls} | set(case.allowed_tools)
    reply = normalize(outcome.reply)
    guessed = {
        resolved_course(repository, call) for call in outcome.tool_calls if call.ok
    }
    results = {
        "tools": all(call.name in called for call in case.expected_calls),
        "arguments": all(
            any(matches(repository, call, expected) for call in outcome.tool_calls)
            for expected in case.expected_calls
        ),
        "precision": called <= allowed,
        "language": detect_language(outcome.reply) == case.language,
        "facts": all(
            any(normalize(option) in reply for option in group) for group in case.facts
        ),
        "no_leak": not any(normalize(word) in reply for word in case.forbidden),
        "no_guess": not guessed & set(case.guess_forbidden),
    }
    return {check: results[check] for check in checks}


def describe(outcome: AgentResult | str) -> str:
    if not isinstance(outcome, AgentResult):
        return outcome
    calls = [
        f"{c.name}({c.arguments}){'' if c.ok else '!'}" for c in outcome.tool_calls
    ]
    reply = " ".join(outcome.reply.split())
    return f"steps={outcome.steps} calls={calls} reply={reply[:200]!r}"


async def main() -> None:
    cases = load_cases()
    settings = get_settings().model_copy(
        update={"llm_max_retries": MAX_RETRIES, "today_override": EVAL_DATE}
    )
    client = LLMClient(settings)
    repository = CatalogRepository.from_file(settings.catalog_path)
    service = AdvisorService(client, repository, settings)
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def run(case: EvalCase) -> tuple[EvalCase, AgentResult | str]:
        async with semaphore:
            return case, await predict(service, case)

    try:
        results = await asyncio.gather(
            *(run(case) for case in cases for _ in range(REPEATS))
        )
    finally:
        await client.close()

    passed: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    steps = []
    for case, outcome in results:
        if isinstance(outcome, AgentResult):
            steps.append(outcome.steps)
        for check, ok in score(repository, case, outcome).items():
            totals[check] += 1
            passed[check] += ok
            if not ok:
                print(f"[{case.id}] {check} failed: {describe(outcome)}")

    print(f"\n{len(cases)} cases x {REPEATS} runs")
    print(f"errors     {len(results) - len(steps)}/{len(results)}")
    if steps:
        print(f"avg steps  {sum(steps) / len(steps):.1f}")
    for check, total in totals.items():
        print(f"{check:<10} {passed[check]}/{total}  {passed[check] / total:.0%}")


if __name__ == "__main__":
    asyncio.run(main())
