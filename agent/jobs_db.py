"""Database models for jobs/companies persistence.

Dual-mode database:
- Local: SQLite at data/jobs.db (relative to project root)
- Railway: PostgreSQL (same database as chat, different tables)
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env from parent directory
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean, DateTime,
    ForeignKey, Index, select, func
)
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, relationship


class JobsBase(DeclarativeBase):
    """Base class for jobs-related models."""
    pass


class Company(JobsBase):
    """Company record.

    discovery_source: where we found this company (simplify, google, manual)
    ats_platform: which ATS they use (ashbyhq, greenhouse, lever) - nullable until enriched
    ats_slug: the URL-friendly identifier for their careers page
    """
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    discovery_source = Column(String, default='manual')
    ats_platform = Column(String, nullable=True)
    ats_slug = Column(String, nullable=True)
    ats_url = Column(String)
    website = Column(String)
    last_scraped = Column(String)
    is_active = Column(Boolean, default=True)
    discovered_date = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())

    jobs = relationship("Job", back_populates="company", cascade="all, delete-orphan")
    contacts = relationship("Contact", back_populates="company", cascade="all, delete-orphan")
    messages = relationship("OutreachMessage", back_populates="company", cascade="all, delete-orphan")


class Job(JobsBase):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    job_url = Column(String, unique=True, nullable=False)
    job_title = Column(String, nullable=False)
    job_description = Column(Text)
    location = Column(String)
    posted_date = Column(String)
    evaluated = Column(Boolean, default=False)
    discovered_date = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())

    company = relationship("Company", back_populates="jobs")
    target_job = relationship("TargetJob", back_populates="job", uselist=False, cascade="all, delete-orphan")


class TargetJob(JobsBase):
    """Filtered jobs to apply to.

    Status: 0=not_relevant, 1=pending, 2=reviewed, 3=applied
    Priority: 1=high (US), 2=medium, 3=low (non-US but relevant)
    """
    __tablename__ = "target_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), unique=True, nullable=False)
    relevance_score = Column(Float)
    match_reason = Column(Text)
    status = Column(Integer, default=1)
    priority = Column(Integer, default=1)
    is_intern = Column(Boolean, default=False)
    experience_analysis = Column(Text)
    added_date = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())

    job = relationship("Job", back_populates="target_job")


class Contact(JobsBase):
    """Key people at companies.

    is_priority: 1=founder/CEO/CTO (decision maker), 0=other engineering leadership
    """
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String, nullable=False)
    title = Column(String)
    linkedin_url = Column(String)
    is_priority = Column(Boolean, default=False)
    discovered_date = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())

    company = relationship("Company", back_populates="contacts")

    __table_args__ = (
        Index('idx_contact_company_name', 'company_id', 'name', unique=True),
    )


class OutreachMessage(JobsBase):
    """Generated outreach messages."""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), unique=True, nullable=False)
    message_text = Column(Text, nullable=False)
    company_research = Column(Text)
    generated_date = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())
    sent_date = Column(String)

    company = relationship("Company", back_populates="messages")


# Add indexes (SQLAlchemy handles these via Index objects or in __table_args__)
Index('idx_job_url', Job.job_url)
Index('idx_company_id', Job.company_id)
Index('idx_evaluated', Job.evaluated)
Index('idx_posted_date', Job.posted_date)
Index('idx_company_name', Company.name)
Index('idx_ats_platform', Company.ats_platform)
Index('idx_discovery_source', Company.discovery_source)
Index('idx_ats_slug', Company.ats_slug)
Index('idx_target_job_id', TargetJob.job_id)
Index('idx_status', TargetJob.status)
Index('idx_contact_company', Contact.company_id)
Index('idx_contact_priority', Contact.is_priority)
Index('idx_message_company', OutreachMessage.company_id)


def get_jobs_database_url() -> str:
    """Determine jobs database URL based on environment.

    - Railway/USE_REMOTE_DB → PostgreSQL (same DB as chat)
    - Local → SQLite at data/jobs.db (project root)
    """
    # Auto-detect Railway environment
    if os.environ.get("RAILWAY_ENVIRONMENT"):
        db_url = os.environ.get("DATABASE_URL")
        if db_url:
            if db_url.startswith("postgres://"):
                db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif db_url.startswith("postgresql://"):
                db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return db_url

    # Explicit flag for local → remote connection
    if os.environ.get("USE_REMOTE_DB", "").lower() == "true":
        db_url = os.environ.get("DATABASE_URL")
        if db_url:
            if db_url.startswith("postgres://"):
                db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif db_url.startswith("postgresql://"):
                db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return db_url

    # Default: local SQLite at project root data/jobs.db
    project_root = Path(__file__).parent.parent
    jobs_db_path = project_root / "data" / "jobs.db"
    return f"sqlite+aiosqlite:///{jobs_db_path}"


# Global engine and session factory
jobs_engine = None
jobs_session_factory = None


async def init_jobs_db():
    """Initialize jobs database engine and create tables."""
    global jobs_engine, jobs_session_factory

    db_url = get_jobs_database_url()
    print(f"[JobsDB] Connecting to: {db_url.split('@')[-1] if '@' in db_url else db_url}")

    # Create data directory for SQLite if needed
    if "sqlite" in db_url:
        db_path = Path(db_url.replace("sqlite+aiosqlite:///", ""))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    jobs_engine = create_async_engine(db_url, echo=False)
    jobs_session_factory = async_sessionmaker(jobs_engine, expire_on_commit=False)

    # Create tables
    async with jobs_engine.begin() as conn:
        await conn.run_sync(JobsBase.metadata.create_all)

    print("[JobsDB] Initialized successfully")


async def get_jobs_session() -> AsyncSession:
    """Get a jobs database session."""
    return jobs_session_factory()


# CRUD helpers

async def upsert_company(
    name: str,
    ats_platform: str = None,
    ats_slug: str = None,
    ats_url: str = None,
    discovery_source: str = 'manual',
    website: str = None
) -> Company:
    """Upsert a company and return it.

    For new companies, all fields are set.
    For existing companies, only updates last_scraped and is_active.
    To update other fields on existing companies, use update_company().
    """
    async with jobs_session_factory() as db:
        result = await db.execute(select(Company).where(Company.name == name))
        company = result.scalar_one_or_none()

        if company:
            company.last_scraped = datetime.now(timezone.utc).isoformat()
            company.is_active = True
        else:
            company = Company(
                name=name,
                discovery_source=discovery_source,
                ats_platform=ats_platform,
                ats_slug=ats_slug,
                ats_url=ats_url,
                website=website,
                last_scraped=datetime.now(timezone.utc).isoformat()
            )
            db.add(company)

        await db.commit()
        await db.refresh(company)
        return company


async def upsert_job(company_id: int, job_url: str, job_title: str,
                     job_description: str = None, location: str = None,
                     posted_date: str = None) -> tuple[Job, bool]:
    """Upsert a job. Returns (job, is_new)."""
    async with jobs_session_factory() as db:
        result = await db.execute(select(Job).where(Job.job_url == job_url))
        job = result.scalar_one_or_none()

        if job:
            return job, False

        job = Job(
            company_id=company_id,
            job_url=job_url,
            job_title=job_title,
            job_description=job_description,
            location=location,
            posted_date=posted_date
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job, True


async def get_company_count() -> int:
    """Get total company count."""
    async with jobs_session_factory() as db:
        result = await db.execute(select(func.count(Company.id)))
        return result.scalar()


async def get_companies_by_platform(ats_platform: str) -> list[dict]:
    """Get all companies for a given ATS platform."""
    async with jobs_session_factory() as db:
        # Only select columns we need (avoids schema mismatch with Railway)
        result = await db.execute(
            select(Company.id, Company.name, Company.ats_url)
            .where(Company.ats_platform == ats_platform)
            .where(Company.is_active == True)
            .order_by(Company.name)
        )
        rows = result.all()
        return [{"id": r.id, "name": r.name, "ats_url": r.ats_url} for r in rows]


async def get_job_count() -> int:
    """Get total job count."""
    async with jobs_session_factory() as db:
        result = await db.execute(select(func.count(Job.id)))
        return result.scalar()


async def get_target_job_count() -> int:
    """Get target jobs count."""
    async with jobs_session_factory() as db:
        result = await db.execute(select(func.count(TargetJob.id)))
        return result.scalar()


async def get_pending_target_jobs() -> list[dict]:
    """Get pending target jobs with company info."""
    async with jobs_session_factory() as db:
        result = await db.execute(
            select(TargetJob, Job, Company)
            .join(Job, TargetJob.job_id == Job.id)
            .join(Company, Job.company_id == Company.id)
            .where(TargetJob.status == 1)
            .order_by(TargetJob.priority, TargetJob.relevance_score.desc())
        )
        rows = result.all()
        return [
            {
                "target_id": tj.id,
                "job_id": j.id,
                "job_title": j.job_title,
                "job_url": j.job_url,
                "company": c.name,
                "location": j.location,
                "relevance_score": tj.relevance_score,
                "priority": tj.priority,
            }
            for tj, j, c in rows
        ]


async def get_stats() -> dict:
    """Get database statistics."""
    companies = await get_company_count()
    jobs = await get_job_count()
    targets = await get_target_job_count()

    async with jobs_session_factory() as db:
        # Get pending count
        result = await db.execute(
            select(func.count(TargetJob.id)).where(TargetJob.status == 1)
        )
        pending = result.scalar()

        # Get contacts count
        result = await db.execute(select(func.count(Contact.id)))
        contacts = result.scalar()

    return {
        "companies": companies,
        "jobs": jobs,
        "target_jobs": targets,
        "pending_jobs": pending,
        "contacts": contacts,
    }
