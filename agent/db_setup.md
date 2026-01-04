# Database Setup

> Database layer for the agent: SQLite locally, PostgreSQL on Railway.
>
> See [spec.md](spec.md) for application architecture.
> See [spec_railway.md](spec_railway.md) for deployment configuration.

## Quick Reference

| Scenario | Chat DB | Jobs DB | Set by |
|----------|---------|---------|--------|
| Local dev (default) | `agent/data/chat.db` | `data/jobs.db` | Nothing set |
| Local → Railway | PostgreSQL | PostgreSQL | `USE_REMOTE_DB=true` |
| Railway production | PostgreSQL | PostgreSQL | `RAILWAY_ENVIRONMENT` (auto) |

**Tip:** If tests fail with schema errors or return 0 counts unexpectedly, check which database you're connected to.

## Overview

The agent uses **two logical databases** with SQLAlchemy:

| Database | Local | Railway | Purpose |
|----------|-------|---------|---------|
| **Chat** | `agent/data/chat.db` | PostgreSQL | Sessions, chat_messages |
| **Jobs** | `data/jobs.db` | PostgreSQL | Companies, jobs, contacts |

On Railway, both use the same PostgreSQL instance (different tables).

```
Local Development              Railway Production
       │                              │
       ▼                              ▼
┌─────────────┐               ┌─────────────┐
│ chat.db     │               │  PostgreSQL │
│ (agent/data)│               │  (shared)   │
├─────────────┤               ├─────────────┤
│ jobs.db     │               │  sessions   │
│ (data/)     │               │  chat_messages│
└─────────────┘               │  companies  │
                              │  jobs       │
                              │  target_jobs│
                              │  contacts   │
                              │  messages   │ (outreach)
                              └─────────────┘
```

## Schemas

### Chat Database (`db.py`)

```sql
sessions
├── id          VARCHAR PRIMARY KEY   -- UUID string
├── created_at  TIMESTAMP WITH TZ     -- Auto-set
└── updated_at  TIMESTAMP WITH TZ     -- Auto-updated

chat_messages
├── id          VARCHAR PRIMARY KEY   -- UUID string
├── session_id  VARCHAR FK            -- → sessions.id
├── role        VARCHAR               -- "user" or "assistant"
├── content     TEXT                  -- Message text
└── created_at  TIMESTAMP WITH TZ     -- Auto-set
```

### Jobs Database (`jobs_db.py`)

```sql
companies
├── id               INTEGER PRIMARY KEY
├── name             VARCHAR UNIQUE NOT NULL
├── discovery_source VARCHAR DEFAULT 'manual'  -- simplify, google, manual
├── ats_platform     VARCHAR                   -- ashbyhq, greenhouse, lever
├── ats_slug         VARCHAR                   -- URL-friendly identifier
├── ats_url          VARCHAR                   -- Full careers page URL
├── website          VARCHAR
├── last_scraped     VARCHAR                   -- ISO timestamp
├── is_active        BOOLEAN DEFAULT true
└── discovered_date  VARCHAR                   -- ISO timestamp

jobs
├── id              INTEGER PRIMARY KEY
├── company_id      INTEGER FK NOT NULL       -- → companies.id
├── job_url         VARCHAR UNIQUE NOT NULL   -- Deduplication key
├── job_title       VARCHAR NOT NULL
├── job_description TEXT
├── location        VARCHAR
├── posted_date     VARCHAR
├── evaluated       BOOLEAN DEFAULT false     -- Processed by /filter?
└── discovered_date VARCHAR

target_jobs
├── id                  INTEGER PRIMARY KEY
├── job_id              INTEGER FK UNIQUE     -- → jobs.id
├── relevance_score     REAL                  -- 0.0-1.0
├── match_reason        TEXT                  -- Why it matched
├── status              INTEGER DEFAULT 1     -- 0=not_relevant, 1=pending, 2=reviewed, 3=applied
├── priority            INTEGER DEFAULT 1     -- 1=high (US), 3=low (non-US)
├── is_intern           BOOLEAN DEFAULT false
├── experience_analysis TEXT                  -- JSON
└── added_date          VARCHAR

contacts
├── id              INTEGER PRIMARY KEY
├── company_id      INTEGER FK NOT NULL       -- → companies.id
├── name            VARCHAR NOT NULL
├── title           VARCHAR
├── linkedin_url    VARCHAR
├── is_priority     BOOLEAN DEFAULT false     -- Decision maker?
└── discovered_date VARCHAR
└── UNIQUE(company_id, name)

messages (outreach)
├── id               INTEGER PRIMARY KEY
├── company_id       INTEGER FK UNIQUE        -- → companies.id
├── message_text     TEXT NOT NULL
├── company_research TEXT
├── generated_date   VARCHAR
└── sent_date        VARCHAR
```

## Database URL Resolution

Both `db.py` and `jobs_db.py` use the same logic:

```python
def get_database_url():
    # 1. Railway environment → PostgreSQL (internal URL)
    if os.environ.get("RAILWAY_ENVIRONMENT"):
        return os.environ["DATABASE_URL"]

    # 2. Explicit remote flag → PostgreSQL (public URL)
    if os.environ.get("USE_REMOTE_DB") == "true":
        return os.environ["DATABASE_URL"]

    # 3. Default → Local SQLite
    return "sqlite+aiosqlite:///path/to/db.db"
```

| Condition | Chat DB | Jobs DB |
|-----------|---------|---------|
| `RAILWAY_ENVIRONMENT` set | PostgreSQL | PostgreSQL |
| `USE_REMOTE_DB=true` | PostgreSQL | PostgreSQL |
| Neither | `agent/data/chat.db` | `data/jobs.db` |

## Common Gotchas

### Which database am I using?

The agent prints the database URL on startup:
```
[JobsDB] Connecting to: turntable.proxy.rlwy.net:41317/railway  ← PostgreSQL
[JobsDB] Connecting to: /Users/.../data/jobs.db                 ← SQLite
```

**Check your environment:**
```bash
# See if USE_REMOTE_DB is set (often loaded from .env)
echo $USE_REMOTE_DB

# Temporarily force local SQLite
unset USE_REMOTE_DB && cd agent && uvicorn main:app --reload
```

### The .env trap

The `.env` file in the project root contains `DATABASE_URL` and may set `USE_REMOTE_DB=true`. This gets loaded automatically by `python-dotenv`, which can unexpectedly connect you to Railway PostgreSQL.

**Symptoms:**
- `/jobs stats` returns 0 when you have local data
- Schema errors about missing columns
- Slow responses (network latency to Railway)

**Fix:** Either unset the variable or check `.env`:
```bash
# Check what's in .env
cat .env | grep -E "(USE_REMOTE_DB|DATABASE_URL)"

# Run with explicit local mode
USE_REMOTE_DB=false uvicorn main:app --reload
```

### Schema mismatch (Railway)

SQLAlchemy's `create_all()` creates tables but **does not add columns** to existing tables. If you add a column to a model, Railway PostgreSQL won't have it.

**Error:** `column X does not exist`

**Fix:** Manually add the column (see Schema Migrations in spec_railway.md)

### Two different SQLite files

- **Chat:** `agent/data/chat.db` (sessions, messages)
- **Jobs:** `data/jobs.db` (companies, jobs, target_jobs)

These are in different directories! When inspecting, use the correct path:
```bash
# Wrong (common mistake)
sqlite3 data/chat.db ".tables"

# Correct
sqlite3 agent/data/chat.db ".tables"  # Chat
sqlite3 data/jobs.db ".tables"         # Jobs
```

## jobs_db.py Helpers

### CRUD Operations

```python
# Company/Job operations
await upsert_company(name, ats_platform, ats_slug, ...)  # Returns Company
await upsert_job(company_id, job_url, job_title, ...)    # Returns (Job, is_new)
await get_companies_by_platform("ashbyhq")               # For /scrape ashby

# Statistics
await get_stats()                  # {companies, jobs, target_jobs, pending_jobs, contacts}
await get_pending_target_jobs()    # List of pending targets with company info
```

### Filter Command Helpers

Used by `/filter` command for two-stage AI filtering:

```python
# Get jobs for filtering
await get_unevaluated_jobs(limit=100)  # Jobs where evaluated=false

# Update after filtering
await insert_target_job(job_id, score, reason, priority, is_intern, experience_analysis)
await mark_jobs_evaluated([job_id1, job_id2, ...])  # Set evaluated=true

# Re-filter
await reset_evaluated()  # Set all jobs back to evaluated=false
```

## Running Locally

### Default (SQLite)

```bash
cd agent
uvicorn main:app --reload --port 8000
```

- Chat: `agent/data/chat.db`
- Jobs: `data/jobs.db` (project root)

### Connecting to Railway PostgreSQL

```bash
cd agent
USE_REMOTE_DB=true uvicorn main:app --reload --port 8000
```

Requires `DATABASE_URL` in `.env`:
```
DATABASE_URL=postgresql://postgres:PASSWORD@turntable.proxy.rlwy.net:41317/railway
```

## SQLAlchemy Async

Both databases use async SQLAlchemy:

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

# SQLite
engine = create_async_engine("sqlite+aiosqlite:///data/chat.db")

# PostgreSQL
engine = create_async_engine("postgresql+asyncpg://...")
```

Drivers:
- `aiosqlite` - Async SQLite
- `asyncpg` - Async PostgreSQL

## What Persists

| Data | Persisted | Location |
|------|-----------|----------|
| Chat messages | Yes | Database |
| Session metadata | Yes | Database |
| Companies/Jobs | Yes | Database |
| Target jobs | Yes | Database |
| Contacts | Yes | Database |
| Claude SDK connections | No | In-memory |
| Session locks | No | In-memory |

## Inspecting Databases

### Local SQLite

```bash
# Chat database
sqlite3 agent/data/chat.db ".tables"
sqlite3 agent/data/chat.db "SELECT id, created_at FROM sessions LIMIT 5;"

# Jobs database
sqlite3 data/jobs.db ".tables"
sqlite3 data/jobs.db "SELECT COUNT(*) FROM companies;"
sqlite3 data/jobs.db "SELECT COUNT(*) FROM jobs WHERE evaluated = 0;"
sqlite3 data/jobs.db "SELECT COUNT(*) FROM target_jobs WHERE status = 1;"
```

### Railway PostgreSQL

```bash
PGPASSWORD=<password> psql -h turntable.proxy.rlwy.net -U postgres -p 41317 -d railway

# In psql:
\dt                    # List tables
\d companies           # Describe table
SELECT COUNT(*) FROM jobs;
SELECT COUNT(*) FROM target_jobs WHERE status = 1;
```

## Dependencies

```
sqlalchemy[asyncio]>=2.0.0
aiosqlite>=0.19.0
asyncpg>=0.29.0
```

## Schema Migrations

SQLAlchemy's `create_all()` creates tables but **does not modify existing tables**. When you add columns to models, you must manually update the databases.

### Railway PostgreSQL

```bash
# Connect to Railway PostgreSQL
PGPASSWORD=ktzEklKpHsEAzjlVsGzGcWPOgXXzjKIa psql -h turntable.proxy.rlwy.net -U postgres -p 41317 -d railway

# Or run a single command
PGPASSWORD=ktzEklKpHsEAzjlVsGzGcWPOgXXzjKIa psql -h turntable.proxy.rlwy.net -U postgres -p 41317 -d railway -c "SQL HERE"
```

**Common operations:**

```sql
-- Add a column
ALTER TABLE companies ADD COLUMN discovery_source VARCHAR DEFAULT 'manual';
ALTER TABLE jobs ADD COLUMN posted_date TEXT;
ALTER TABLE target_jobs ADD COLUMN priority INTEGER DEFAULT 1;

-- Rename a table
ALTER TABLE messages RENAME TO chat_messages;

-- Check table structure
\d companies
\d jobs

-- List all tables
\dt
```

### Local SQLite

```bash
# jobs.db (job pipeline data)
sqlite3 data/jobs.db "ALTER TABLE jobs ADD COLUMN posted_date TEXT;"
sqlite3 data/jobs.db "ALTER TABLE target_jobs ADD COLUMN priority INTEGER DEFAULT 1;"
sqlite3 data/jobs.db "ALTER TABLE target_jobs ADD COLUMN is_intern BOOLEAN DEFAULT 0;"
sqlite3 data/jobs.db "ALTER TABLE target_jobs ADD COLUMN experience_analysis TEXT;"

# chat.db (chat sessions)
sqlite3 agent/data/chat.db "ALTER TABLE messages RENAME TO chat_messages;"

# Check schema
sqlite3 data/jobs.db ".schema jobs"
sqlite3 agent/data/chat.db ".schema chat_messages"
```

### Keeping Schemas in Sync

When adding columns to SQLAlchemy models, update both databases:

```bash
# Example: Adding a new column to jobs table

# 1. Update the model in jobs_db.py
#    posted_date = Column(String)

# 2. Update Railway PostgreSQL
PGPASSWORD=ktzEklKpHsEAzjlVsGzGcWPOgXXzjKIa psql -h turntable.proxy.rlwy.net -U postgres -p 41317 -d railway \
  -c "ALTER TABLE jobs ADD COLUMN posted_date VARCHAR;"

# 3. Update local SQLite
sqlite3 data/jobs.db "ALTER TABLE jobs ADD COLUMN posted_date TEXT;"
```

### Multi-Developer Schema Skew

When multiple developers work in parallel, schemas can drift:
- Dev A adds columns to `src/` scripts but forgets the SQLAlchemy model
- Dev B adds columns to the model but forgets Railway PostgreSQL
- Local SQLite gets updated but Railway doesn't (or vice versa)

**Audit command** (run periodically):

```bash
# Compare PostgreSQL vs SQLite columns for a table
PGPASSWORD=ktzEklKpHsEAzjlVsGzGcWPOgXXzjKIa psql -h turntable.proxy.rlwy.net -U postgres -p 41317 -d railway \
  -c "SELECT column_name FROM information_schema.columns WHERE table_name = 'contacts' ORDER BY ordinal_position;"

sqlite3 data/jobs.db "PRAGMA table_info(contacts);"

# Check what src/ code expects
grep -rh "INSERT INTO contacts\|ALTER TABLE contacts" src/
```

**Three places must stay in sync:**
1. `agent/jobs_db.py` - SQLAlchemy models
2. Railway PostgreSQL - production database
3. Local SQLite (`data/jobs.db`) - development database

## Troubleshooting

### Column doesn't exist (Railway)

SQLAlchemy creates tables but doesn't migrate columns. Add manually:

```bash
PGPASSWORD=<password> psql -h turntable.proxy.rlwy.net -U postgres -p 41317 -d railway \
  -c "ALTER TABLE companies ADD COLUMN ats_slug VARCHAR;"
```

### "offset-naive and offset-aware datetimes"

PostgreSQL is strict about timezones. Use:
```python
Column(DateTime(timezone=True), server_default=func.now())
```

### SQLite database locked

SQLite has limited concurrency. Use `USE_REMOTE_DB=true` for concurrent access.

---

Last updated: 2026-01-04
