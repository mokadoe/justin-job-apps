# Database Setup

> Swappable database layer: SQLite locally, PostgreSQL on Railway.

## Overview

The agent uses SQLAlchemy to abstract database operations. The same code runs against both SQLite (local development) and PostgreSQL (Railway production).

```
Local Development          Railway Production
       │                          │
       ▼                          ▼
   SQLite                    PostgreSQL
data/chat.db            postgres.railway.internal
```

## Schema

```sql
sessions
├── id          VARCHAR PRIMARY KEY   -- UUID string
├── created_at  TIMESTAMP WITH TZ     -- Auto-set on create
└── updated_at  TIMESTAMP WITH TZ     -- Auto-set on update

messages
├── id          VARCHAR PRIMARY KEY   -- UUID string
├── session_id  VARCHAR FK            -- Links to sessions.id
├── role        VARCHAR               -- "user" or "assistant"
├── content     TEXT                  -- Message text
└── created_at  TIMESTAMP WITH TZ     -- Auto-set on create
```

## Database URL Resolution

The database is selected based on environment variables:

| Condition | Database | URL |
|-----------|----------|-----|
| `RAILWAY_ENVIRONMENT` set | PostgreSQL | `DATABASE_URL` (internal) |
| `USE_REMOTE_DB=true` | PostgreSQL | `DATABASE_URL` (public) |
| Neither | SQLite | `sqlite:///data/chat.db` |

```python
# From db.py - simplified logic
def get_database_url():
    if os.environ.get("RAILWAY_ENVIRONMENT"):
        return os.environ["DATABASE_URL"]  # Railway auto-injects this

    if os.environ.get("USE_REMOTE_DB") == "true":
        return os.environ["DATABASE_URL"]  # You set this manually

    return "sqlite+aiosqlite:///data/chat.db"  # Local default
```

## Running Locally

### Default (SQLite)

```bash
cd agent
uvicorn main:app --reload --port 8000
```

- Database: `agent/data/chat.db` (auto-created)
- No environment variables needed

### Connecting to Railway Database

```bash
cd agent
USE_REMOTE_DB=true \
DATABASE_URL="postgresql://postgres:PASSWORD@turntable.proxy.rlwy.net:41317/railway" \
uvicorn main:app --reload --port 8000
```

Get the connection string from Railway:
```bash
railway variables --service Postgres | grep DATABASE_PUBLIC_URL
```

## Railway Architecture

```
Railway Project: job-flow
│
├── Service: justin-job-apps
│   ├── Source: /agent directory
│   ├── Builder: Dockerfile
│   ├── Variables:
│   │   ├── ANTHROPIC_API_KEY
│   │   └── DATABASE_URL → ${{Postgres.DATABASE_URL}}  ← linked
│   └── URL: justin-job-apps-production.up.railway.app
│
└── Service: Postgres
    ├── Type: Managed PostgreSQL
    ├── Volume: postgres-volume (persistent)
    ├── Internal: postgres.railway.internal:5432
    └── Public: turntable.proxy.rlwy.net:41317
```

### Variable Linking

Railway uses `${{ServiceName.VARIABLE}}` syntax to share variables between services:

```
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

This resolves at runtime to:
```
postgresql://postgres:PASSWORD@postgres.railway.internal:5432/railway
```

### Internal vs Public URLs

| Type | URL | Use Case |
|------|-----|----------|
| Internal | `postgres.railway.internal:5432` | App-to-DB within Railway |
| Public | `turntable.proxy.rlwy.net:41317` | External access (local dev) |

Internal URLs are faster and more secure (private network).

## SQLAlchemy

SQLAlchemy is the Python ORM that abstracts database differences.

### Why It Matters

```python
# You write once:
session = ChatSession(id="abc-123")
db.add(session)
await db.commit()

# SQLAlchemy generates appropriate SQL:
# SQLite:   INSERT INTO sessions VALUES (?, ?, ?)
# Postgres: INSERT INTO sessions VALUES ($1, $2, $3)
```

### Async Support

We use async SQLAlchemy with:
- `aiosqlite` - Async SQLite driver
- `asyncpg` - Async PostgreSQL driver

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

engine = create_async_engine("sqlite+aiosqlite:///data/chat.db")
# or
engine = create_async_engine("postgresql+asyncpg://...")
```

## What Persists

| Data | Persisted | Location |
|------|-----------|----------|
| Chat messages | Yes | Database |
| Session metadata | Yes | Database |
| Claude SDK connections | No | In-memory |
| Session locks | No | In-memory |

**Implication:** Restarting the server preserves chat history, but Claude's internal conversation context resets (SDK limitation).

## Files

```
agent/
├── db.py              # Models, engine factory, CRUD helpers
├── main.py            # FastAPI app (imports db.py)
├── requirements.txt   # Includes sqlalchemy, aiosqlite, asyncpg
├── data/
│   └── chat.db        # SQLite database (gitignored)
└── db_setup.md        # This file
```

## Useful Commands

```bash
# View Railway project status
railway status

# View service logs
railway logs

# List all services
railway service list

# View Postgres variables
railway variables --service Postgres

# Connect to Postgres shell
railway connect Postgres
# Then: \dt, SELECT * FROM sessions;, etc.

# Manual deploy
cd agent && railway up
```

## Inspecting Local SQLite

```bash
# List tables
sqlite3 data/chat.db ".tables"

# View schema
sqlite3 data/chat.db ".schema"

# Query sessions
sqlite3 data/chat.db "SELECT id, created_at FROM sessions;"

# Query messages
sqlite3 data/chat.db "SELECT session_id, role, substr(content, 1, 50) FROM messages;"
```

## Dependencies

```
# requirements.txt
sqlalchemy[asyncio]>=2.0.0   # ORM with async support
aiosqlite>=0.19.0            # Async SQLite driver
asyncpg>=0.29.0              # Async PostgreSQL driver
```

## Troubleshooting

### "Can't subtract offset-naive and offset-aware datetimes"

PostgreSQL is strict about timezone-aware timestamps. Fixed by using:
```python
Column(DateTime(timezone=True), server_default=func.now())
```

### Connection refused to Railway Postgres

1. Check you're using the **public** URL locally (not internal)
2. Verify the password hasn't changed: `railway variables --service Postgres`

### SQLite database locked

SQLite has limited concurrency. If you see locking issues:
1. Ensure only one process accesses the DB
2. Consider using `USE_REMOTE_DB=true` with Railway Postgres for concurrent access

---

Last updated: 2026-01-03
