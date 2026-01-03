"""Database models and async engine factory for chat persistence."""

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

# Load .env from parent directory (where ANTHROPIC_API_KEY lives)
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, select
from sqlalchemy.sql import func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class ChatSession(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    role = Column(String, nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("ChatSession", back_populates="messages")


def get_database_url() -> str:
    """Determine database URL based on environment.

    Logic (Option A - explicit flag):
    - If RAILWAY_ENVIRONMENT is set → use DATABASE_URL (we're on Railway)
    - If USE_REMOTE_DB=true → use DATABASE_URL (local connecting to remote)
    - Otherwise → use local SQLite
    """
    # Auto-detect Railway environment
    if os.environ.get("RAILWAY_ENVIRONMENT"):
        db_url = os.environ.get("DATABASE_URL")
        if db_url:
            # Railway Postgres URLs start with postgres://, SQLAlchemy needs postgresql://
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

    # Default: local SQLite
    return "sqlite+aiosqlite:///data/chat.db"


# Global engine and session factory (initialized on startup)
engine = None
async_session_factory = None


async def init_db():
    """Initialize database engine and create tables."""
    global engine, async_session_factory

    db_url = get_database_url()
    print(f"[DB] Connecting to: {db_url.split('@')[-1] if '@' in db_url else db_url}")

    # Create data directory for SQLite if needed
    if "sqlite" in db_url:
        os.makedirs("data", exist_ok=True)

    engine = create_async_engine(db_url, echo=False)
    async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("[DB] Initialized successfully")


async def get_session() -> AsyncSession:
    """Get a database session."""
    return async_session_factory()


# CRUD helpers

async def get_or_create_chat_session(session_id: str) -> ChatSession:
    """Get existing chat session or create new one."""
    async with async_session_factory() as db:
        result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
        chat_session = result.scalar_one_or_none()

        if not chat_session:
            chat_session = ChatSession(id=session_id)
            db.add(chat_session)
            await db.commit()
            await db.refresh(chat_session)

        return chat_session


async def add_message(session_id: str, role: str, content: str) -> Message:
    """Add a message to a chat session."""
    async with async_session_factory() as db:
        # Ensure session exists
        await get_or_create_chat_session(session_id)

        # Add message
        message = Message(session_id=session_id, role=role, content=content)
        db.add(message)
        await db.commit()
        await db.refresh(message)

        return message


async def get_chat_history(session_id: str) -> list[dict]:
    """Get chat history for a session."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at)
        )
        messages = result.scalars().all()
        return [{"role": m.role, "content": m.content} for m in messages]


async def get_all_sessions() -> list[dict]:
    """Get all sessions with preview info."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(ChatSession).order_by(ChatSession.updated_at.desc())
        )
        sessions = result.scalars().all()

        session_list = []
        for s in sessions:
            # Get message count and first user message for preview
            msg_result = await db.execute(
                select(Message)
                .where(Message.session_id == s.id)
                .order_by(Message.created_at)
            )
            messages = msg_result.scalars().all()

            preview = ""
            for m in messages:
                if m.role == "user":
                    preview = m.content[:50] + ("..." if len(m.content) > 50 else "")
                    break

            session_list.append({
                "id": s.id,
                "messages": len(messages),
                "preview": preview,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            })

        return session_list


async def delete_chat_session(session_id: str) -> bool:
    """Delete a chat session and its messages."""
    async with async_session_factory() as db:
        result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
        chat_session = result.scalar_one_or_none()

        if chat_session:
            await db.delete(chat_session)
            await db.commit()
            return True
        return False


async def session_exists(session_id: str) -> bool:
    """Check if a session exists in the database."""
    async with async_session_factory() as db:
        result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
        return result.scalar_one_or_none() is not None
