from app.workers.celery_app import celery_app
from app.workers.tasks import process_resume, optimize_resume

__all__ = ["celery_app", "process_resume", "optimize_resume"]
