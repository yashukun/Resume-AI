from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.core.database import Base


class Resume(Base):
    """Resume model for storing parsed resume data."""

    __tablename__ = "resumes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)

    # Raw text extracted from the resume file
    raw_text = Column(Text, nullable=True)

    # Complete structured data from AI extraction (name, contact, sections)
    user_details = Column(JSON, nullable=True)

    # AI-optimized content
    optimized_summary = Column(Text, nullable=True)
    optimized_experience = Column(JSON, nullable=True)
    optimized_skills = Column(JSON, nullable=True)

    # ATS analysis
    ats_score = Column(JSON, nullable=True)  # scores and recommendations
    keyword_matches = Column(JSON, nullable=True)
    missing_keywords = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Resume {self.id} for Job {self.job_id}>"
