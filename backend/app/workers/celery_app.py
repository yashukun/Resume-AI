from celery import Celery
from celery.signals import worker_ready
from app.core.config import settings
import httpx
import logging

logger = logging.getLogger(__name__)

# Create Celery app
celery_app = Celery(
    "resume_ai",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"]
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,  # 10 minutes max per task
    task_soft_time_limit=540,  # Soft limit 9 minutes
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# Task routes (optional, for scaling)
celery_app.conf.task_routes = {
    "app.workers.tasks.process_resume": {"queue": "resume_processing"},
    "app.workers.tasks.optimize_resume": {"queue": "ai_optimization"},
}


@worker_ready.connect
def warm_up_model(sender, **kwargs):
    """
    Pre-load the fast model into Ollama memory on worker startup.
    This avoids a 10-20s cold-start on the first request.
    """
    try:
        model = settings.ollama_model_fast
        logger.info(f"Pre-warming Ollama model: {model}")
        response = httpx.post(
            f"{settings.ollama_base_url}/api/generate",
            json={
                "model": model,
                "prompt": "hi",
                "stream": False,
                "keep_alive": "30m",
                "options": {"num_predict": 1},
            },
            timeout=60.0,
        )
        if response.status_code == 200:
            logger.info(f"Model {model} pre-warmed successfully")
        else:
            logger.warning(f"Model pre-warm returned {response.status_code}")
    except Exception as e:
        logger.warning(f"Model pre-warm failed (non-fatal): {e}")
