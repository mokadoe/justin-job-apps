# Claude Agent Chat - Technical Spec

> Minimal implementation of Claude Agent SDK with FastAPI + SSE streaming chat interface.
>
> **Deployed at:** https://justin-job-apps-production.up.railway.app
>
> See [spec_railway.md](spec_railway.md) for deployment configuration.
> See [db_setup.md](db_setup.md) for database schemas and connections.

## Overview

A web-based chat interface that connects to Claude via the Claude Agent SDK. Supports multiple concurrent sessions with conversation history, tool usage, session management, and **slash commands** for job pipeline operations.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Browser                                 │
│  ┌──────────────┐  ┌──────────────────────────────────────────┐│
│  │   Sidebar    │  │              Main Chat                   ││
│  │              │  │  ┌────────────────────────────────────┐  ││
│  │  Sessions    │  │  │        Message History             │  ││
│  │    List      │  │  └────────────────────────────────────┘  ││
│  │              │  │  ┌────────────────────────────────────┐  ││
│  │  + New Chat  │  │  │     Input + Send Button            │  ││
│  ├──────────────┤  │  └────────────────────────────────────┘  ││
│  │  Commands    │  │                                          ││
│  │  /scrape     │  │  Detects "/" prefix → POST /command      ││
│  │  /filter     │  │  Otherwise        → POST /chat           ││
│  │  /jobs       │  │                                          ││
│  └──────────────┘  └──────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │ SSE              │                   │ SSE
          ▼                   ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Claude Agent   │  │ Command Handler │  │  Jobs Database  │
│  SDK (Chat)     │  │  (Slash Cmds)   │  │  (SQLite/PG)    │
└─────────────────┘  └─────────────────┘  └─────────────────┘
          │                   │
          ▼                   ▼
┌─────────────────┐  ┌─────────────────┐
│  Claude API     │  │  src/scrapers/  │ ← Code reuse via sys.path
│                 │  │  src/filters/   │
└─────────────────┘  └─────────────────┘
```

## API Endpoints

### Chat

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/chat/{session_id}` | Send message to Claude, receive SSE stream |

**Request:**
```json
{ "prompt": "Hello, Claude!" }
```

**Response:** SSE stream with events:
- `text` - Assistant text: `{"text": "..."}`
- `tool` - Tool usage: `{"tool": "Read", "input": "..."}`
- `result` - Tool result: `{"result": "..."}`
- `error` - Error: `{"error": "..."}`
- `done` - Complete: `{"done": true}`

### Slash Commands

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/commands` | List available commands |
| `POST` | `/command/{session_id}` | Execute slash command, receive SSE stream |

**POST /command/{session_id} Request:**
```json
{ "prompt": "/filter 100" }
```

**Response:** SSE stream with events:
- `progress` - Status update: `{"type": "progress", "text": "..."}`
- `done` - Complete: `{"type": "done", "text": "..."}`
- `error` - Error: `{"type": "error", "text": "..."}`

### Sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/sessions` | List all active sessions |
| `GET` | `/session/{id}` | Check session status |
| `DELETE` | `/session/{id}` | End and cleanup session |
| `GET` | `/history/{id}` | Get chat history for session |

### UI

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serve chat interface HTML |
| `GET` | `/?session={id}` | Resume specific session |

## Slash Commands

Commands provide direct access to job pipeline operations without going through Claude.

### Available Commands

| Command | Description |
|---------|-------------|
| `/scrape ashby [--force]` | Fetch jobs from all Ashby companies in DB (skip recently scraped unless --force) |
| `/scrape ashby <company>...` | Fetch jobs from specific Ashby companies |
| `/scrape simplify` | Fetch prospective companies from SimplifyJobs |
| `/filter [limit]` | AI filter jobs for new grad relevance (two-stage: Haiku + Sonnet) |
| `/filter reset` | Reset evaluated flag on all jobs (re-filter) |
| `/jobs stats` | Show database statistics |
| `/jobs pending` | Show pending target jobs |

### Two-Stage AI Filtering (`/filter`)

```
Jobs → Stage 0: Regex → Stage 1: Haiku → Stage 2: Sonnet → target_jobs
       (fast, free)    (cheap, batch)   (expensive, profile-aware)
```

1. **Stage 0 - Regex Pre-filter**: Reject obvious mismatches (senior roles, non-engineering)
2. **Stage 1 - Haiku**: Batch evaluate remaining jobs for ACCEPT/REVIEW/REJECT
3. **Stage 2 - Sonnet**: Review borderline cases with `profile.json` context

Results:
- ACCEPT → Insert into `target_jobs` with priority (1=US, 3=non-US)
- REJECT → Mark as evaluated, not stored in target_jobs

### Command Architecture

```
agent/commands/
├── __init__.py    # Registry, dispatcher, list_commands()
├── scrape.py      # /scrape handlers
├── filter.py      # /filter handlers (two-stage AI)
└── jobs.py        # /jobs handlers
```

**Registry Pattern:**
```python
from commands import register

@register("mycommand",
          description="What it does",
          usage="/mycommand <arg>")
async def handle_mycommand(args: str):
    yield {"type": "progress", "text": "Working..."}
    yield {"type": "done", "text": "Complete!"}
```

**Code Reuse:** Commands import from `src/scrapers/` and `src/filters/` via sys.path manipulation.

## Session Management

### Lifecycle

1. **Creation**: New session created on first `/chat/{id}` request
2. **Reuse**: Same `session_id` reuses existing `ClaudeSDKClient`
3. **Cleanup**: `DELETE /session/{id}` disconnects client and clears data

### Storage

See [db_setup.md](db_setup.md) for complete database schemas.

**In-Memory (ephemeral):**
```python
sessions: dict[str, ClaudeSDKClient]     # SDK client instances
session_locks: dict[str, asyncio.Lock]   # Prevent race conditions
```

## Frontend

### URL-Based Session Routing

- `http://localhost:8000/` → Creates new session, updates URL to `/?session={id}`
- `http://localhost:8000/?session={id}` → Resumes existing session, loads history

### UI Components

| Component | Description |
|-----------|-------------|
| Sidebar | Lists all sessions with preview + message count |
| Commands Panel | Shows available slash commands (clickable) |
| "+ New Chat" | Creates fresh session |
| Chat area | Scrollable message history |
| Input | Text input + Send button (detects "/" prefix) |

### Message Types (CSS classes)

| Class | Style | Usage |
|-------|-------|-------|
| `.user` | Purple, right-aligned | User messages |
| `.assistant` | Dark blue | Claude responses |
| `.tool` | Dark green, monospace | Tool usage/results |
| `.error` | Dark red | Errors |

## Configuration

### Claude Agent Options

```python
ClaudeAgentOptions(
    model="claude-haiku-4-5-20251001",
    allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebSearch", "WebFetch"],
    permission_mode="acceptEdits",
)
```

### Running Locally

```bash
cd agent
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Known Limitations

1. **No authentication** - Anyone can access any session
2. **Single server** - No horizontal scaling support
3. **SDK context not persisted** - Chat history persists, but Claude's internal context resets on restart

## Files

```
agent/
├── main.py           # FastAPI server + embedded HTML
├── db.py             # Chat database models (sessions, messages)
├── jobs_db.py        # Jobs database models + filter helpers
├── commands/         # Slash command handlers
│   ├── __init__.py   # Registry + dispatcher
│   ├── scrape.py     # /scrape command
│   ├── filter.py     # /filter command (two-stage AI)
│   └── jobs.py       # /jobs command
├── requirements.txt  # Dependencies
├── spec.md           # This file
├── spec_railway.md   # Railway deployment
├── db_setup.md       # Database documentation
├── Dockerfile        # Container build
├── railway.toml      # Railway config
└── data/
    └── chat.db       # SQLite database (local, gitignored)
```

## Dependencies

```
fastapi>=0.115.0
uvicorn>=0.32.0
claude-agent-sdk>=0.1.0
sse-starlette>=2.0.0
sqlalchemy[asyncio]>=2.0.0
aiosqlite>=0.19.0
asyncpg>=0.29.0
python-dotenv>=1.0.0
anthropic>=0.50.0
requests>=2.31.0
beautifulsoup4>=4.12.0
```
