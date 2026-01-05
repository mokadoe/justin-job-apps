#!/usr/bin/env python3
"""
Database migration: Add 'source' column to companies table.

Tracks where companies were discovered from (e.g., 'ashby_manual', 'google_dork', 'simplify').
"""

import sqlite3
from pathlib import Path

from jobs_db_conn import is_remote

DB_PATH = Path(__file__).parent.parent.parent / 'data' / 'jobs.db'


def migrate():
    """
    Add source column to companies table and set default for existing rows.
    """
    if is_remote():
        print("Remote database - schema managed by agent/jobs_db.py")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("=" * 60)
    print("Database Migration: Add 'source' to companies table")
    print("=" * 60)
    print()

    # Check if column already exists
    cursor.execute("PRAGMA table_info(companies)")
    columns = [col[1] for col in cursor.fetchall()]

    if 'source' in columns:
        print("✓ Column 'source' already exists in companies table")
        print("  No migration needed.")
        conn.close()
        return

    # Add column
    print("Adding 'source' column to companies table...")
    cursor.execute("""
        ALTER TABLE companies
        ADD COLUMN source TEXT DEFAULT 'ashby_manual'
    """)

    # Update existing rows (all current companies are from Ashby manual list)
    cursor.execute("""
        UPDATE companies
        SET source = 'ashby_manual'
        WHERE source IS NULL OR source = ''
    """)

    conn.commit()

    # Verify
    cursor.execute("SELECT COUNT(*) FROM companies WHERE source = 'ashby_manual'")
    count = cursor.fetchone()[0]

    print(f"✓ Added 'source' column")
    print(f"✓ Updated {count} existing companies with source='ashby_manual'")
    print()
    print("=" * 60)
    print()

    conn.close()


if __name__ == '__main__':
    migrate()
