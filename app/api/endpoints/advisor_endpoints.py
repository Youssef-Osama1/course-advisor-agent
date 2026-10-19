from fastapi import APIRouter

from app.api.dependencies import AdvisorServiceDep
from app.api.schemas.advisor import AdviseRequest
from app.services.agent import AgentResult

router = APIRouter()


@router.post("")
async def advise(payload: AdviseRequest, service: AdvisorServiceDep) -> AgentResult:
    return await service.answer(payload.message, payload.student_id)
