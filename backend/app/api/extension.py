"""
Browser extension API surface.

Single endpoint: accept a parsed JD blob from the extension's content
script (along with an existing UserResume id) and queue an optimization
job. The heavy lifting reuses the existing pipeline — this is just a
convenience wrapper so the extension doesn't have to mimic the multipart
form upload flow.
"""

from fastapi import APIRouter, HTTPException, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.user_resume import UserResume
from app.models.job import Job, JobStatus
from app.schemas import UploadResponse
from app.workers.tasks import process_resume
from pydantic import BaseModel, Field
from typing import Optional
import uuid

router = APIRouter(prefix="/extension", tags=["Extension"])


class ExtensionJobRequest(BaseModel):
    """Payload sent by the extension's popup when the user clicks Optimize."""

    user_resume_id: uuid.UUID
    jd_text: str = Field(
        ...,
        min_length=50,
        max_length=50_000,
        description="Raw JD text scraped from the page",
    )
    jd_url: Optional[str] = Field(
        default=None, max_length=2048,
        description="URL of the job posting (for display + 'Apply' link).",
    )
    job_title: Optional[str] = Field(default=None, max_length=255)
    company_name: Optional[str] = Field(default=None, max_length=255)


@router.post("/jobs", response_model=UploadResponse)
async def create_extension_job(
    payload: ExtensionJobRequest,
    db: AsyncSession = Depends(get_db),
    x_device_id: Optional[str] = Header(default=None),
):
    """
    Queue an optimization job from the extension.

    The user_resume_id MUST refer to a library entry owned by the same
    device (or a legacy NULL-device entry — useful while testing). The
    JD text is treated as untrusted input and stored verbatim on the Job
    row; the pipeline's existing LLM extraction handles title/company
    backfill if the extension didn't pull them off the page.
    """
    lib_q = await db.execute(
        select(UserResume).where(UserResume.id == payload.user_resume_id)
    )
    library_entry = lib_q.scalar_one_or_none()
    if not library_entry:
        raise HTTPException(
            status_code=404, detail="Resume not found in library"
        )

    # Enforce ownership: if a device header is sent, the resume must
    # belong to that device (or be NULL = shared). Without the header
    # we fall back to allowing only NULL-owned resumes — same scoping
    # rule as the list endpoint.
    if x_device_id:
        if library_entry.device_id not in (None, x_device_id):
            raise HTTPException(
                status_code=403,
                detail="This resume belongs to a different device",
            )
    else:
        if library_entry.device_id is not None:
            raise HTTPException(
                status_code=403,
                detail="Send X-Device-Id header to access this resume",
            )

    # Tuck the JD URL into the job_description so it's preserved without
    # widening the Job schema. The optimizer ignores it; the UI/popup
    # already keeps the URL it sent.
    jd_with_url = payload.jd_text
    if payload.jd_url:
        jd_with_url = f"{payload.jd_text}\n\n[Source: {payload.jd_url}]"

    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        user_resume_id=library_entry.id,
        original_filename=library_entry.original_filename,
        original_file_path=library_entry.original_file_path,
        file_type=library_entry.file_type,
        job_description=jd_with_url,
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
