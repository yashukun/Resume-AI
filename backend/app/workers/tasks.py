import asyncio
import hashlib
from celery import shared_task
from app.workers.celery_app import celery_app
from app.services.storage import storage_service
from app.services.resume_parser import resume_parser
from app.services.ai_service import ai_service, ResumeExtractionError, PreflightError
from app.services.ats_engine import ats_engine
from app.services.resume_optimizer import resume_optimizer
from app.services.docx_generator import docx_generator
from app.services.pdf_converter import pdf_converter
from app.core.database import get_task_session
from app.models.job import Job, JobStatus
from app.models.resume import Resume
from app.models.user_resume import UserResume
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
    except PreflightError as e:
        # Environment is broken (Ollama down / model missing). Retrying
        # will hit the same wall — fail immediately with the actionable
        # error so the user sees `Run \`ollama pull X\`` instead of
        # watching PARSING spin for an hour.
        logger.error(f"Preflight failed for job {job_id}: {e}")
        run_async(_update_job_status(job_id, JobStatus.FAILED, str(e)))
        return
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
    # Verify Ollama + required models BEFORE doing any work. This turns
    # a 20-minute timeout-and-retry loop into an immediate, actionable
    # error if the LLM dependency isn't running.
    await ai_service.preflight()

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

        # ── Library lookup: skip parsing if we've already parsed this
        # exact file before. Job.user_resume_id may be pre-set by the
        # "from existing" endpoint, in which case we trust it directly;
        # otherwise we look up by content hash. ─────────────────────────
        library_entry: UserResume | None = None

        if job.user_resume_id:
            lib_result = await session.execute(
                select(UserResume).where(UserResume.id == job.user_resume_id)
            )
            library_entry = lib_result.scalar_one_or_none()

        # Download the file (we need bytes either for parsing or for
        # hashing — only skip the download if we already have a fully
        # parsed library entry).
        file_path = job.original_file_path.replace(
            f"{storage_service.bucket}/", "")

        if library_entry and library_entry.user_details:
            # Trust the linked library entry — skip download + parse.
            raw_text = library_entry.raw_text
            user_details = library_entry.user_details
            logger.info(
                f"Reusing parsed library entry {library_entry.id} for job "
                f"{job_id} — skipping parse"
            )
        else:
            file_data = await storage_service.download_file(file_path)
            file_hash = hashlib.sha256(file_data).hexdigest()

            # Hash-based lookup (catches uploads that weren't routed
            # through the library picker but happen to be identical).
            if library_entry is None:
                hash_result = await session.execute(
                    select(UserResume).where(UserResume.file_hash == file_hash)
                )
                library_entry = hash_result.scalar_one_or_none()

            if library_entry and library_entry.user_details:
                raw_text = library_entry.raw_text
                user_details = library_entry.user_details
                job.user_resume_id = library_entry.id
                logger.info(
                    f"Hash-matched library entry {library_entry.id} for job "
                    f"{job_id} — skipping parse"
                )
            else:
                # Actually parse — this is the expensive path.
                parsed_data = await resume_parser.parse_file(
                    file_data, job.file_type
                )
                raw_text = parsed_data.pop("raw_text", None)
                user_details = parsed_data

                if library_entry is None:
                    library_entry = UserResume(
                        file_hash=file_hash,
                        original_filename=job.original_filename,
                        original_file_path=job.original_file_path,
                        file_type=job.file_type,
                        raw_text=raw_text,
                        user_details=user_details,
                    )
                    session.add(library_entry)
                    await session.flush()  # populate library_entry.id
                else:
                    # Row existed but had no parsed data — backfill it.
                    library_entry.raw_text = raw_text
                    library_entry.user_details = user_details

                job.user_resume_id = library_entry.id

        # Create resume record (per-job snapshot of parsed data; the
        # downstream optimizer mutates this row's optimized_* fields).
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
    except PreflightError as e:
        # Same fast-fail logic as process_resume — see comment there.
        logger.error(f"Preflight failed for optimize job {job_id}: {e}")
        run_async(_update_job_status(job_id, JobStatus.FAILED, str(e)))
        return
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
    # Same fast-fail preflight as the parse task. Optimization runs ~8
    # LLM calls — burning 30+ minutes on retries when Ollama is down is
    # the worst possible UX.
    await ai_service.preflight()

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

        # ── Step 2: Deterministic ATS scoring — BEFORE optimization ──
        ats_before = ats_engine.score(resume_data, jd_data)
        logger.info(
            f"ATS score BEFORE: {ats_before['overall_score']}/100 for job {job_id}"
        )

        # ── Step 3: Build optimized resume JSON (LLM + logic) ────────
        # This creates a BRAND NEW JSON — original user_details is untouched
        optimized_data = await resume_optimizer.optimize(
            resume_data, jd_data, ats_before
        )

        # ── Step 3b: Re-score on the OPTIMIZED resume ────────────────
        # Validates that the rewrite actually improved keyword/skill match.
        # If the score went DOWN, that's a signal something went wrong —
        # we still ship (no LLM is perfect), but we log it loudly.
        ats_after = ats_engine.score(optimized_data, jd_data)
        delta = ats_after["overall_score"] - ats_before["overall_score"]
        logger.info(
            f"ATS score AFTER: {ats_after['overall_score']}/100 "
            f"(delta: {'+' if delta >= 0 else ''}{delta}) for job {job_id}"
        )
        if delta < 0:
            logger.warning(
                f"ATS score DECREASED after optimization for job {job_id} "
                f"(before={ats_before['overall_score']}, "
                f"after={ats_after['overall_score']}). "
                f"Investigate prompts or fall-through logic."
            )

        # Persist both scores. ats_score now contains the full picture:
        # - root: current (post-optimization) score + breakdown
        # - "before": pre-optimization snapshot
        # - "delta": after - before (positive = improved)
        # - "gap_analysis": missing skills the candidate could consider
        #                    adding (surfaced in UI, NOT in the resume DOCX)
        # The frontend already pulls `ats_score` via /jobs/{id}/resume,
        # so this avoids any schema migration.
        opt_meta = optimized_data.get("optimization_metadata") or {}
        resume.ats_score = {
            **ats_after,
            "before": ats_before,
            "delta": delta,
            "gap_analysis": opt_meta.get("gap_analysis") or {
                "missing_required": [],
                "missing_preferred": [],
            },
        }
        resume.keyword_matches = ats_after.get("matching_keywords", [])
        resume.missing_keywords = ats_after.get("missing_keywords", [])

        # Store optimized pieces in their dedicated DB columns
        resume.optimized_summary = optimized_data.get("summary")
        resume.optimized_experience = optimized_data.get("experience")
        resume.optimized_skills = optimized_data.get("skills")

        # Stamp ats_score_after into the optimization_metadata too —
        # convenient for the frontend to read alongside ats_score_before.
        if optimized_data.get("optimization_metadata"):
            optimized_data["optimization_metadata"]["ats_score_after"] = (
                ats_after["overall_score"]
            )
            optimized_data["optimization_metadata"]["ats_score_delta"] = delta

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

        # ── Done — mark COMPLETED now so the user can download DOCX ──
        # immediately. PDF conversion is fired as a follow-up task; if
        # the user clicks PDF before it finishes, the download endpoint
        # 404s and the UI shows a friendly retry message.
        job.status = JobStatus.COMPLETED
        from datetime import datetime
        job.completed_at = datetime.utcnow()
        await session.commit()
        logger.info(f"Resume optimization completed for job: {job_id}")

        # Fire-and-forget — runs in a separate worker slot so the user
        # is unblocked the moment the DOCX is ready.
        if pdf_converter.is_available():
            generate_pdf.delay(job_id)
        else:
            logger.info("LibreOffice not available — skipping PDF conversion")


@celery_app.task(bind=True, max_retries=2)
def generate_pdf(self, job_id: str):
    """
    Convert the job's optimized DOCX to PDF and upload it.

    Runs AFTER the job has been marked COMPLETED so users can grab the
    DOCX without waiting on LibreOffice cold-start (~3-10s). The PDF
    becomes available a few seconds later — the download endpoint
    handles "not yet" with a 404 which the UI translates to a friendly
    "PDF may not be available" toast.
    """
    logger.info(f"Generating PDF for job: {job_id}")
    try:
        run_async(_generate_pdf_async(job_id))
    except Exception as e:
        logger.error(f"PDF generation failed for {job_id}: {e}")
        raise self.retry(exc=e, countdown=20)


async def _generate_pdf_async(job_id: str):
    docx_object = f"generated/{job_id}/optimized_resume.docx"
    try:
        docx_bytes = await storage_service.download_file(docx_object)
    except Exception as e:
        logger.error(
            f"PDF generation: could not fetch DOCX for {job_id}: {e}"
        )
        return

    pdf_bytes = pdf_converter.convert(docx_bytes)
    if not pdf_bytes:
        logger.warning(f"PDF conversion returned empty for {job_id}")
        return

    pdf_object = f"generated/{job_id}/optimized_resume.pdf"
    await storage_service.upload_file(
        pdf_bytes,
        pdf_object,
        content_type="application/pdf",
    )
    logger.info(f"PDF uploaded for job {job_id}")


@celery_app.task(bind=True, max_retries=3)
def parse_user_resume(self, user_resume_id: str):
    """
    Parse a library resume that was uploaded without an associated job.

    Idempotent: if the row already has user_details, this is a no-op.
    """
    logger.info(f"Parsing library resume: {user_resume_id}")
    try:
        run_async(_parse_user_resume_async(user_resume_id))
    except PreflightError as e:
        logger.error(
            f"Preflight failed for library resume {user_resume_id}: {e}"
        )
        # No job to mark FAILED — just give up. Next attempt to use this
        # resume in a job will retry via the regular hash-lookup path.
        return
    except Exception as e:
        logger.error(f"Error parsing library resume: {e}")
        raise self.retry(exc=e, countdown=30)


async def _parse_user_resume_async(user_resume_id: str):
    await ai_service.preflight()

    async with get_task_session() as session:
        result = await session.execute(
            select(UserResume).where(UserResume.id == user_resume_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            logger.warning(f"UserResume not found: {user_resume_id}")
            return
        if row.user_details:
            logger.info(
                f"Library resume {user_resume_id} already parsed — skipping"
            )
            return

        file_path = row.original_file_path.replace(
            f"{storage_service.bucket}/", ""
        )
        file_data = await storage_service.download_file(file_path)
        parsed = await resume_parser.parse_file(file_data, row.file_type)
        row.raw_text = parsed.pop("raw_text", None)
        row.user_details = parsed
        await session.commit()
        logger.info(f"Library resume parsed: {user_resume_id}")


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
