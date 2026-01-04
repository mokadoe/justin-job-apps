# Claude Agent Chat - Technical Spec

> Minimal implementation of Claude Agent SDK with FastAPI + SSE streaming chat interface.
>
> **Deployed at:** https://justin-job-apps-production.up.railway.app
>
> See [spec_railway.md](spec_railway.md) for deployment configuration.
> See [db_setup.md](db_setup.md) for database schemas and connections.
> See [commands/COMMANDS.md](commands/COMMANDS.md) for adding new commands.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Browser                                 │
│  ┌──────────────┐  ┌──────────────────────────────────────────┐│
│  │   Sidebar    │  │              Main Chat                   ││
│  │  Sessions    │  │  ┌────────────────────────────────────┐  ││
│  │  Commands    │  │  │   Pipeline Viewer (collapsible)    │  ││
│  │  + New Chat  │  │  ├────────────────────────────────────┤  ││
│  ├──────────────┤  │  │        Message History             │  ││
│  │  Archive     │  │  ├────────────────────────────────────┤  ││
│  │  Toggle      │  │  │   Input + Model Selector + Send    │  ││
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
{ "prompt": "Hello!", "model": "claude-haiku-4-5-20251001" }
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
| `POST` | `/command/{session_id}` | Execute slash command |

**POST /command/{session_id} Request:**
```json
{ "text": "/filter 100" }
```

**Response:** SSE stream with events:
- `progress` - Status update: `{"type": "progress", "text": "..."}`
- `done` - Complete: `{"type": "done", "text": "..."}`
- `error` - Error: `{"type": "error", "text": "..."}`

### Sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/sessions` | List sessions (`?include_archived=true` for all) |
| `GET` | `/session/{id}` | Check session status + model |
| `DELETE` | `/session/{id}` | End and cleanup session |
| `POST` | `/sessions/{id}/archive` | Archive/unarchive session |
| `GET` | `/history/{id}` | Get chat history |

### Pipeline Stats

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/pipeline/stats` | Get pipeline stage statistics |

### Models

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/models` | List available Claude models |

### Other

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serve chat interface (embedded HTML) |
| `GET` | `/health` | Health check for Railway |

## Available Models

```python
AVAILABLE_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-5-20251101",
]
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
```

Model can be changed per-session via the UI dropdown. Switching models reconnects the SDK client.

## Session Management

### Lifecycle

1. **Creation**: New session created on first `/chat/{id}` request
2. **Reuse**: Same `session_id` reuses existing `ClaudeSDKClient`
3. **Model Switch**: Changing models disconnects and recreates client with history
4. **Archive**: Sessions can be archived (hidden from default list)
5. **Cleanup**: `DELETE /session/{id}` disconnects client and deletes from DB

### In-Memory State

```python
sessions: dict[str, ClaudeSDKClient]     # SDK client instances
session_models: dict[str, str]            # Model per session
session_locks: dict[str, asyncio.Lock]   # Prevent race conditions
```

Note: SDK connections are ephemeral. On restart, chat history is reloaded from DB but Claude's context resets.

## Claude Agent SDK Configuration

```python
ClaudeAgentOptions(
    model=model,  # Selected model
    allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebSearch", "WebFetch"],
    permission_mode="acceptEdits",
    system_prompt=generate_system_prompt(),  # Includes command docs
)
```

## Frontend

### URL Routing

- `/?session={id}` - Resume existing session, loads history
- `/` (no param) - Creates new session, updates URL

### UI Components

| Component | Description |
|-----------|-------------|
| Pipeline Viewer | Collapsible bar showing pipeline stage counts |
| Sidebar | Sessions list + commands panel + archive toggle |
| Model Selector | Dropdown to switch Claude models |
| Chat area | Scrollable message history with tool collapsing |
| Input | Text input (detects "/" prefix for commands) |

### Message Styling

| Class | Style | Usage |
|-------|-------|-------|
| `.user` | Purple, right-aligned | User messages |
| `.assistant` | Dark blue | Claude responses |
| `.system` | Teal, monospace | Command output |
| `.tool` | Green, collapsible | Tool usage/results |
| `.error` | Red | Errors |

## Files

```
agent/
├── main.py              # FastAPI server + embedded HTML
├── db.py                # Chat database (sessions, messages)
├── jobs_db.py           # Jobs database (companies, jobs, targets)
├── commands/            # Slash command handlers
│   ├── __init__.py      # Registry, dispatcher, doc generation
│   ├── scrape.py        # /scrape command
│   ├── filter.py        # /filter command
│   └── jobs.py          # /jobs command
├── spec.md              # This file
├── spec_railway.md      # Railway deployment
├── db_setup.md          # Database documentation
├── CLAUDE_HEADER.md     # Header for auto-generated CLAUDE.md
├── CLAUDE.md            # Auto-generated (don't edit)
├── requirements.txt     # Python dependencies
├── Dockerfile           # Container build
├── railway.toml         # Railway config
└── data/                # Local SQLite (gitignored)
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
```

## Running Locally

```bash
cd agent
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Known Limitations

1. **No authentication** - Anyone can access any session
2. **Single server** - No horizontal scaling support
3. **SDK context resets** - Chat history persists, but Claude's context resets on restart
