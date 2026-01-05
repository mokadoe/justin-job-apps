#!/usr/bin/env python3
"""Migration: Add messages table for storing generated outreach."""

import sqlite3
from pathlib import Path

from jobs_db_conn import is_remote

DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"


def migrate():
    """Add messages table."""
    if is_remote():
        print("Remote database - schema managed by agent/jobs_db.py")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("Running migration: Add messages table...")

    # Create messages table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            message_text TEXT NOT NULL,
            company_research TEXT,
            generated_date TEXT DEFAULT CURRENT_TIMESTAMP,
            sent_date TEXT,
            FOREIGN KEY (company_id) REFERENCES companies(id),
            UNIQUE(company_id)
        )
    """)
    print("  ✓ Created 'messages' table")

    # Create index
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_company ON messages(company_id)")
    print("  ✓ Created index on messages table")

    conn.commit()
    conn.close()

    print("\n✓ Migration complete!")
    print("\nNew schema:")
    print("  - messages table - Generated outreach messages per company")
    print("    - message_text (personalized message)")
    print("    - company_research (context used for generation)")
    print("    - sent_date (NULL until sent)")


if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        print("Run 'make init' first")
    else:
        migrate()
