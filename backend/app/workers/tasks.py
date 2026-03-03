import asyncio
from celery import shared_task
from app.workers.celery_app import celery_app
from app.services.storage import storage_service
from app.services.resume_parser import resume_parser
from app.services.ai_service import ai_service, ResumeExtractionError
from app.services.ats_engine import ats_engine
from app.services.resume_optimizer import resume_optimizer
from app.services.docx_generator import docx_generator
from app.services.pdf_converter import pdf_converter
from app.core.database import get_task_session
from app.models.job import Job, JobStatus
from app.models.resume import Resume
from sqlalchemy import select
import logging

logger = logging.getLogger(__name__)


def run_async(coro):
    """Helper to run async functions in sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, max_retries=3)
def process_resume(self, job_id: str):
    """
    Process a resume: parse and extract data.

    Args:
        job_id: UUID of the job to process
    """
    attempt = self.request.retries + 1
    max_attempts = self.max_retries + 1
    logger.info(
        f"Starting resume processing for job: {job_id} "
        f"(attempt {attempt}/{max_attempts})")

    try:
        # Clear any retry message from previous attempt
        if attempt > 1:
            run_async(_update_job_status(
                job_id, JobStatus.PARSING,
                error_message=None,
                progress_hint=f"Retry {attempt}/{max_attempts}",
            ))
        run_async(_process_resume_async(job_id))
    except Exception as e:
        logger.error(
            f"Error processing resume (attempt {attempt}): {e}")
        try:
            retry_msg = (
                f"Attempt {attempt}/{max_attempts} failed — "
                f"retrying in 30s..."
            )
            run_async(_update_job_status(
                job_id, JobStatus.PARSING, error_message=retry_msg))
            raise self.retry(exc=e, countdown=30)
        except self.MaxRetriesExceededError:
            # All retries exhausted — permanent failure
            logger.error(
                f"All retries exhausted for job {job_id}: {e}")
            run_async(_update_job_status(
                job_id, JobStatus.FAILED, str(e)))
            raise


async def _process_resume_async(job_id: str):
    """Async implementation of resume processing."""
    async with get_task_session() as session:
        # Get the job
        result = await session.execute(
            select(Job).where(Job.id == job_id)
        )
        job = result.scalar_one_or_none()

        if not job:
            raise ValueError(f"Job not found: {job_id}")

        # Update status to parsing
        job.status = JobStatus.PARSING
        await session.commit()

        # Download file from storage
        file_path = job.original_file_path.replace(
            f"{storage_service.bucket}/", "")
        file_data = await storage_service.download_file(file_path)

        # Parse the resume
        parsed_data = await resume_parser.parse_file(file_data, job.file_type)

        # Separate raw_text from structured data
        raw_text = parsed_data.pop("raw_text", None)

        # Store the entire AI-extracted JSON as user_details
        # Format: {name, contact: {email, phone, linkedin, github, portfolio, ...},
        #          extracted_links: {linkedin: [...], github: [...], ...},
        #          sections: [{title, content/items}, ...]}
        user_details = parsed_data

        # Create resume record with full JSON in one column
        resume = Resume(
            job_id=job.id,
            raw_text=raw_text,
            user_details=user_details,
        )
        session.add(resume)

        # Update job status
        job.status = JobStatus.PROCESSING
        await session.commit()

        logger.info(f"Resume parsed successfully for job: {job_id}")

        # Trigger optimization task
        optimize_resume.delay(job_id, str(resume.id))


@celery_app.task(bind=True, max_retries=3)
def optimize_resume(self, job_id: str, resume_id: str):
    """
    Optimize resume using AI.

    Args:
        job_id: UUID of the job
        resume_id: UUID of the resume record
    """
    attempt = self.request.retries + 1
    max_attempts = self.max_retries + 1
    logger.info(
        f"Starting resume optimization for job: {job_id} "
        f"(attempt {attempt}/{max_attempts})")

    try:
        if attempt > 1:
            run_async(_update_job_status(
                job_id, JobStatus.OPTIMIZING,
                error_message=None,
                progress_hint=f"Retry {attempt}/{max_attempts}",
            ))
        run_async(_optimize_resume_async(job_id, resume_id))
    except Exception as e:
        logger.error(
            f"Error optimizing resume (attempt {attempt}): {e}")
        try:
            retry_msg = (
                f"Attempt {attempt}/{max_attempts} failed — "
                f"retrying in 30s..."
            )
            run_async(_update_job_status(
                job_id, JobStatus.OPTIMIZING, error_message=retry_msg))
            raise self.retry(exc=e, countdown=30)
        except self.MaxRetriesExceededError:
            logger.error(
                f"All retries exhausted for optimization job {job_id}: {e}")
            run_async(_update_job_status(
                job_id, JobStatus.FAILED, str(e)))
            raise


async def _optimize_resume_async(job_id: str, resume_id: str):
    """
    Async implementation of resume optimization.

    Pipeline:
      Step 1 — Parse JD (LLM)
      Step 2 — Deterministic ATS scoring
      Step 3 — Build optimized resume JSON (LLM + logic)
      Step 4 — Generate DOCX from optimized JSON
      Step 5 — Convert DOCX → PDF (optional, if LibreOffice available)
      Step 6 — Upload generated files to MinIO
    """
    async with get_task_session() as session:
        # Get job and resume
        job_result = await session.execute(
            select(Job).where(Job.id == job_id)
        )
        job = job_result.scalar_one_or_none()

        resume_result = await session.execute(
            select(Resume).where(Resume.id == resume_id)
        )
        resume = resume_result.scalar_one_or_none()

        if not job or not resume:
            raise ValueError("Job or Resume not found")

        # Update status
        job.status = JobStatus.OPTIMIZING
        await session.commit()

        resume_data = resume.user_details or {}

        # ── Step 1: Parse JD (uses LLM — needed for structured extraction) ──
        ai_available = await ai_service.health_check()

        if ai_available:
            jd_data = await ai_service.extract_job_requirements(
                job.job_description
            )
            logger.info(
                f"JD parsed: title={jd_data.get('job_title')}, "
                f"required_skills={len(jd_data.get('required_skills', []))}, "
                f"keywords={len(jd_data.get('keywords', []))}"
            )

            # Backfill job-level fields from JD extraction
            if jd_data.get("job_title") and not job.job_title:
                job.job_title = jd_data["job_title"]
            if jd_data.get("company_name") and not job.company_name:
                job.company_name = jd_data["company_name"]
        else:
            logger.warning("AI service unavailable — using empty JD parse")
            jd_data = ai_service._normalize_jd_data({})

        # ── Step 2: Deterministic ATS scoring (no LLM!) ──────────────
        ats_result = ats_engine.score(resume_data, jd_data)
        resume.ats_score = ats_result
        resume.keyword_matches = ats_result.get("matching_keywords", [])
        resume.missing_keywords = ats_result.get("missing_keywords", [])

        logger.info(
            f"ATS score: {ats_result['overall_score']}/100 for job {job_id}"
        )

        # ── Step 3: Build optimized resume JSON (LLM + logic) ────────
        # This creates a BRAND NEW JSON — original user_details is untouched
        optimized_data = await resume_optimizer.optimize(
            resume_data, jd_data, ats_result
        )

        # Store optimized pieces in their dedicated DB columns
        resume.optimized_summary = optimized_data.get("summary")
        resume.optimized_experience = optimized_data.get("experience")
        resume.optimized_skills = optimized_data.get("skills")

        logger.info(f"Optimized resume built for job {job_id}")

        # ── Step 4: Generate DOCX from optimized JSON ────────────────
        docx_bytes = docx_generator.generate(optimized_data)

        # Upload DOCX to MinIO
        docx_object = f"generated/{job_id}/optimized_resume.docx"
        docx_path = await storage_service.upload_file(
            docx_bytes,
            docx_object,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        logger.info(f"DOCX uploaded: {docx_path}")

        # Store the primary output path (DOCX)
        job.optimized_file_path = docx_path

        # ── Step 5: Convert to PDF (optional) ────────────────────────
        if pdf_converter.is_available():
            pdf_bytes = pdf_converter.convert(docx_bytes)
            if pdf_bytes:
                pdf_object = f"generated/{job_id}/optimized_resume.pdf"
                pdf_path = await storage_service.upload_file(
                    pdf_bytes,
                    pdf_object,
                    content_type="application/pdf",
                )
                logger.info(f"PDF uploaded: {pdf_path}")
            else:
                logger.warning("PDF conversion returned empty — skipping")
        else:
            logger.info("LibreOffice not available — skipping PDF conversion")

        # ── Done ─────────────────────────────────────────────────────
        job.status = JobStatus.COMPLETED
        from datetime import datetime
        job.completed_at = datetime.utcnow()

        await session.commit()
        logger.info(f"Resume optimization completed for job: {job_id}")


async def _update_job_status(
    job_id: str,
    status: JobStatus,
    error_message: str = None,
    progress_hint: str = None,
):
    """Update job status and optional progress info."""
    async with get_task_session() as session:
        result = await session.execute(
            select(Job).where(Job.id == job_id)
        )
        job = result.scalar_one_or_none()
        if job:
            job.status = status
            # error_message=None explicitly clears it (e.g., on retry start)
            job.error_message = error_message
            await session.commit()
