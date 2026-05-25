from contextlib import asynccontextmanager
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# Create async engine (used by FastAPI — single event-loop, safe)
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
)

# Create async session factory (for FastAPI requests)
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Base class for models
Base = declarative_base()


@asynccontextmanager
async def get_task_session():
    """Create an isolated async session for Celery tasks.

    Each call spins up a *fresh* async engine + session so that
    concurrent Celery workers never share asyncpg connections
    (which are not safe for concurrent use across event-loops/processes).
    """
    task_engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        future=True,
        pool_size=1,
        max_overflow=0,
    )
    task_session_factory = async_sessionmaker(
        task_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with task_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
    await task_engine.dispose()


async def get_db() -> AsyncSession:
    """Dependency for getting async database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database tables and apply small idempotent migrations.

    There is no Alembic in this project, so `create_all` is the source
    of truth for *new* tables. For columns added to existing tables
    after first deploy we have to ALTER manually — the statements below
    are guarded with IF NOT EXISTS so re-running is safe.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # jobs.user_resume_id was added when the resume library was
        # introduced. Existing dev DBs need the column added in-place.
        try:
            await conn.execute(text(
                "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS "
                "user_resume_id UUID REFERENCES user_resumes(id) "
                "ON DELETE SET NULL"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_jobs_user_resume_id "
                "ON jobs (user_resume_id)"
            ))
        except Exception as e:
            logger.warning(f"Post-create migration step failed: {e}")
