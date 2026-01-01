#!/usr/bin/env python3
"""Migration: Add contacts table and website field to companies table."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"


def migrate():
    """Add contacts table and website column."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("Running migration: Add contacts table and website field...")

    # Add website column to companies table (if not exists)
    try:
        cursor.execute("ALTER TABLE companies ADD COLUMN website TEXT")
        print("  ✓ Added 'website' column to companies table")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("  ⊘ 'website' column already exists")
        else:
            raise

    # Create contacts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            title TEXT,
            linkedin_url TEXT,
            is_priority BOOLEAN DEFAULT 0,
            discovered_date TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(id),
            UNIQUE(company_id, name)
        )
    """)
    print("  ✓ Created 'contacts' table")

    # Create indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_contact_company ON contacts(company_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_contact_priority ON contacts(is_priority)")
    print("  ✓ Created indexes on contacts table")

    conn.commit()
    conn.close()

    print("\n✓ Migration complete!")
    print("\nNew schema:")
    print("  - companies.website (TEXT) - Company website URL")
    print("  - contacts table - Key people at companies")
    print("    - name, title, linkedin_url")
    print("    - is_priority (1=founder/CEO/CTO, 0=other)")


if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        print("Run 'make init' first")
    else:
        migrate()
