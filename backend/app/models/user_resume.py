from sqlalchemy import Column, String, Text, DateTime, JSON, Index
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.core.database import Base


class UserResume(Base):
    """
    A parsed-once, reusable resume in the user's library.

    Decoupled from Job so the same resume can be applied to many JDs
    without re-running the (expensive) parsing LLM call. Lookup is by
    file_hash, so re-uploading identical bytes returns the existing row.
    """

    __tablename__ = "user_resumes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # SHA-256 of the raw file bytes — unique key for dedup
    file_hash = Column(String(64), nullable=False, unique=True, index=True)

    # Anonymous identifier scoping resumes to a single user/install.
    # NULL means "legacy / web-app upload" — visible to anyone with no
    # device header. The browser extension generates a UUID on install
    # and sends it as X-Device-Id; the backend filters by it.
    device_id = Column(String(64), nullable=True, index=True)

    # Original file metadata
    original_filename = Column(String(255), nullable=False)
    original_file_path = Column(String(500), nullable=False)
    file_type = Column(String(10), nullable=False)  # pdf, docx

    # Parsed output (populated after the parser runs)
    raw_text = Column(Text, nullable=True)
    user_details = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_user_resumes_created_at", "created_at"),
    )

    def __repr__(self):
        return f"<UserResume {self.id} {self.original_filename}>"
