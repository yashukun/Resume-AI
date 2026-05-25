from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.config import settings
from app.models.user_resume import UserResume
from app.models.job import Job
from app.schemas import UserResumeSummary, UserResumeDetail
from app.services.storage import storage_service
from app.workers.tasks import parse_user_resume
import uuid
import hashlib
import os
from typing import List

router = APIRouter(prefix="/resumes", tags=["Resume Library"])


def _summary_from_row(r: UserResume) -> UserResumeSummary:
    name = None
    if r.user_details and isinstance(r.user_details, dict):
        name = r.user_details.get("name")
    return UserResumeSummary(
        id=r.id,
        original_filename=r.original_filename,
        file_type=r.file_type,
        file_hash=r.file_hash,
        name=name,
        is_parsed=r.user_details is not None,
        created_at=r.created_at,
    )


@router.get("", response_model=List[UserResumeSummary])
async def list_resumes(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List parsed resumes in the library, most recent first."""
    result = await db.execute(
        select(UserResume)
        .order_by(UserResume.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()
    return [_summary_from_row(r) for r in rows]


@router.get("/{resume_id}", response_model=UserResumeDetail)
async def get_resume(
    resume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single library entry with full parsed data."""
    result = await db.execute(
        select(UserResume).where(UserResume.id == resume_id)
    )
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Resume not found")

    summary = _summary_from_row(r)
    return UserResumeDetail(
        **summary.model_dump(),
        user_details=r.user_details,
        raw_text=r.raw_text,
    )


@router.post("", response_model=UserResumeDetail, status_code=201)
async def upload_resume_to_library(
    file: UploadFile = File(..., description="Resume file (PDF or DOCX)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a resume to the library without creating a job.

    If the same file (by SHA-256) is already present, returns the existing
    entry without re-uploading or re-parsing.
    """
    filename = file.filename or "unknown"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(settings.allowed_extensions)}",
        )

    content = await file.read()
    if len(content) > settings.max_upload_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {settings.max_upload_size // (1024*1024)}MB",
        )

    file_hash = hashlib.sha256(content).hexdigest()

    # Idempotent: return existing row if hash matches.
    existing = await db.execute(
        select(UserResume).where(UserResume.file_hash == file_hash)
    )
    row = existing.scalar_one_or_none()
    if row:
        summary = _summary_from_row(row)
        return UserResumeDetail(
            **summary.model_dump(),
            user_details=row.user_details,
            raw_text=row.raw_text,
        )

    # New entry — upload bytes to MinIO and persist a row.
    resume_id = uuid.uuid4()
    storage_filename = f"library/{resume_id}/{filename}"
    content_type = (
        "application/pdf" if ext == ".pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    try:
        file_path = await storage_service.upload_file(
            content, storage_filename, content_type
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to upload file: {str(e)}"
        )

    file_type = ext.replace(".", "")
    row = UserResume(
        id=resume_id,
        file_hash=file_hash,
        original_filename=filename,
        original_file_path=file_path,
        file_type=file_type,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    # Kick off background parse so the entry is ready next time it's used.
    parse_user_resume.delay(str(row.id))

    summary = _summary_from_row(row)
    return UserResumeDetail(
        **summary.model_dump(),
        user_details=row.user_details,
        raw_text=row.raw_text,
    )


@router.delete("/{resume_id}")
async def delete_resume(
    resume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Remove a resume from the library. Jobs that referenced it keep their
    own snapshot of the parsed data, so prior outputs remain downloadable.
    """
    result = await db.execute(
        select(UserResume).where(UserResume.id == resume_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Best-effort storage cleanup
    try:
        object_path = row.original_file_path.replace(
            f"{storage_service.bucket}/", ""
        )
        await storage_service.delete_file(object_path)
    except Exception:
        pass

    await db.delete(row)
    await db.commit()
    return {"message": "Resume deleted from library"}
