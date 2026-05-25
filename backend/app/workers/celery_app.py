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
    # ── Time limits ──────────────────────────────────────────────────
    # CPU-only Ollama inference (Docker on Mac has no Metal/GPU access)
    # is SLOW — a single 4K-token generation of a 3B model can take
    # 10-15 minutes. Old limits (540s soft / 600s hard) killed tasks
    # mid-inference and triggered an endless retry loop.
    # New limits give enough headroom for the worst case while still
    # bounded so genuinely stuck workers eventually die.
    task_time_limit=1800,       # 30 min hard kill
    task_soft_time_limit=1500,  # 25 min soft warn
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
    Pre-load BOTH the fast and general models into Ollama memory on
    worker startup. The fast model handles resume/JD extraction; the
    general model handles the optimizer rewrites. Without warming the
    general model, the first optimize job pays a 10-20s cold-load
    penalty before its first LLM call even starts streaming.
    """
    models_to_warm = [
        settings.ollama_model_fast,
        settings.ollama_model_general,
    ]
    for model in models_to_warm:
        try:
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
                timeout=120.0,
            )
            if response.status_code == 200:
                logger.info(f"Model {model} pre-warmed successfully")
            else:
                logger.warning(
                    f"Pre-warm of {model} returned {response.status_code}"
                )
        except Exception as e:
            logger.warning(f"Pre-warm of {model} failed (non-fatal): {e}")
