from fastapi import APIRouter
from app.schemas import HealthCheck
from app.services.ai_service import ai_service
from app.core.config import settings
import redis

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthCheck)
async def health_check():
    """
    Health check endpoint.

    Returns the status of all services.
    """
    services = {}

    # Check Redis
    try:
        r = redis.from_url(settings.redis_url)
        r.ping()
        services["redis"] = "healthy"
    except Exception:
        services["redis"] = "unhealthy"

    # Check Ollama
    try:
        if await ai_service.health_check():
            services["ollama"] = "healthy"
        else:
            services["ollama"] = "unhealthy"
    except Exception:
        services["ollama"] = "unhealthy"

    # Check MinIO
    from app.services.storage import storage_service
    try:
        storage_service.client.bucket_exists(settings.minio_bucket)
        services["minio"] = "healthy"
    except Exception:
        services["minio"] = "unhealthy"

    # Overall status
    overall = "healthy" if all(
        s == "healthy" for s in services.values()) else "degraded"

    return HealthCheck(
        status=overall,
        version="1.0.0",
        services=services,
    )


@router.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "docs": "/docs",
    }
