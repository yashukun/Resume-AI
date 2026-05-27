from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query, Header
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.config import settings
from app.models.job import Job, JobStatus
from app.models.resume import Resume
from app.models.user_resume import UserResume
from app.schemas import (
    JobResponse,
    JobStatusResponse,
    UploadResponse,
    ResumeResponse,
    JobFromExistingRequest,
)
from app.services.storage import storage_service
from app.workers.tasks import process_resume
import uuid
import hashlib
from typing import List, Optional
import os
import io

router = APIRouter(prefix="/upload", tags=["Upload"])


@router.post("/resume", response_model=UploadResponse)
async def upload_resume(
    file: UploadFile = File(..., description="Resume file (PDF or DOCX)"),
    job_description: str = Form(..., min_length=50,
                                description="Job description text"),
    job_title: str = Form(None, description="Job title (optional)"),
    company_name: str = Form(None, description="Company name (optional)"),
    db: AsyncSession = Depends(get_db),
    x_device_id: Optional[str] = Header(default=None),
):
    """
    Upload a resume file and job description for processing.

    - **file**: Resume in PDF or DOCX format (max 10MB)
    - **job_description**: The target job description text
    - **job_title**: Optional job title
    - **company_name**: Optional company name

    Returns a job ID that can be used to track processing status.
    """
    # Validate file extension
    filename = file.filename or "unknown"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in settings.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(settings.allowed_extensions)}"
        )

    # Read file content
    content = await file.read()

    # Validate file size
    if len(content) > settings.max_upload_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {settings.max_upload_size // (1024*1024)}MB"
        )

    # Library lookup: if we've seen this exact file before, link the job
    # to the existing library entry and skip re-uploading bytes to MinIO.
    file_hash = hashlib.sha256(content).hexdigest()
    file_type = ext.replace(".", "")
    job_id = uuid.uuid4()
    content_type = (
        "application/pdf" if ext == ".pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    existing_q = await db.execute(
        select(UserResume).where(UserResume.file_hash == file_hash)
    )
    library_entry = existing_q.scalar_one_or_none()
    reused_existing_parse = bool(
        library_entry and library_entry.user_details
    )

    if library_entry:
        file_path = library_entry.original_file_path
    else:
        storage_filename = f"library/{uuid.uuid4()}/{filename}"
        try:
            file_path = await storage_service.upload_file(
                content, storage_filename, content_type
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to upload file: {str(e)}",
            )
        library_entry = UserResume(
            file_hash=file_hash,
            device_id=x_device_id,
            original_filename=filename,
            original_file_path=file_path,
            file_type=file_type,
        )
        db.add(library_entry)
        await db.flush()  # populate library_entry.id

    # Create job record linked to the library entry
    job = Job(
        id=job_id,
        user_resume_id=library_entry.id,
        original_filename=filename,
        original_file_path=file_path,
        file_type=file_type,
        job_description=job_description,
        job_title=job_title,
        company_name=company_name,
        status=JobStatus.PENDING,
    )

    db.add(job)
    await db.commit()

    # Queue processing task
    process_resume.delay(str(job_id))

    return UploadResponse(
        job_id=job_id,
        user_resume_id=library_entry.id,
        message=(
            "Reusing previously parsed resume. Optimization starting."
            if reused_existing_parse
            else "Resume uploaded successfully. Processing started."
        ),
        status=JobStatus.PENDING,
        reused_existing_parse=reused_existing_parse,
    )


@router.post("/resume/from-existing", response_model=UploadResponse)
async def create_job_from_existing_resume(
    payload: JobFromExistingRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new optimization job using a resume already in the library.

    No file upload — the parsed data is reused, so processing jumps
    straight past the parse step into optimization.
    """
    lib_q = await db.execute(
        select(UserResume).where(UserResume.id == payload.user_resume_id)
    )
    library_entry = lib_q.scalar_one_or_none()
    if not library_entry:
        raise HTTPException(
            status_code=404, detail="Resume not found in library"
        )

    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        user_resume_id=library_entry.id,
        original_filename=library_entry.original_filename,
        original_file_path=library_entry.original_file_path,
        file_type=library_entry.file_type,
        job_description=payload.job_description,
        job_title=payload.job_title,
        company_name=payload.company_name,
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.commit()

    process_resume.delay(str(job_id))

    return UploadResponse(
        job_id=job_id,
        user_resume_id=library_entry.id,
        message=(
            "Reusing previously parsed resume. Optimization starting."
            if library_entry.user_details
            else "Resume queued — parsing required, then optimizing."
        ),
        status=JobStatus.PENDING,
        reused_existing_parse=bool(library_entry.user_details),
    )


@router.get("/jobs", response_model=List[JobResponse])
async def list_jobs(
    limit: int = 10,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List all processing jobs."""
    result = await db.execute(
        select(Job).order_by(Job.created_at.desc()).limit(limit).offset(offset)
    )
    jobs = result.scalars().all()
    return jobs


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get details of a specific job."""
    result = await db.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job


@router.get("/jobs/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get the processing status of a job."""
    result = await db.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    progress_messages = {
        JobStatus.PENDING: "Job queued for processing",
        JobStatus.PARSING: "Parsing resume content — this may take a minute",
        JobStatus.PROCESSING: "Extracting structured data",
        JobStatus.OPTIMIZING: "AI optimization in progress — enhancing your resume",
        JobStatus.COMPLETED: "Processing complete",
        JobStatus.FAILED: "Processing failed",
    }

    # If the job has a transient error_message (retry info), show it
    # instead of the default progress message — gives user visibility.
    progress = progress_messages.get(job.status, "")
    if (
        job.error_message
        and job.status not in (JobStatus.FAILED, JobStatus.COMPLETED)
    ):
        progress = job.error_message

    return JobStatusResponse(
        id=job.id,
        status=job.status,
        progress_message=progress,
        error_message=job.error_message if job.status == JobStatus.FAILED else None,
    )


@router.get("/jobs/{job_id}/resume", response_model=ResumeResponse)
async def get_parsed_resume(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get the parsed resume data for a job."""
    result = await db.execute(
        select(Resume).where(Resume.job_id == job_id)
    )
    resume = result.scalar_one_or_none()

    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    return resume


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a job and its associated data."""
    result = await db.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Delete resume if exists
    resume_result = await db.execute(
        select(Resume).where(Resume.job_id == job_id)
    )
    resume = resume_result.scalar_one_or_none()
    if resume:
        await db.delete(resume)

    # Delete only the generated outputs for this job. The original
    # upload bytes are owned by the UserResume library entry and may
    # be shared with other jobs — deleting it here would break them.
    for suffix in ("optimized_resume.docx", "optimized_resume.pdf"):
        try:
            await storage_service.delete_file(
                f"generated/{job_id}/{suffix}"
            )
        except Exception:
            pass

    await db.delete(job)
    await db.commit()

    return {"message": "Job deleted successfully"}


@router.get("/jobs/{job_id}/download")
async def download_optimized_resume(
    job_id: uuid.UUID,
    format: Optional[str] = Query("docx", regex="^(docx|pdf)$"),
    db: AsyncSession = Depends(get_db),
):
    """
    Download the generated optimized resume file.

    - **format**: "docx" (default) or "pdf"

    Returns:
        - If format=docx → presigned URL for the DOCX file
        - If format=pdf  → presigned URL for the PDF file (if available)
    """
    result = await db.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Job not completed yet. Current status: {job.status.value}"
        )

    if not job.optimized_file_path:
        raise HTTPException(
            status_code=404,
            detail="No optimized file generated for this job"
        )

    # Determine object path based on format
    base_object = f"generated/{job_id}/optimized_resume"

    if format == "pdf":
        object_name = f"{base_object}.pdf"
        content_type = "application/pdf"
        filename = "optimized_resume.pdf"
    else:
        object_name = f"{base_object}.docx"
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        filename = "optimized_resume.docx"

    # Stream file directly through the backend (avoids internal Docker
    # hostnames like minio:9000 leaking into presigned URLs)
    try:
        file_data = await storage_service.download_file(object_name)
        return StreamingResponse(
            io.BytesIO(file_data),
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"File not found in storage: {format} format may not be available"
        )
