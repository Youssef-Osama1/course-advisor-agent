from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config.settings import get_settings
from app.core.exceptions import (
    AgentStepLimitError,
    LLMOutputError,
    StudentNotFoundError,
)
from app.core.logger import setup_logging
from app.repositories.catalog_repository import CatalogRepository
from app.services.llm_client import LLMClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    app.state.catalog_repository = CatalogRepository.from_file(settings.catalog_path)
    app.state.llm_client = LLMClient(settings)
    yield
    await app.state.llm_client.close()


app = FastAPI(title="Course Advisor Agent", lifespan=lifespan)
app.include_router(api_router)


@app.exception_handler(LLMOutputError)
@app.exception_handler(AgentStepLimitError)
async def handle_model_failure(
    request: Request, error: LLMOutputError | AgentStepLimitError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(error)}
    )


@app.exception_handler(StudentNotFoundError)
async def handle_student_not_found(
    request: Request, error: StudentNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)}
    )
