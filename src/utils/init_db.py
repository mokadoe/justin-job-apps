#!/usr/bin/env python3
"""Initialize the SQLite database with schema."""

import sqlite3
from pathlib import Path

# Paths
DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"
SCHEMA_PATH = Path(__file__).parent.parent.parent / "schemas" / "jobs.sql"

def init_database(force=False):
    """Create database and apply schema.

    Args:
        force: If True, delete existing database and recreate
    """
    # Ensure data directory exists
    DB_PATH.parent.mkdir(exist_ok=True)

    # If force, delete existing database
    if force and DB_PATH.exists():
        DB_PATH.unlink()
        print(f"✓ Deleted existing database at {DB_PATH}")

    # Read schema
    with open(SCHEMA_PATH, 'r') as f:
        schema = f.read()

    # Create database and apply schema
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executescript(schema)
    conn.commit()
    conn.close()

    print(f"✓ Database initialized at {DB_PATH}")
    print(f"✓ Schema applied from {SCHEMA_PATH}")

if __name__ == "__main__":
    init_database()
