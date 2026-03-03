from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from enum import Enum


class JobStatus(str, Enum):
    PENDING = "pending"
    PARSING = "parsing"
    PROCESSING = "processing"
    OPTIMIZING = "optimizing"
    COMPLETED = "completed"
    FAILED = "failed"


# Job Schemas
class JobCreate(BaseModel):
    job_description: str = Field(..., min_length=50,
                                 description="Job description text")
    job_title: Optional[str] = Field(None, description="Job title")
    company_name: Optional[str] = Field(None, description="Company name")


class JobResponse(BaseModel):
    id: UUID
    status: JobStatus
    original_filename: str
    file_type: str
    job_description: str
    job_title: Optional[str]
    company_name: Optional[str]
    optimized_file_path: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class JobStatusResponse(BaseModel):
    id: UUID
    status: JobStatus
    progress_message: Optional[str] = None
    error_message: Optional[str] = None


# Resume Schemas
class ResumeResponse(BaseModel):
    id: UUID
    job_id: UUID
    raw_text: Optional[str] = None
    user_details: Optional[Dict[str, Any]] = None
    ats_score: Optional[Dict[str, Any]] = None
    optimized_summary: Optional[str] = None
    optimized_experience: Optional[List[Dict[str, Any]]] = None
    optimized_skills: Optional[List[str]] = None
    keyword_matches: Optional[List[Any]] = None
    missing_keywords: Optional[List[Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


# Upload Schemas
class UploadResponse(BaseModel):
    job_id: UUID
    message: str
    status: JobStatus


# Health Check
class HealthCheck(BaseModel):
    status: str = "healthy"
    version: str = "1.0.0"
    services: Dict[str, str] = {}
