from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum
from app.core.database import Base


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    PARSING = "parsing"
    PROCESSING = "processing"
    OPTIMIZING = "optimizing"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(Base):
    """Job model for tracking resume processing tasks."""

    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(SQLEnum(JobStatus),
                    default=JobStatus.PENDING, nullable=False)

    # Link to the parsed resume in the user's library (nullable for
    # jobs created before the library feature; new jobs always set this).
    user_resume_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user_resumes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Original file info (snapshot at job creation — kept for display
    # even if the user later deletes the library entry).
    original_filename = Column(String(255), nullable=False)
    original_file_path = Column(String(500), nullable=False)
    file_type = Column(String(10), nullable=False)  # pdf, docx

    # Job description
    job_description = Column(Text, nullable=False)
    job_title = Column(String(255), nullable=True)
    company_name = Column(String(255), nullable=True)

    # Output
    optimized_file_path = Column(String(500), nullable=True)

    # Error tracking
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Job {self.id} - {self.status}>"
