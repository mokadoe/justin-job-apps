# Database Abstraction Layer

> **Purpose:** This document explains the database abstraction that allows `src/` scripts to connect to either local SQLite or remote PostgreSQL based on environment variables.

---

## Overview

The `src/utils/jobs_db_conn.py` module provides a unified interface for database connections. Scripts can run against:

- **Local SQLite** (`data/jobs.db`) - Default for local development
- **Remote PostgreSQL** (Railway) - When `USE_REMOTE_DB=true` or running on Railway

This abstraction was introduced to allow the same codebase to work seamlessly with both databases without code changes.

---

## Core Module: `src/utils/jobs_db_conn.py`

```python
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
    """Get database connection based on environment."""
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
```

---

## How to Use in New Files

### Step 1: Import the Module

Add the import at the top of your file:

```python
import sys
from pathlib import Path

# Add src/ to path for imports (works for both direct run and agent import)
src_path = Path(__file__).parent.parent  # Adjust .parent count based on file depth
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
from utils.jobs_db_conn import get_connection, is_remote
```

**IMPORTANT - Import Pattern:**
- Always add **`src/`** to `sys.path`, not project root
- Always import as **`from utils.xxx`**, never `from src.utils.xxx`
- This ensures compatibility with both:
  - Direct execution (`python3 src/filters/filter_jobs.py`)
  - Agent import (agent adds `src/` to path, then imports `from filters.xxx`)

**Path depth examples:**
| File location | Path to src/ |
|---------------|--------------|
| `src/filters/filter_jobs.py` | `Path(__file__).parent.parent` |
| `src/discovery/dork_ats.py` | `Path(__file__).parent.parent` |
| `src/discovery/aggregators/run.py` | `Path(__file__).parent.parent.parent` |

### Step 2: Add the Placeholder Helper

SQL placeholders differ between databases:
- SQLite: `?`
- PostgreSQL: `%s`

Add this helper function:

```python
def _placeholder():
    """Return SQL placeholder for current database."""
    return "%s" if is_remote() else "?"
```

### Step 3: Use Context Manager for Connections

Replace direct `sqlite3.connect()` calls:

```python
# OLD (SQLite only)
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
# ... do work ...
conn.commit()
conn.close()

# NEW (works with both)
p = _placeholder()
with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM companies WHERE id = {p}", (company_id,))
    # ... do work ...
    conn.commit()  # Optional - context manager commits on exit
```

### Step 4: Handle Row Access Differences

PostgreSQL with `RealDictCursor` returns dict-like rows. SQLite with `Row` factory returns tuple-like rows that also support key access.

```python
# For COUNT queries - always use column alias
cursor.execute("SELECT COUNT(*) as cnt FROM jobs")
row = cursor.fetchone()
count = row['cnt'] if is_remote() else row[0]

# For named columns - both work with key access
cursor.execute("SELECT id, name FROM companies")
for row in cursor.fetchall():
    # This works for both:
    company = dict(row)  # Convert to dict
    print(company['id'], company['name'])
```

### Step 5: Handle INSERT Conflicts

SQLite and PostgreSQL have different syntax for upserts:

```python
p = _placeholder()

if is_remote():
    # PostgreSQL
    cursor.execute(f"""
        INSERT INTO jobs (company_id, job_url, job_title)
        VALUES ({p}, {p}, {p})
        ON CONFLICT (job_url) DO NOTHING
    """, (company_id, job_url, job_title))
else:
    # SQLite
    cursor.execute(f"""
        INSERT OR IGNORE INTO jobs (company_id, job_url, job_title)
        VALUES ({p}, {p}, {p})
    """, (company_id, job_url, job_title))
```

For `INSERT OR REPLACE` (upsert with update):

```python
if is_remote():
    cursor.execute(f"""
        INSERT INTO messages (company_id, message_text)
        VALUES ({p}, {p})
        ON CONFLICT (company_id) DO UPDATE SET
            message_text = EXCLUDED.message_text
    """, (company_id, message_text))
else:
    cursor.execute(f"""
        INSERT OR REPLACE INTO messages (company_id, message_text)
        VALUES ({p}, {p})
    """, (company_id, message_text))
```

### Step 6: Handle RETURNING for Inserts

PostgreSQL supports `RETURNING` to get the inserted ID. SQLite uses `cursor.lastrowid`:

```python
p = _placeholder()

if is_remote():
    cursor.execute(f"""
        INSERT INTO companies (name, ats_platform)
        VALUES ({p}, {p})
        RETURNING id
    """, (name, ats_platform))
    company_id = cursor.fetchone()['id']
else:
    cursor.execute(f"""
        INSERT INTO companies (name, ats_platform)
        VALUES ({p}, {p})
    """, (name, ats_platform))
    company_id = cursor.lastrowid
```

---

## Files Updated

### Core Utilities
| File | Changes |
|------|---------|
| `src/utils/jobs_db_conn.py` | **NEW** - Core abstraction module |
| `src/utils/view.py` | 4 connections updated |
| `src/utils/init_db.py` | Skips for remote (schema managed by agent/) |

### Scrapers
| File | Changes |
|------|---------|
| `src/scrapers/load_jobs.py` | 2 connections, RETURNING for inserts |
| `src/scrapers/load_all_jobs.py` | 2 connections, row access fixes |

### Filters
| File | Changes |
|------|---------|
| `src/filters/filter_jobs.py` | 2 connections, ON CONFLICT syntax |

### Discovery
| File | Changes |
|------|---------|
| `src/discovery/dork_ats.py` | 1 connection |
| `src/discovery/aggregators/run.py` | 2 connections (store_companies, queue_jobs) |

### Outreach
| File | Changes |
|------|---------|
| `src/outreach/generate_messages.py` | 4 connections, ON CONFLICT for upsert |
| `src/outreach/prepare_outreach.py` | 4 connections |

### Migrations (Local-Only)
| File | Changes |
|------|---------|
| `src/utils/migrate_add_contacts.py` | Skips for remote |
| `src/utils/migrate_add_messages.py` | Skips for remote |
| `src/utils/migrate_add_discovery.py` | Skips for remote |
| `src/utils/migrate_add_source.py` | Skips for remote |

---

## Common Pitfalls

### 1. Index-Based Row Access
PostgreSQL's `RealDictCursor` returns dicts, not tuples. `row[0]` fails.

```python
# BAD - fails on PostgreSQL
cursor.execute("SELECT COUNT(*) FROM jobs")
count = cursor.fetchone()[0]

# GOOD - works on both
cursor.execute("SELECT COUNT(*) as cnt FROM jobs")
row = cursor.fetchone()
count = row['cnt'] if is_remote() else row[0]
```

### 2. SELECT DISTINCT with ORDER BY Subquery
PostgreSQL doesn't allow `ORDER BY (subquery)` with `SELECT DISTINCT`.

```python
# BAD - fails on PostgreSQL
cursor.execute("""
    SELECT DISTINCT c.id, c.name
    FROM companies c
    JOIN jobs j ON c.id = j.company_id
    ORDER BY (SELECT COUNT(*) FROM jobs WHERE company_id = c.id) DESC
""")

# GOOD - use GROUP BY instead
cursor.execute("""
    SELECT c.id, c.name, COUNT(j.id) as job_count
    FROM companies c
    JOIN jobs j ON c.id = j.company_id
    GROUP BY c.id, c.name
    ORDER BY job_count DESC
""")
```

### 3. Missing Column Aliases
Always alias aggregate functions for consistent access:

```python
# BAD
cursor.execute("SELECT COUNT(*), MAX(id) FROM jobs")

# GOOD
cursor.execute("SELECT COUNT(*) as cnt, MAX(id) as max_id FROM jobs")
```

### 4. Forgetting to Load .env
The `jobs_db_conn.py` module loads `.env` automatically, but if you're accessing `DATABASE_URL` directly elsewhere, ensure dotenv is loaded:

```python
from dotenv import load_dotenv
load_dotenv()
```

---

## Testing

### Test Local Database
```bash
python3 src/utils/view.py db
python3 src/utils/view.py targets
```

### Test Remote Database
```bash
USE_REMOTE_DB=true python3 src/utils/view.py db
USE_REMOTE_DB=true python3 src/utils/view.py targets
```

### Compare Both
```bash
# Check job counts match expectations
python3 src/utils/view.py targets | grep "Total"
USE_REMOTE_DB=true python3 src/utils/view.py targets | grep "Total"
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `USE_REMOTE_DB` | Set to `true` to use PostgreSQL |
| `RAILWAY_ENVIRONMENT` | Auto-set when running on Railway |
| `DATABASE_URL` | PostgreSQL connection string (from Railway) |

These should be in your `.env` file (gitignored).

---

## Schema Management

- **Local SQLite**: Schema in `schemas/jobs.sql`, applied via `make init`
- **Remote PostgreSQL**: Schema managed by `agent/jobs_db.py` (SQLAlchemy async)

Migration files (`src/utils/migrate_*.py`) are local-only and skip when `is_remote()` returns true.

---

## Dependencies

Added to `requirements.txt`:
```
psycopg2-binary==2.9.9
```

Install with:
```bash
pip install -r requirements.txt
```
