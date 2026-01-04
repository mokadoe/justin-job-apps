"""Database connection abstraction for src/ scripts.

Respects USE_REMOTE_DB environment variable to switch between:
- Local SQLite (default): data/jobs.db
- Remote PostgreSQL: DATABASE_URL

Usage:
    from utils.db import get_connection

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM companies")
        rows = cursor.fetchall()
"""

import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent.parent.parent / ".env")


def is_remote():
    """Check if using remote database."""
    return (
        os.environ.get("RAILWAY_ENVIRONMENT") or
        os.environ.get("USE_REMOTE_DB", "").lower() == "true"
    )


@contextmanager
def get_connection():
    """Get database connection based on environment.

    Returns:
        Connection object (sqlite3.Connection or psycopg2.connection)
        - SQLite: rows accessible as dict-like objects via sqlite3.Row
        - PostgreSQL: rows accessible as dicts via RealDictCursor

    Usage:
        with get_connection() as conn:
            cursor = conn.cursor()
            # ... do work ...
        # auto-commits and closes
    """
    if is_remote():
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(
            os.environ.get("DATABASE_URL"),
            cursor_factory=RealDictCursor
        )
    else:
        db_path = Path(__file__).parent.parent.parent / "data" / "jobs.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
