from typing import Annotated

from fastapi import Depends, Request

from app.config.settings import Settings, get_settings
from app.repositories.catalog_repository import CatalogRepository
from app.services.advisor_service import AdvisorService
from app.services.llm_client import LLMClient


def get_llm_client(request: Request) -> LLMClient:
    return request.app.state.llm_client


LLMClientDep = Annotated[LLMClient, Depends(get_llm_client)]


def get_catalog_repository(request: Request) -> CatalogRepository:
    return request.app.state.catalog_repository


CatalogRepositoryDep = Annotated[CatalogRepository, Depends(get_catalog_repository)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_advisor_service(
    llm_client: LLMClientDep, repository: CatalogRepositoryDep, settings: SettingsDep
) -> AdvisorService:
    return AdvisorService(llm_client, repository, settings)


AdvisorServiceDep = Annotated[AdvisorService, Depends(get_advisor_service)]
