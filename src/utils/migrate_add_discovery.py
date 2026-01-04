#!/usr/bin/env python3
"""Migration: Add discovery_source and ats_slug columns to companies table.

This migration:
1. Adds discovery_source column (defaults to 'manual' for existing data)
2. Adds ats_slug column
3. Backfills ats_slug from existing ats_url for ashby companies
4. Creates new indexes

Safe to run multiple times - checks if columns already exist.
"""

import sqlite3
from pathlib import Path

from db import is_remote

DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"


def migrate():
    """Run the migration."""
    if is_remote():
        print("Remote database - schema managed by agent/jobs_db.py")
        return

    if not DB_PATH.exists():
        print(f"No database found at {DB_PATH}, skipping migration")
        return

    print(f"Migrating database: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check existing columns
    cursor.execute("PRAGMA table_info(companies)")
    columns = {col[1] for col in cursor.fetchall()}
    print(f"Existing columns: {columns}")

    changes_made = False

    # Add discovery_source column
    if 'discovery_source' not in columns:
        print("Adding discovery_source column...")
        cursor.execute("ALTER TABLE companies ADD COLUMN discovery_source TEXT DEFAULT 'manual'")
        changes_made = True
    else:
        print("discovery_source column already exists")

    # Add ats_slug column
    if 'ats_slug' not in columns:
        print("Adding ats_slug column...")
        cursor.execute("ALTER TABLE companies ADD COLUMN ats_slug TEXT")
        changes_made = True

        # Backfill ats_slug from ats_url for ashby companies
        print("Backfilling ats_slug from ats_url...")
        cursor.execute("""
            UPDATE companies
            SET ats_slug = REPLACE(ats_url, 'https://jobs.ashbyhq.com/', '')
            WHERE ats_platform = 'ashbyhq'
            AND ats_url LIKE 'https://jobs.ashbyhq.com/%'
        """)
        backfilled = cursor.rowcount
        print(f"  Backfilled {backfilled} companies")
    else:
        print("ats_slug column already exists")

    # Create indexes if they don't exist
    print("Creating indexes...")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_discovery_source ON companies(discovery_source)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ats_slug ON companies(ats_slug)")

    conn.commit()

    # Show summary
    cursor.execute("SELECT COUNT(*) FROM companies")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM companies WHERE ats_slug IS NOT NULL")
    with_slug = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM companies WHERE ats_platform IS NOT NULL")
    with_platform = cursor.fetchone()[0]

    print(f"\nSummary:")
    print(f"  Total companies: {total}")
    print(f"  With ats_platform: {with_platform}")
    print(f"  With ats_slug: {with_slug}")

    conn.close()

    if changes_made:
        print("\nMigration complete!")
    else:
        print("\nNo changes needed - already migrated")


if __name__ == "__main__":
    migrate()
