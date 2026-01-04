# Database Setup

> Database layer for the agent: SQLite locally, PostgreSQL on Railway.
>
> See [spec.md](spec.md) for application architecture.

## Quick Reference

| Scenario | Database | Set by |
|----------|----------|--------|
| Local dev (default) | SQLite | Nothing set |
| Local → Railway | PostgreSQL | `USE_REMOTE_DB=true` |
| Railway production | PostgreSQL | `RAILWAY_ENVIRONMENT` (auto) |

## Overview

The agent uses **two logical databases** via SQLAlchemy:

| Database | Local Path | Purpose |
|----------|------------|---------|
| **Chat** | `agent/data/chat.db` | Sessions, chat_messages |
| **Jobs** | `data/jobs.db` | Companies, jobs, contacts |

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
                              │  messages   │
                              └─────────────┘
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

## Schemas

### Chat Database (`db.py`)

```sql
sessions
├── id          VARCHAR PRIMARY KEY   -- UUID string
├── created_at  TIMESTAMP WITH TZ     -- Auto-set
├── updated_at  TIMESTAMP WITH TZ     -- Auto-updated
└── is_archived BOOLEAN DEFAULT false -- Hide from default list

chat_messages
├── id          VARCHAR PRIMARY KEY   -- UUID string
├── session_id  VARCHAR FK            -- → sessions.id
├── role        VARCHAR               -- "user", "assistant", or "system"
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
├── status              INTEGER DEFAULT 1     -- 0=pending_review, 1=pending, 2=reviewed, 3=applied
├── priority            INTEGER DEFAULT 1     -- 1=high (US), 3=low (non-US)
├── is_intern           BOOLEAN DEFAULT false
├── experience_analysis TEXT                  -- JSON
└── added_date          VARCHAR

contacts
├── id               INTEGER PRIMARY KEY
├── company_id       INTEGER FK NOT NULL      -- → companies.id
├── name             VARCHAR NOT NULL
├── title            VARCHAR
├── linkedin_url     VARCHAR
├── is_priority      BOOLEAN DEFAULT false    -- Decision maker?
├── match_confidence VARCHAR DEFAULT 'medium' -- high or medium
├── person_context   TEXT                     -- Background info
├── context_source   VARCHAR                  -- linkedin or google
├── discovered_date  VARCHAR
└── UNIQUE(company_id, name)

messages (outreach)
├── id               INTEGER PRIMARY KEY
├── company_id       INTEGER FK UNIQUE        -- → companies.id
├── message_text     TEXT NOT NULL
├── company_research TEXT
├── generated_date   VARCHAR
└── sent_date        VARCHAR
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
await get_pipeline_stats()         # For pipeline viewer UI
```

### Filter Command Helpers

Used by `/filter` command for two-stage AI filtering:

```python
# Get jobs for filtering
await get_unevaluated_jobs(limit=100)  # Jobs where evaluated=false

# Stage 1 (Haiku) results
await insert_target_job(job_id, score, reason, priority, is_intern, experience_analysis)
await insert_review_job(...)  # For REVIEW jobs (status=0, pending Sonnet)

# Stage 2 (Sonnet) results
await get_pending_review_jobs()  # Jobs with status=0
await finalize_review_job(job_id, accept, new_score, new_reason)

# Mark as processed
await mark_jobs_evaluated([job_id1, job_id2, ...])  # Set evaluated=true

# Re-filter
await reset_evaluated()     # Set all jobs back to evaluated=false
await clear_target_jobs()   # Delete all target_jobs
```

## Common Gotchas

### Which database am I using?

The agent prints the database URL on startup:
```
[JobsDB] Connecting to: turntable.proxy.rlwy.net:41317/railway  ← PostgreSQL
[JobsDB] Connecting to: /Users/.../data/jobs.db                 ← SQLite
```

### The .env trap

The `.env` file may set `USE_REMOTE_DB=true`, which gets loaded by `python-dotenv` and unexpectedly connects you to Railway PostgreSQL.

**Symptoms:**
- `/jobs stats` returns 0 when you have local data
- Schema errors about missing columns
- Slow responses (network latency)

**Fix:**
```bash
# Check what's in .env
cat .env | grep -E "(USE_REMOTE_DB|DATABASE_URL)"

# Run with explicit local mode
USE_REMOTE_DB=false uvicorn main:app --reload
```

### Two different SQLite files

- **Chat:** `agent/data/chat.db` (sessions, messages)
- **Jobs:** `data/jobs.db` (companies, jobs, target_jobs)

These are in different directories!

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
```

### Railway PostgreSQL

```bash
PGPASSWORD=<password> psql -h turntable.proxy.rlwy.net -U postgres -p 41317 -d railway

# In psql:
\dt                    # List tables
\d companies           # Describe table
SELECT COUNT(*) FROM jobs;
```

## Schema Migrations

SQLAlchemy's `create_all()` creates tables but **does not add columns** to existing tables. When you add columns to models, you must manually update the databases.

### Adding a Column

```bash
# 1. Update the model in jobs_db.py
#    new_column = Column(String)

# 2. Update Railway PostgreSQL
PGPASSWORD=<password> psql -h turntable.proxy.rlwy.net -U postgres -p 41317 -d railway \
  -c "ALTER TABLE tablename ADD COLUMN new_column VARCHAR;"

# 3. Update local SQLite
sqlite3 data/jobs.db "ALTER TABLE tablename ADD COLUMN new_column TEXT;"
```

### Audit Command

When schemas drift between PostgreSQL and SQLite:

```bash
# Compare columns
PGPASSWORD=<password> psql -h turntable.proxy.rlwy.net -U postgres -p 41317 -d railway \
  -c "SELECT column_name FROM information_schema.columns WHERE table_name = 'contacts' ORDER BY ordinal_position;"

sqlite3 data/jobs.db "PRAGMA table_info(contacts);"
```

**Three places must stay in sync:**
1. `agent/jobs_db.py` - SQLAlchemy models
2. Railway PostgreSQL - production database
3. Local SQLite - development database

## Dependencies

```
sqlalchemy[asyncio]>=2.0.0
aiosqlite>=0.19.0
asyncpg>=0.29.0
```
