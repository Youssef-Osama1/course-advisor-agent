import logging

from app.config.settings import Settings
from app.core.exceptions import StudentNotFoundError
from app.prompts.advisor import (
    ADVISOR_SYSTEM_PROMPT,
    CHECK_ELIGIBILITY_DESCRIPTION,
    GET_COURSE_DESCRIPTION,
    GET_MY_RECORD_DESCRIPTION,
    LIST_SECTIONS_DESCRIPTION,
)
from app.repositories.catalog_repository import CatalogRepository
from app.services.agent import AgentResult, Tool, ToolRegistry, run_agent
from app.services.llm_client import LLMClient
from app.tools.courses import (
    CheckEligibilityArgs,
    CourseTools,
    GetCourseArgs,
    GetMyRecordArgs,
    ListSectionsArgs,
)

logger = logging.getLogger(__name__)


class AdvisorService:
    def __init__(
        self, llm_client: LLMClient, repository: CatalogRepository, settings: Settings
    ) -> None:
        self._llm_client = llm_client
        self._repository = repository
        self._settings = settings

    async def answer(self, message: str, student_id: str) -> AgentResult:
        student = self._repository.find_student(student_id)
        if student is None:
            raise StudentNotFoundError(f"Student {student_id} was not found")
        tools = CourseTools(self._repository, student, self._settings.current_date())
        result = await run_agent(
            llm_client=self._llm_client,
            registry=build_registry(tools),
            system=ADVISOR_SYSTEM_PROMPT,
            message=message,
            max_steps=self._settings.agent_max_steps,
        )
        logger.info(
            "Answered advising message: steps=%s tool_calls=%s failed_calls=%s",
            result.steps,
            len(result.tool_calls),
            sum(not call.ok for call in result.tool_calls),
        )
        return result


def build_registry(tools: CourseTools) -> ToolRegistry:
    return ToolRegistry(
        [
            Tool("get_course", GET_COURSE_DESCRIPTION, GetCourseArgs, tools.get_course),
            Tool(
                "check_eligibility",
                CHECK_ELIGIBILITY_DESCRIPTION,
                CheckEligibilityArgs,
                tools.check_eligibility,
            ),
            Tool(
                "list_sections",
                LIST_SECTIONS_DESCRIPTION,
                ListSectionsArgs,
                tools.list_sections,
            ),
            Tool(
                "get_my_record",
                GET_MY_RECORD_DESCRIPTION,
                GetMyRecordArgs,
                tools.get_my_record,
            ),
        ]
    )
