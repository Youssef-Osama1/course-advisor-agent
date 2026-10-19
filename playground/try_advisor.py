import asyncio
from datetime import date

from app.config.settings import get_settings
from app.core.logger import setup_logging
from app.repositories.catalog_repository import CatalogRepository
from app.services.advisor_service import AdvisorService
from app.services.llm_client import LLMClient

CASES = [
    ("S1002", "ينفع أسجّل Machine Learning الترم الجاي؟ وفيه سكاشن إمتى؟"),
    ("S1003", "Can I take Machine Learning next term?"),
    ("S1001", "I want to register for learning next term."),
    ("S1004", "أنا باخد إيه الترم ده؟"),
]
PLAYGROUND_DATE = date(2026, 10, 19)
SECONDS_BETWEEN_CASES = 15


async def main() -> None:
    settings = get_settings().model_copy(update={"today_override": PLAYGROUND_DATE})
    setup_logging(settings.log_level)
    llm_client = LLMClient(settings)
    repository = CatalogRepository.from_file(settings.catalog_path)
    service = AdvisorService(llm_client, repository, settings)
    try:
        for index, (student_id, message) in enumerate(CASES):
            if index:
                await asyncio.sleep(SECONDS_BETWEEN_CASES)
            result = await service.answer(message, student_id)
            print(f"\n{student_id}: {message}")
            print(result.model_dump_json(indent=2))
    finally:
        await llm_client.close()


asyncio.run(main())
