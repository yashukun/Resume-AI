from fastapi import APIRouter
from app.api.upload import router as upload_router
from app.api.health import router as health_router
from app.api.resumes import router as resumes_router
from app.api.extension import router as extension_router

api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(upload_router)
api_router.include_router(resumes_router)
api_router.include_router(extension_router)
