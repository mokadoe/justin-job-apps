"""Minimal Claude Agent SDK + FastAPI + SSE streaming chat."""

import os
import json
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)
import db
import jobs_db
from commands import dispatch as dispatch_command, list_commands, generate_system_prompt, generate_claude_md


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize CLAUDE.md and databases on startup."""
    # Generate CLAUDE.md before any ClaudeSDKClient is created
    # This ensures the SDK has up-to-date context about available commands
    agent_dir = Path(__file__).parent
    claude_md_path = agent_dir / "CLAUDE.md"
    claude_md_path.write_text(generate_claude_md())
    print(f"[Startup] Generated {claude_md_path}")

    await db.init_db()
    await jobs_db.init_jobs_db()
    yield


app = FastAPI(lifespan=lifespan)

# Store active SDK sessions and locks (in-memory, ephemeral)
sessions: dict[str, ClaudeSDKClient] = {}
session_models: dict[str, str] = {}  # Track model per session
session_locks: dict[str, asyncio.Lock] = {}
running_tasks: dict[str, asyncio.Task] = {}  # Track running requests for abort

AVAILABLE_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-5-20251101",
]
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

def get_options(model: str = DEFAULT_MODEL, conversation_history: list[dict] = None):
    # Generate system prompt from command registry
    system_prompt = generate_system_prompt()

    if conversation_history:
        # Append history context
        history_text = "\n".join([
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in conversation_history
        ])
        system_prompt += f"""
You are continuing a conversation. Here is the conversation history so far:

<conversation_history>
{history_text}
</conversation_history>

Continue the conversation naturally, taking into account what was discussed above."""

    return ClaudeAgentOptions(
        model=model,
        allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebSearch", "WebFetch"],
        permission_mode="acceptEdits",
        system_prompt=system_prompt,
    )


async def get_or_create_session(session_id: str, model: str = None) -> ClaudeSDKClient:
    """Get existing session or create new one. Recreates if model changed."""
    if session_id not in session_locks:
        session_locks[session_id] = asyncio.Lock()

    use_model = model or DEFAULT_MODEL

    async with session_locks[session_id]:
        # Check if model changed - if so, disconnect old client
        if session_id in sessions:
            current_model = session_models.get(session_id)
            if current_model and current_model != use_model:
                print(f"[{session_id[:8]}] Model changed: {current_model} -> {use_model}, reconnecting...")
                try:
                    await sessions[session_id].disconnect()
                except:
                    pass
                del sessions[session_id]

        if session_id not in sessions:
            # Always load conversation history when creating a new client
            # This handles: model switch, server restart, or explicit reload
            history = await db.get_chat_history(session_id)
            if history:
                print(f"[{session_id[:8]}] Loading {len(history)} messages from history")

            print(f"[{session_id[:8]}] Creating session with model: {use_model}")
            client = ClaudeSDKClient(get_options(use_model, history if history else None))
            await client.connect()
            sessions[session_id] = client
            session_models[session_id] = use_model
        else:
            print(f"[{session_id[:8]}] REUSING existing session (model: {session_models.get(session_id, 'unknown')})")
        return sessions[session_id]


async def collect_response(session_id: str, prompt: str, model: str = None) -> list[dict]:
    """Collect Claude's response messages."""
    print(f"[{session_id[:8]}] Starting request: {prompt[:50]}...")
    events = []

    # Ensure session exists in DB and store user message
    await db.get_or_create_chat_session(session_id)
    await db.add_message(session_id, "user", prompt)

    try:
        client = await get_or_create_session(session_id, model)
        print(f"[{session_id[:8]}] Got client, sending query...")
        await client.query(prompt)
        print(f"[{session_id[:8]}] Query sent, receiving response...")

        message_count = 0
        assistant_text = ""
        async for message in client.receive_response():
            message_count += 1
            print(f"[{session_id[:8]}] Message {message_count}: {type(message).__name__}")
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        assistant_text += block.text
                        events.append({"event": "text", "data": json.dumps({"text": block.text})})
                    elif isinstance(block, ToolUseBlock):
                        events.append({"event": "tool", "data": json.dumps({"tool": block.name, "input": str(block.input)[:200]})})
                    elif isinstance(block, ToolResultBlock):
                        content = block.content if isinstance(block.content, str) else str(block.content)
                        events.append({"event": "result", "data": json.dumps({"result": content[:500]})})
            elif isinstance(message, ResultMessage):
                print(f"[{session_id[:8]}] Done! Turns: {message.num_turns}")
                events.append({"event": "done", "data": json.dumps({"done": True})})

        # Store assistant response
        if assistant_text:
            await db.add_message(session_id, "assistant", assistant_text)

        print(f"[{session_id[:8]}] Response complete, {message_count} messages, {len(events)} events")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[{session_id[:8]}] ERROR: {e}")
        # Session might be corrupted, remove it
        if session_id in sessions:
            try:
                await sessions[session_id].disconnect()
            except:
                pass
            del sessions[session_id]
        events.append({"event": "error", "data": json.dumps({"error": str(e)})})

    return events


async def stream_with_heartbeat(session_id: str, prompt: str, model: str = None):
    """Stream response with periodic heartbeats while processing."""
    import asyncio

    # Start collecting in background
    events_future = asyncio.ensure_future(collect_response(session_id, prompt, model))

    # Track the task for abort functionality
    running_tasks[session_id] = events_future

    try:
        # Send heartbeats while waiting
        heartbeat_count = 0
        while not events_future.done():
            heartbeat_count += 1
            dots = "." * ((heartbeat_count % 3) + 1)
            yield {"event": "thinking", "data": json.dumps({"status": f"thinking{dots}"})}
            await asyncio.sleep(1.0)

        # Get the collected events
        events = await events_future

        # Stream the actual response
        for event in events:
            yield event
    except asyncio.CancelledError:
        yield {"event": "error", "data": json.dumps({"error": "Request cancelled"})}
    finally:
        # Clean up task tracking
        running_tasks.pop(session_id, None)


@app.post("/chat/{session_id}")
async def chat(session_id: str, request: Request):
    """Chat endpoint with SSE streaming."""
    body = await request.json()
    prompt = body.get("prompt", "")
    model = body.get("model")  # Optional: only used when creating new session
    return EventSourceResponse(stream_with_heartbeat(session_id, prompt, model))


@app.delete("/session/{session_id}")
async def end_session(session_id: str):
    """End a chat session (closes SDK connection and deletes from DB)."""
    # Close SDK connection if active
    if session_id in sessions:
        await sessions[session_id].disconnect()
        del sessions[session_id]

    # Delete from database
    deleted = await db.delete_chat_session(session_id)
    if deleted:
        return {"status": "deleted"}
    return {"status": "not_found"}


@app.get("/session/{session_id}")
async def check_session(session_id: str):
    """Check if a session exists."""
    in_db = await db.session_exists(session_id)
    in_memory = session_id in sessions
    return {
        "exists": in_db,
        "active": in_memory,  # Has live SDK connection
        "session_id": session_id,
        "model": session_models.get(session_id),
    }


@app.post("/session/{session_id}/abort")
async def abort_session(session_id: str):
    """Abort any running request for this session."""
    aborted = False

    # Cancel running task if exists
    if session_id in running_tasks:
        task = running_tasks[session_id]
        if not task.done():
            task.cancel()
            print(f"[{session_id[:8]}] Task cancelled")
            aborted = True
        del running_tasks[session_id]

    # Disconnect and remove SDK client to stop any in-progress request
    if session_id in sessions:
        try:
            await sessions[session_id].disconnect()
            print(f"[{session_id[:8]}] Client disconnected")
        except Exception as e:
            print(f"[{session_id[:8]}] Disconnect error: {e}")
        del sessions[session_id]
        aborted = True

    return {"aborted": aborted, "session_id": session_id}


@app.get("/models")
async def list_models():
    """List available models."""
    return {"models": AVAILABLE_MODELS, "default": DEFAULT_MODEL}


@app.get("/sessions")
async def list_sessions(include_archived: bool = False):
    """List all sessions with preview.

    Args:
        include_archived: If true, include archived sessions. Default false.
    """
    sessions_list = await db.get_all_sessions(include_archived=include_archived)
    # Add indicator for active SDK connections
    for s in sessions_list:
        s["active"] = s["id"] in sessions
    return {"sessions": sessions_list}


@app.post("/sessions/{session_id}/archive")
async def archive_session(session_id: str, request: Request):
    """Archive or unarchive a session.

    Body: {"archive": true} to archive, {"archive": false} to unarchive
    """
    body = await request.json()
    archive = body.get("archive", True)

    success = await db.archive_session(session_id, archive=archive)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"success": True, "archived": archive}


@app.get("/history/{session_id}")
async def get_history(session_id: str):
    """Get chat history for a session."""
    history = await db.get_chat_history(session_id)
    return {"history": history}


@app.get("/commands")
async def get_commands():
    """List available slash commands for UI."""
    return {"commands": list_commands()}


@app.get("/pipeline/stats")
async def get_pipeline_stats():
    """Get pipeline stage statistics for the viewer."""
    stats = await jobs_db.get_pipeline_stats()
    return stats


@app.get("/api/view/{stage}")
async def get_view_data(stage: str):
    """Get data for pipeline stage viewer."""
    data = await jobs_db.get_view_data(stage)
    if data is None:
        return {"error": f"Unknown stage: {stage}"}
    return data


VIEWER_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <link href="https://cdn.jsdelivr.net/npm/gridjs/dist/theme/mermaid.min.css" rel="stylesheet"/>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: system-ui, sans-serif; background: #1a1a2e; color: #eee; padding: 1rem; }}
        h1 {{ margin-bottom: 1rem; font-size: 1.5rem; color: #aaa; }}
        .count {{ color: #666; font-weight: normal; font-size: 1rem; }}
        #columns-panel {{ background: #12121f; padding: 0.75rem 1rem; border-radius: 8px; margin-bottom: 1rem; }}
        .panel-header {{ font-size: 0.75rem; color: #666; text-transform: uppercase; margin-bottom: 0.5rem; cursor: pointer; }}
        .panel-header:hover {{ color: #888; }}
        #column-checkboxes {{ display: flex; flex-wrap: wrap; gap: 0.5rem 1rem; }}
        #column-checkboxes.collapsed {{ display: none; }}
        .col-check {{ display: flex; align-items: center; gap: 0.3rem; font-size: 0.85rem; color: #aaa; cursor: pointer; }}
        .col-check:hover {{ color: #ccc; }}
        .col-check input {{ cursor: pointer; }}
        #table {{ margin-top: 1rem; }}
        /* Grid.js dark theme overrides */
        .gridjs-wrapper {{ border: 1px solid #333; border-radius: 8px; }}
        .gridjs-table {{ background: #1a1a2e; }}
        .gridjs-thead th {{ background: #12121f; color: #aaa; border-bottom: 1px solid #333; }}
        .gridjs-tbody td {{ background: #1a1a2e; color: #ccc; border-bottom: 1px solid #222; }}
        .gridjs-tr:hover td {{ background: #2a2a4a; }}
        .gridjs-footer {{ background: #12121f; border-top: 1px solid #333; }}
        .gridjs-pagination {{ color: #aaa; }}
        .gridjs-pages button {{ background: #2a2a4a; color: #aaa; border: 1px solid #333; }}
        .gridjs-pages button:hover {{ background: #3a3a5a; }}
        .gridjs-pages button.gridjs-currentPage {{ background: #4a4a8a; color: #fff; }}
        .gridjs-search {{ background: #12121f; }}
        .gridjs-search-input {{ background: #1a1a2e; color: #eee; border: 1px solid #444; border-radius: 4px; padding: 0.5rem; }}
        .gridjs-search-input:focus {{ outline: none; border-color: #6a6aaa; }}
        .gridjs-notfound {{ background: #1a1a2e; color: #888; }}
        a {{ color: #6a8aaa; }}
    </style>
</head>
<body>
    <h1>{title} <span class="count">({count} rows)</span></h1>
    <div id="columns-panel">
        <div class="panel-header" onclick="togglePanel()">Columns ▼</div>
        <div id="column-checkboxes"></div>
    </div>
    <div id="table"></div>

    <script src="https://cdn.jsdelivr.net/npm/gridjs/dist/gridjs.umd.js"></script>
    <script>
        const stage = '{stage}';
        let allColumns = {all_columns};
        let defaultColumns = {default_columns};
        let rows = {rows};
        let activeColumns = [...defaultColumns];
        let grid = null;
        let panelCollapsed = false;

        function togglePanel() {{
            panelCollapsed = !panelCollapsed;
            document.getElementById('column-checkboxes').classList.toggle('collapsed', panelCollapsed);
            document.querySelector('.panel-header').textContent = 'Columns ' + (panelCollapsed ? '▶' : '▼');
        }}

        function renderCheckboxes() {{
            const container = document.getElementById('column-checkboxes');
            container.innerHTML = allColumns.map(col => {{
                const checked = activeColumns.includes(col) ? 'checked' : '';
                return '<label class="col-check"><input type="checkbox" value="' + col + '" ' + checked + ' onchange="toggleColumn(this)"> ' + col + '</label>';
            }}).join('');
        }}

        function toggleColumn(checkbox) {{
            const col = checkbox.value;
            if (checkbox.checked) {{
                if (!activeColumns.includes(col)) {{
                    // Insert in original order
                    const idx = allColumns.indexOf(col);
                    let insertAt = activeColumns.length;
                    for (let i = 0; i < activeColumns.length; i++) {{
                        if (allColumns.indexOf(activeColumns[i]) > idx) {{
                            insertAt = i;
                            break;
                        }}
                    }}
                    activeColumns.splice(insertAt, 0, col);
                }}
            }} else {{
                activeColumns = activeColumns.filter(c => c !== col);
            }}
            updateGrid();
        }}

        function formatCell(value, col) {{
            if (value === null || value === undefined) return '';
            // Make URLs clickable
            if (col.includes('url') && typeof value === 'string' && value.startsWith('http')) {{
                return gridjs.html('<a href="' + value + '" target="_blank">link</a>');
            }}
            // Format booleans
            if (typeof value === 'boolean') return value ? 'Yes' : 'No';
            // Format dates (truncate time)
            if (col.includes('date') && typeof value === 'string' && value.includes('T')) {{
                return value.split('T')[0];
            }}
            return value;
        }}

        function updateGrid() {{
            const columns = activeColumns.map(col => ({{
                name: col,
                formatter: (cell) => formatCell(cell, col)
            }}));
            const data = rows.map(row => activeColumns.map(col => row[col]));

            if (grid) {{
                grid.updateConfig({{ columns, data }}).forceRender();
            }} else {{
                grid = new gridjs.Grid({{
                    columns,
                    data,
                    search: true,
                    sort: true,
                    pagination: {{ limit: 50 }},
                    fixedHeader: true,
                    height: 'calc(100vh - 180px)'
                }}).render(document.getElementById('table'));
            }}
        }}

        renderCheckboxes();
        updateGrid();
    </script>
</body>
</html>"""


@app.get("/view/{stage}", response_class=HTMLResponse)
async def view_stage(stage: str):
    """Serve the pipeline stage viewer page."""
    data = await jobs_db.get_view_data(stage)
    if data is None:
        return HTMLResponse(f"<h1>Unknown stage: {stage}</h1>", status_code=404)

    html = VIEWER_HTML.format(
        title=data["title"],
        stage=stage,
        count=len(data["rows"]),
        all_columns=json.dumps(data["all_columns"]),
        default_columns=json.dumps(data["default_columns"]),
        rows=json.dumps(data["rows"])
    )
    return HTMLResponse(html)


@app.post("/command/{session_id}")
async def run_command(session_id: str, request: Request):
    """Execute a slash command with SSE progress streaming."""
    body = await request.json()
    text = body.get("text", "")

    # Store the command in chat history
    await db.get_or_create_chat_session(session_id)
    await db.add_message(session_id, "user", text)

    async def event_stream():
        result_text = []
        async for event in dispatch_command(text):
            event_type = event.get("type", "progress")
            yield {"event": event_type, "data": json.dumps(event)}
            result_text.append(event.get("text", ""))

        # Store the result in chat history
        if result_text:
            await db.add_message(session_id, "system", "\n".join(result_text))

    return EventSourceResponse(event_stream())


HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Claude Agent Chat</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: system-ui, sans-serif; background: #1a1a2e; color: #eee; height: 100vh; display: flex; }
        #sidebar { width: 220px; background: #12121f; border-right: 1px solid #333; display: flex; flex-direction: column; }
        #new-session { margin: 0.75rem; padding: 0.5rem; background: #4a4a8a; border: none; border-radius: 6px; color: #fff; cursor: pointer; font-size: 0.9rem; }
        #new-session:hover { background: #5a5a9a; }
        #sessions-list { flex: 1; overflow-y: auto; }
        .session-link { display: flex; align-items: flex-start; padding: 0.6rem 0.75rem; text-decoration: none; color: #aaa; border-bottom: 1px solid #222; gap: 0.5rem; }
        .session-link:hover { background: #1a1a2e; }
        .session-link.active { background: #2a2a4a; color: #fff; }
        .session-content { flex: 1; min-width: 0; }
        .session-preview { display: block; font-size: 0.9rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #ccc; }
        .session-count { font-size: 0.7rem; color: #555; margin-top: 0.2rem; display: block; }
        .no-sessions { padding: 1rem; color: #555; font-size: 0.85rem; text-align: center; }
        #archive-toggle { display: block; padding: 0.5rem 0.75rem; font-size: 0.75rem; color: #555; cursor: pointer; border-top: 1px solid #333; }
        #archive-toggle input { margin-right: 0.4rem; }
        .archive-btn { background: none; border: none; color: #444; cursor: pointer; font-size: 1rem; padding: 0.2rem; line-height: 1; opacity: 0; transition: opacity 0.15s; }
        .session-link:hover .archive-btn { opacity: 1; }
        .archive-btn:hover { color: #aaa; }
        .session-link.archived { opacity: 0.5; }
        .session-link.archived .session-preview::before { content: '[archived] '; color: #666; }
        #main { flex: 1; display: flex; flex-direction: column; }
        #chat { flex: 1; overflow-y: auto; padding: 1rem; }
        .msg { margin: 0.5rem 0; padding: 0.75rem 1rem; border-radius: 8px; max-width: 80%; word-wrap: break-word; }
        .user { background: #4a4a6a; margin-left: auto; }
        .assistant { background: #2a2a4a; }
        .tool-container { max-height: 200px; overflow-y: auto; margin: 0.5rem 0; border-radius: 8px; background: #1a3a2a; }
        .tool { background: #1a3a2a; font-size: 0.8rem; font-family: monospace; margin: 0; border-radius: 0; border-bottom: 1px solid #2a4a3a; padding: 0.5rem 0.75rem; }
        .error { background: #4a1a1a; color: #faa; }
        .loading { background: #2a2a4a; color: #888; }
        .loading::after { content: ''; animation: dots 1.5s infinite; }
        @keyframes dots { 0%, 20% { content: '.'; } 40% { content: '..'; } 60%, 100% { content: '...'; } }
        #input-area { display: flex; padding: 1rem; background: #0a0a1a; gap: 0.5rem; }
        #prompt { flex: 1; padding: 0.75rem; border: 1px solid #444; border-radius: 6px; background: #1a1a2e; color: #eee; font-size: 1rem; }
        #prompt:focus { outline: none; border-color: #6a6aaa; }
        #prompt:disabled { background: #151525; color: #666; cursor: not-allowed; }
        button { padding: 0.75rem 1.5rem; border: none; border-radius: 6px; background: #4a4a8a; color: #fff; cursor: pointer; font-size: 1rem; }
        button:hover { background: #5a5a9a; }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
        #stop { background: #8a4a4a; }
        #stop:hover { background: #9a5a5a; }
        pre { white-space: pre-wrap; word-break: break-word; margin: 0; }
        #debug { font-size: 0.7rem; color: #666; padding: 0.25rem 1rem; background: #0a0a1a; font-family: monospace; display: flex; align-items: center; gap: 1.5rem; }
        #debug span { color: #888; }
        #debug > div { display: flex; align-items: center; gap: 0.4rem; }
        #model-select { background: #1a1a2e; color: #aaa; border: 1px solid #444; border-radius: 4px; padding: 0.15rem 0.3rem; font-size: 0.7rem; font-family: monospace; cursor: pointer; }
        #model-select:focus { outline: none; border-color: #6a6aaa; }
        /* Commands panel */
        #commands-panel { border-top: 1px solid #333; padding: 0.5rem; }
        .panel-header { font-size: 0.75rem; color: #666; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }
        .command-item { padding: 0.4rem 0.5rem; margin: 0.25rem 0; background: #1a1a2e; border-radius: 4px; cursor: pointer; font-size: 0.8rem; }
        .command-item:hover { background: #2a2a4a; }
        .command-usage { font-family: monospace; color: #8a8aaa; font-size: 0.75rem; }
        .command-desc { color: #666; font-size: 0.7rem; margin-top: 0.2rem; }
        /* System message style */
        .system { background: #1a2a3a; border-left: 3px solid #4a8aaa; font-family: monospace; font-size: 0.85rem; }
        .system pre { color: #aaccee; }
        /* Pipeline viewer */
        #pipeline { background: #0a0a1a; border-bottom: 1px solid #333; }
        #pipeline-stages { overflow: hidden; max-height: 200px; transition: max-height 0.2s ease; }
        #pipeline.collapsed #pipeline-stages { max-height: 0; padding: 0 1rem; }
        #pipeline-header { display: flex; align-items: center; justify-content: space-between; padding: 0.4rem 1rem; cursor: pointer; }
        #pipeline-header:hover { background: #12121f; }
        #pipeline-title { font-size: 0.7rem; color: #666; text-transform: uppercase; letter-spacing: 0.05em; }
        #pipeline-toggle { background: none; border: none; color: #555; cursor: pointer; font-size: 0.8rem; padding: 0.2rem; }
        #pipeline-stages { display: flex; gap: 0.25rem; padding: 0 1rem 0.5rem 1rem; align-items: center; flex-wrap: wrap; }
        .pipeline-arrow { color: #333; font-size: 0.7rem; }
        .pipeline-stage { background: #1a1a2e; border-radius: 8px; padding: 0.6rem 0.9rem; min-width: 110px; border-left: 4px solid #555; cursor: pointer; transition: background 0.15s; }
        .pipeline-stage:hover { background: #2a2a4a; }
        .pipeline-stage.green { border-left-color: #4a8; }
        .pipeline-stage.yellow { border-left-color: #a84; }
        .pipeline-stage.orange { border-left-color: #a64; }
        .pipeline-stage.red { border-left-color: #a44; }
        .pipeline-stage.gray { border-left-color: #555; }
        .stage-name { font-size: 0.75rem; color: #888; text-transform: uppercase; letter-spacing: 0.03em; }
        .stage-count { font-size: 1.1rem; color: #ccc; font-weight: 500; }
        .stage-unit { font-size: 0.7rem; color: #666; font-weight: normal; }
        .stage-extra { font-size: 0.65rem; color: #666; margin-top: 0.15rem; }
        .stage-time { font-size: 0.65rem; color: #555; margin-top: 0.15rem; }
    </style>
</head>
<body>
    <div id="sidebar">
        <button id="new-session" onclick="newSession()">+ New Chat</button>
        <div id="sessions-list"></div>
        <label id="archive-toggle"><input type="checkbox" id="show-archived" onchange="loadSessions()"> Show archived</label>
        <div id="commands-panel">
            <div class="panel-header">Commands</div>
            <div id="commands-list"></div>
        </div>
    </div>
    <div id="main">
        <div id="pipeline">
            <div id="pipeline-header" onclick="togglePipeline()">
                <span id="pipeline-title">Pipeline</span>
                <button id="pipeline-toggle">▼</button>
            </div>
            <div id="pipeline-stages"></div>
        </div>
        <div id="chat"></div>
        <div id="input-area">
            <input id="prompt" type="text" placeholder="Ask Claude..." autofocus>
            <button id="send">Send</button>
            <button id="stop" style="display:none;">Stop</button>
        </div>
        <div id="debug">
            <div>Session: <span id="session-display">-</span></div>
            <div>Model: <select id="model-select"></select></div>
        </div>
    </div>
    <script>
        const chat = document.getElementById('chat');
        const promptInput = document.getElementById('prompt');
        const sendBtn = document.getElementById('send');
        const stopBtn = document.getElementById('stop');
        const modelSelect = document.getElementById('model-select');

        // Check URL for session param, otherwise create new
        const urlParams = new URLSearchParams(window.location.search);
        let sessionId = urlParams.get('session') || crypto.randomUUID();
        let currentAssistant = null;
        let currentToolContainer = null;
        let abortController = null;

        function setRunningState(running) {
            sendBtn.disabled = running;
            promptInput.disabled = running;
            sendBtn.style.display = running ? 'none' : 'block';
            stopBtn.style.display = running ? 'block' : 'none';
            promptInput.placeholder = running ? 'Running...' : 'Ask Claude...';
        }

        async function stopRequest() {
            // Client-side abort
            if (abortController) {
                abortController.abort();
                abortController = null;
            }
            // Server-side abort
            try {
                await fetch('/session/' + sessionId + '/abort', { method: 'POST' });
            } catch (e) {
                console.log('Abort request failed:', e);
            }
            setRunningState(false);
            promptInput.focus();
        }

        stopBtn.onclick = stopRequest;

        function addToolMsg(text) {
            if (!currentToolContainer) {
                currentToolContainer = document.createElement('div');
                currentToolContainer.className = 'tool-container';
                chat.appendChild(currentToolContainer);
            }
            const div = document.createElement('div');
            div.className = 'tool';
            div.innerHTML = '<pre>' + text + '</pre>';
            currentToolContainer.appendChild(div);
            currentToolContainer.scrollTop = currentToolContainer.scrollHeight;
            chat.scrollTop = chat.scrollHeight;
        }

        function closeToolContainer() {
            currentToolContainer = null;
        }
        let sessionStarted = false;  // Track if session has messages
        let pipelineCollapsed = localStorage.getItem('pipelineCollapsed') === 'true';

        function togglePipeline() {
            pipelineCollapsed = !pipelineCollapsed;
            localStorage.setItem('pipelineCollapsed', pipelineCollapsed);
            updatePipelineVisibility();
        }

        function updatePipelineVisibility() {
            const pipeline = document.getElementById('pipeline');
            const toggle = document.getElementById('pipeline-toggle');
            if (pipelineCollapsed) {
                pipeline.classList.add('collapsed');
                toggle.textContent = '▶';
            } else {
                pipeline.classList.remove('collapsed');
                toggle.textContent = '▼';
            }
        }

        function getFreshnessColor(isoTimestamp) {
            if (!isoTimestamp) return 'gray';
            const now = new Date();
            const then = new Date(isoTimestamp);
            const hoursAgo = (now - then) / (1000 * 60 * 60);
            if (hoursAgo < 24) return 'green';
            if (hoursAgo < 72) return 'yellow';
            return 'orange';
        }

        function formatTimeAgo(isoTimestamp) {
            if (!isoTimestamp) return 'never';
            const now = new Date();
            const then = new Date(isoTimestamp);
            const hoursAgo = Math.floor((now - then) / (1000 * 60 * 60));
            if (hoursAgo < 1) return 'just now';
            if (hoursAgo < 24) return hoursAgo + 'h ago';
            const daysAgo = Math.floor(hoursAgo / 24);
            if (daysAgo === 1) return '1 day ago';
            return daysAgo + ' days ago';
        }

        function formatBreakdown(breakdown) {
            if (!breakdown || Object.keys(breakdown).length === 0) return '';
            return Object.entries(breakdown)
                .map(([k, v]) => k + ':' + v.toLocaleString())
                .join(' ');
        }

        async function loadPipeline() {
            try {
                const res = await fetch('/pipeline/stats');
                const data = await res.json();
                const stages = ['discover', 'scrape', 'filter', 'targets', 'contacts', 'outreach'];
                const labels = {discover: 'Discover', scrape: 'Scrape', filter: 'Filter', targets: 'Targets', contacts: 'Contacts', outreach: 'Outreach'};
                const container = document.getElementById('pipeline-stages');

                container.innerHTML = stages.map((stage, i) => {
                    const info = data[stage] || {count: 0, last_run: null};
                    const color = getFreshnessColor(info.last_run);
                    const time = formatTimeAgo(info.last_run);
                    const arrow = i < stages.length - 1 ? '<span class="pipeline-arrow">→</span>' : '';
                    const unit = info.unit || '';

                    // Build extra info line
                    let extra = '';
                    if (stage === 'scrape' && info.breakdown) {
                        extra = '<div class="stage-extra">' + formatBreakdown(info.breakdown) + '</div>';
                    } else if (stage === 'filter' && info.pass_rate !== undefined) {
                        extra = '<div class="stage-extra">' + info.pass_rate + '% of ' + (info.evaluated || 0).toLocaleString() + '</div>';
                    }

                    return '<div class="pipeline-stage ' + color + '" onclick="window.open(\\'/view/' + stage + '\\', \\'_blank\\')">' +
                        '<div class="stage-name">' + labels[stage] + '</div>' +
                        '<div class="stage-count">' + (info.count || 0).toLocaleString() + ' <span class="stage-unit">' + unit + '</span></div>' +
                        extra +
                        '<div class="stage-time">' + time + '</div>' +
                        '</div>' + arrow;
                }).join('');

                updatePipelineVisibility();
            } catch (e) {
                console.log('Failed to load pipeline:', e);
            }
        }

        async function loadModels() {
            try {
                const res = await fetch('/models');
                const data = await res.json();
                modelSelect.innerHTML = data.models.map(m => {
                    // Extract just the model name (e.g., "haiku-4-5" from "claude-haiku-4-5-20251001")
                    const parts = m.replace('claude-', '').split('-');
                    const shortName = parts.slice(0, -1).join('-'); // Remove date suffix
                    return '<option value="' + m + '"' + (m === data.default ? ' selected' : '') + '>' + shortName + '</option>';
                }).join('');
            } catch (e) {
                console.log('Failed to load models:', e);
                modelSelect.innerHTML = '<option value="claude-haiku-4-5-20251001">haiku-4-5</option>';
            }
        }

        function addMsg(text, cls) {
            const div = document.createElement('div');
            div.className = 'msg ' + cls;
            const pre = document.createElement('pre');
            pre.textContent = text;
            div.appendChild(pre);
            chat.appendChild(div);
            chat.scrollTop = chat.scrollHeight;
            return div;
        }

        async function loadHistory() {
            const loadingMsg = addMsg('Loading session', 'loading');
            try {
                const res = await fetch('/history/' + sessionId);
                const data = await res.json();
                loadingMsg.remove();
                if (data.history && data.history.length > 0) {
                    sessionStarted = true;
                    for (const msg of data.history) {
                        const cls = msg.role === 'user' ? 'user' : (msg.role === 'system' ? 'system' : 'assistant');
                        addMsg(msg.content, cls);
                    }
                }
                // Try to get session's model (may be unknown if server restarted)
                const sessionRes = await fetch('/session/' + sessionId);
                const sessionData = await sessionRes.json();
                if (sessionData.model) {
                    modelSelect.value = sessionData.model;
                }
            } catch (e) {
                loadingMsg.remove();
                console.log('Failed to load history:', e);
            }
        }

        async function loadSessions() {
            try {
                const showArchived = document.getElementById('show-archived').checked;
                const res = await fetch('/sessions?include_archived=' + showArchived);
                const data = await res.json();
                const container = document.getElementById('sessions-list');
                if (data.sessions.length === 0) {
                    container.innerHTML = '<div class="no-sessions">' + (showArchived ? 'No sessions' : 'No active sessions') + '</div>';
                    return;
                }
                container.innerHTML = data.sessions.map(s => {
                    const isArchived = s.is_archived;
                    const classes = 'session-link' + (s.id === sessionId ? ' active' : '') + (isArchived ? ' archived' : '');
                    const icon = isArchived ? '↩' : '×';
                    const btnAction = isArchived ? 'false' : 'true';
                    return '<a href="/?session=' + s.id + '" class="' + classes + '">' +
                        '<div class="session-content">' +
                        '<span class="session-preview">' + (s.preview || 'New chat') + '</span>' +
                        '<span class="session-count">' + s.messages + ' msgs</span>' +
                        '</div>' +
                        '<button class="archive-btn" onclick="archiveSession(event, \\'' + s.id + '\\', ' + btnAction + ')">' + icon + '</button>' +
                        '</a>';
                }).join('');
            } catch (e) {
                console.log('Failed to load sessions:', e);
            }
        }

        async function archiveSession(event, id, archive) {
            event.preventDefault();
            event.stopPropagation();
            try {
                await fetch('/sessions/' + id + '/archive', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({archive: archive})
                });
                loadSessions();
            } catch (e) {
                console.log('Failed to archive session:', e);
            }
        }

        async function loadCommands() {
            try {
                const res = await fetch('/commands');
                const data = await res.json();
                const container = document.getElementById('commands-list');
                container.innerHTML = data.commands.map(cmd =>
                    '<div class="command-item" onclick="fillCommand(\\'' + cmd.usage.split(' ')[0] + ' \\')">' +
                    '<div class="command-usage">' + cmd.usage + '</div>' +
                    '<div class="command-desc">' + cmd.description + '</div>' +
                    '</div>'
                ).join('');
            } catch (e) {
                console.log('Failed to load commands:', e);
            }
        }

        function fillCommand(cmd) {
            promptInput.value = cmd;
            promptInput.focus();
        }

        async function runCommand(text) {
            addMsg(text, 'user');
            promptInput.value = '';
            setRunningState(true);
            sessionStarted = true;

            // Create system message for progress
            let systemMsg = null;
            abortController = new AbortController();

            try {
                const response = await fetch('/command/' + sessionId, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: text }),
                    signal: abortController.signal
                });

                if (!response.ok) {
                    throw new Error('Server error: ' + response.status);
                }

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split(/\\r?\\n/);
                    buffer = lines.pop() || '';

                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.slice(6));
                                if (data.type === 'progress' || data.type === 'done') {
                                    if (!systemMsg) {
                                        systemMsg = addMsg('', 'system');
                                    }
                                    const pre = systemMsg.querySelector('pre');
                                    if (pre.textContent) pre.textContent += '\\n';
                                    pre.textContent += data.text;
                                    chat.scrollTop = chat.scrollHeight;
                                } else if (data.type === 'error') {
                                    addMsg('Error: ' + data.text, 'error');
                                }
                            } catch (e) {
                                console.log('Parse error:', e, line);
                            }
                        }
                    }
                }
                loadSessions(); // Refresh session list
            } catch (err) {
                if (err.name !== 'AbortError') {
                    addMsg('Error: ' + err.message, 'error');
                }
            } finally {
                abortController = null;
                setRunningState(false);
                promptInput.focus();
            }
        }

        async function sendMessage() {
            const text = promptInput.value.trim();
            if (!text) return;

            // Route slash commands to command handler
            if (text.startsWith('/')) {
                return runCommand(text);
            }

            addMsg(text, 'user');
            promptInput.value = '';
            setRunningState(true);
            currentAssistant = null;
            currentToolContainer = null;

            sessionStarted = true;
            abortController = new AbortController();

            // Show loading indicator
            const loadingMsg = addMsg('Thinking', 'loading');

            try {
                const response = await fetch('/chat/' + sessionId, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: text, model: modelSelect.value }),
                    signal: abortController.signal
                });

                if (!response.ok) {
                    throw new Error('Server error: ' + response.status);
                }

                // Remove loading indicator once we start receiving
                let loadingRemoved = false;
                function removeLoading() {
                    if (!loadingRemoved) {
                        loadingMsg.remove();
                        loadingRemoved = true;
                    }
                }

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split(/\\r?\\n/);
                    buffer = lines.pop() || '';

                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.slice(6));
                                if (data.status) {
                                    // Update thinking indicator
                                    const pre = loadingMsg.querySelector('pre');
                                    if (pre) pre.textContent = data.status;
                                } else if (data.text) {
                                    removeLoading();
                                    closeToolContainer();
                                    if (!currentAssistant) {
                                        currentAssistant = addMsg('', 'assistant');
                                    }
                                    currentAssistant.querySelector('pre').textContent += data.text;
                                    chat.scrollTop = chat.scrollHeight;
                                } else if (data.tool) {
                                    removeLoading();
                                    addToolMsg('🔧 ' + data.tool + ': ' + data.input);
                                } else if (data.result) {
                                    addToolMsg('✓ ' + data.result.slice(0, 300));
                                } else if (data.error) {
                                    removeLoading();
                                    closeToolContainer();
                                    addMsg('Error: ' + data.error, 'error');
                                } else if (data.done) {
                                    removeLoading();
                                    closeToolContainer();
                                    loadSessions(); // Refresh session list
                                }
                            } catch (e) {
                                console.log('Parse error:', e, line);
                            }
                        }
                    }
                }
                removeLoading(); // Ensure removed if no events
            } catch (err) {
                loadingMsg.remove();
                if (err.name !== 'AbortError') {
                    addMsg('Error: ' + err.message, 'error');
                }
            } finally {
                abortController = null;
                setRunningState(false);
                promptInput.focus();
            }
        }

        function newSession() {
            window.location.href = '/';
        }

        sendBtn.onclick = sendMessage;
        promptInput.onkeydown = e => { if (e.key === 'Enter') sendMessage(); };
        document.getElementById('session-display').textContent = sessionId.slice(0, 8);

        // Initialize: load models, commands, pipeline, then history/sessions
        Promise.all([loadModels(), loadCommands(), loadPipeline()]).then(() => {
            if (urlParams.get('session')) {
                loadHistory().then(loadSessions);
            } else {
                // Update URL with new session ID
                history.replaceState(null, '', '/?session=' + sessionId);
                loadSessions();
            }
        });
    </script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the chat interface."""
    return HTML


@app.get("/health")
async def health():
    """Health check endpoint for Railway."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
