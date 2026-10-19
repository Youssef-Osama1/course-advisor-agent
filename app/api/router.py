from fastapi import APIRouter

from app.api.endpoints import advisor_endpoints, health_endpoints

api_router = APIRouter()
api_router.include_router(health_endpoints.router, tags=["health"])
api_router.include_router(advisor_endpoints.router, prefix="/advise", tags=["advise"])
