# Claude Agent Chat - Technical Spec

> Minimal implementation of Claude Agent SDK with FastAPI + SSE streaming chat interface.
>
> **Deployed at:** https://justin-job-apps-production.up.railway.app
>
> See [spec_railway.md](spec_railway.md) for deployment configuration.

## Overview

A web-based chat interface that connects to Claude via the Claude Agent SDK. Supports multiple concurrent sessions with conversation history, tool usage, and session management.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Browser                            │
│  ┌─────────────┐  ┌──────────────────────────────────┐ │
│  │   Sidebar   │  │           Main Chat              │ │
│  │  Sessions   │  │  ┌────────────────────────────┐  │ │
│  │   List      │  │  │     Message History        │  │ │
│  │             │  │  └────────────────────────────┘  │ │
│  │  + New Chat │  │  ┌────────────────────────────┐  │ │
│  │             │  │  │   Input + Send Button      │  │ │
│  └─────────────┘  │  └────────────────────────────┘  │ │
└───────────────────┴──────────────────────────────────┴─┘
                              │
                              │ SSE (Server-Sent Events)
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Server                       │
│  ┌─────────────────────────────────────────────────┐   │
│  │  In-Memory Storage                              │   │
│  │  • sessions: {id → ClaudeSDKClient}             │   │
│  │  • chat_history: {id → [{role, content}]}       │   │
│  │  • session_locks: {id → asyncio.Lock}           │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                              │
                              │ Claude Agent SDK
                              ▼
┌─────────────────────────────────────────────────────────┐
│                    Claude API                           │
│  Model: claude-haiku-4-5-20251001                       │
│  Tools: Read, Write, Edit, Bash, Glob, Grep,           │
│         WebSearch, WebFetch                             │
└─────────────────────────────────────────────────────────┘
```

## API Endpoints

### Chat

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/chat/{session_id}` | Send message, receive SSE stream |

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

### Sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/sessions` | List all active sessions |
| `GET` | `/session/{id}` | Check session status (exists + active) |
| `DELETE` | `/session/{id}` | End and cleanup session |
| `GET` | `/history/{id}` | Get chat history for session |

**GET /session/{id} Response:**
```json
{
  "exists": true,
  "active": true,
  "session_id": "uuid-string"
}
```

**GET /sessions Response:**
```json
{
  "sessions": [
    {
      "id": "uuid-string",
      "messages": 4,
      "preview": "First user message...",
      "active": true,
      "created_at": "2026-01-03T12:00:00+00:00",
      "updated_at": "2026-01-03T12:05:00+00:00"
    }
  ]
}
```

**GET /history/{id} Response:**
```json
{
  "history": [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi there!"}
  ]
}
```

### UI

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serve chat interface HTML |
| `GET` | `/?session={id}` | Resume specific session |

## Session Management

### Lifecycle

1. **Creation**: New session created on first `/chat/{id}` request
2. **Reuse**: Same `session_id` reuses existing `ClaudeSDKClient` (maintains conversation history)
3. **Cleanup**: `DELETE /session/{id}` disconnects client and clears data

### Storage

**Database (persistent):**
```python
# See db.py for models
ChatSession  # id, created_at, updated_at
Message      # id, session_id, role, content, created_at
```

**In-Memory (ephemeral):**
```python
sessions: dict[str, ClaudeSDKClient]     # SDK client instances
session_locks: dict[str, asyncio.Lock]   # Prevent race conditions
```

**Database selection:** SQLite locally, PostgreSQL on Railway. See [db_setup.md](db_setup.md) for details.

### Conversation History

The Claude Agent SDK maintains conversation context internally within a `ClaudeSDKClient` instance. Multiple `query()` calls on the same client preserve full context.

We also store a simplified `chat_history` for:
- Displaying history when resuming a session via URL
- Showing previews in the sidebar

## Frontend

### URL-Based Session Routing

- `http://localhost:8000/` → Creates new session, updates URL to `/?session={id}`
- `http://localhost:8000/?session={id}` → Resumes existing session, loads history

### UI Components

| Component | Description |
|-----------|-------------|
| Sidebar | Lists all sessions with preview + message count |
| "+ New Chat" | Creates fresh session |
| Chat area | Scrollable message history |
| Input | Text input + Send button |
| Debug bar | Shows current session ID (first 8 chars) |

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

### Running on Railway

See [spec_railway.md](spec_railway.md) for deployment details.

## Known Limitations

1. **No authentication** - Anyone can access any session
2. **Single server** - No horizontal scaling support
3. **No streaming during generation** - Response collected before sending (workaround for SSE issues)
4. **SDK context not persisted** - Chat history persists, but Claude's internal context resets on restart

## Future Improvements

- [x] Persistent storage (SQLite/PostgreSQL) - See [db_setup.md](db_setup.md)
- [ ] SDK session resumption (cross-restart persistence)
- [ ] Authentication
- [ ] Real-time streaming (fix SSE + async generator issues)
- [ ] Session deletion from UI
- [ ] Search across sessions
- [ ] Export chat history

## Files

```
agent/
├── main.py           # FastAPI server + embedded HTML
├── db.py             # Database models and CRUD helpers
├── requirements.txt  # Dependencies
├── spec.md           # This file (application spec)
├── spec_railway.md   # Railway deployment spec
├── db_setup.md       # Database setup documentation
├── Dockerfile        # Container build
├── railway.toml      # Railway config
├── .dockerignore     # Docker build excludes
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
```
