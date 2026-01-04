"""Minimal Claude Agent SDK + FastAPI + SSE streaming chat."""

import os
import json
import asyncio
from contextlib import asynccontextmanager
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
from commands import dispatch as dispatch_command, list_commands


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize databases on startup."""
    await db.init_db()
    await jobs_db.init_jobs_db()
    yield


app = FastAPI(lifespan=lifespan)

# Store active SDK sessions and locks (in-memory, ephemeral)
sessions: dict[str, ClaudeSDKClient] = {}
session_models: dict[str, str] = {}  # Track model per session
session_locks: dict[str, asyncio.Lock] = {}

AVAILABLE_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-5-20251101",
]
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def get_options(model: str = DEFAULT_MODEL, conversation_history: list[dict] = None):
    system_prompt = None
    if conversation_history:
        # Format history as context for the new model
        history_text = "\n".join([
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in conversation_history
        ])
        system_prompt = f"""You are continuing a conversation. Here is the conversation history so far:

<conversation_history>
{history_text}
</conversation_history>

Continue the conversation naturally, taking into account what was discussed above."""

    return ClaudeAgentOptions(
        model=model,
        allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep","WebSearch","WebFetch"],
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


async def stream_events(events: list[dict]):
    """Stream pre-collected events."""
    for event in events:
        yield event


@app.post("/chat/{session_id}")
async def chat(session_id: str, request: Request):
    """Chat endpoint with SSE streaming."""
    body = await request.json()
    prompt = body.get("prompt", "")
    model = body.get("model")  # Optional: only used when creating new session
    # Collect all events first, then stream them (avoids generator issues)
    events = await collect_response(session_id, prompt, model)
    return EventSourceResponse(stream_events(events))


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


@app.get("/models")
async def list_models():
    """List available models."""
    return {"models": AVAILABLE_MODELS, "default": DEFAULT_MODEL}


@app.get("/sessions")
async def list_sessions():
    """List all sessions with preview."""
    sessions_list = await db.get_all_sessions()
    # Add indicator for active SDK connections
    for s in sessions_list:
        s["active"] = s["id"] in sessions
    return {"sessions": sessions_list}


@app.get("/history/{session_id}")
async def get_history(session_id: str):
    """Get chat history for a session."""
    history = await db.get_chat_history(session_id)
    return {"history": history}


@app.get("/commands")
async def get_commands():
    """List available slash commands for UI."""
    return {"commands": list_commands()}


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
        .session-link { display: block; padding: 0.6rem 0.75rem; text-decoration: none; color: #aaa; border-bottom: 1px solid #222; }
        .session-link:hover { background: #1a1a2e; }
        .session-link.active { background: #2a2a4a; color: #fff; }
        .session-id { font-family: monospace; font-size: 0.75rem; color: #666; }
        .session-preview { display: block; font-size: 0.8rem; margin-top: 0.2rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .session-count { font-size: 0.7rem; color: #555; }
        .no-sessions { padding: 1rem; color: #555; font-size: 0.85rem; text-align: center; }
        #main { flex: 1; display: flex; flex-direction: column; }
        #chat { flex: 1; overflow-y: auto; padding: 1rem; }
        .msg { margin: 0.5rem 0; padding: 0.75rem 1rem; border-radius: 8px; max-width: 80%; word-wrap: break-word; }
        .user { background: #4a4a6a; margin-left: auto; }
        .assistant { background: #2a2a4a; }
        .tool { background: #1a3a2a; font-size: 0.85rem; font-family: monospace; }
        .error { background: #4a1a1a; color: #faa; }
        .loading { background: #2a2a4a; color: #888; }
        .loading::after { content: ''; animation: dots 1.5s infinite; }
        @keyframes dots { 0%, 20% { content: '.'; } 40% { content: '..'; } 60%, 100% { content: '...'; } }
        #input-area { display: flex; padding: 1rem; background: #0a0a1a; gap: 0.5rem; }
        #prompt { flex: 1; padding: 0.75rem; border: 1px solid #444; border-radius: 6px; background: #1a1a2e; color: #eee; font-size: 1rem; }
        #prompt:focus { outline: none; border-color: #6a6aaa; }
        button { padding: 0.75rem 1.5rem; border: none; border-radius: 6px; background: #4a4a8a; color: #fff; cursor: pointer; font-size: 1rem; }
        button:hover { background: #5a5a9a; }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
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
    </style>
</head>
<body>
    <div id="sidebar">
        <button id="new-session" onclick="newSession()">+ New Chat</button>
        <div id="sessions-list"></div>
        <div id="commands-panel">
            <div class="panel-header">Commands</div>
            <div id="commands-list"></div>
        </div>
    </div>
    <div id="main">
        <div id="chat"></div>
        <div id="input-area">
            <input id="prompt" type="text" placeholder="Ask Claude..." autofocus>
            <button id="send">Send</button>
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
        const modelSelect = document.getElementById('model-select');

        // Check URL for session param, otherwise create new
        const urlParams = new URLSearchParams(window.location.search);
        let sessionId = urlParams.get('session') || crypto.randomUUID();
        let currentAssistant = null;
        let sessionStarted = false;  // Track if session has messages

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
                const res = await fetch('/sessions');
                const data = await res.json();
                const container = document.getElementById('sessions-list');
                if (data.sessions.length === 0) {
                    container.innerHTML = '<div class="no-sessions">No active sessions</div>';
                    return;
                }
                container.innerHTML = data.sessions.map(s =>
                    '<a href="/?session=' + s.id + '" class="session-link' + (s.id === sessionId ? ' active' : '') + '">' +
                    '<span class="session-id">' + s.id.slice(0, 8) + '</span>' +
                    '<span class="session-preview">' + (s.preview || 'Empty') + '</span>' +
                    '<span class="session-count">' + s.messages + ' msgs</span>' +
                    '</a>'
                ).join('');
            } catch (e) {
                console.log('Failed to load sessions:', e);
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
            sendBtn.disabled = true;
            sessionStarted = true;

            // Create system message for progress
            let systemMsg = null;

            try {
                const response = await fetch('/command/' + sessionId, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: text })
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
                addMsg('Error: ' + err.message, 'error');
            } finally {
                sendBtn.disabled = false;
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
            sendBtn.disabled = true;
            currentAssistant = null;

            sessionStarted = true;

            // Show loading indicator
            const loadingMsg = addMsg('Thinking', 'loading');

            try {
                const response = await fetch('/chat/' + sessionId, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: text, model: modelSelect.value })
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
                                if (data.text) {
                                    removeLoading();
                                    if (!currentAssistant) {
                                        currentAssistant = addMsg('', 'assistant');
                                    }
                                    currentAssistant.querySelector('pre').textContent += data.text;
                                    chat.scrollTop = chat.scrollHeight;
                                } else if (data.tool) {
                                    removeLoading();
                                    addMsg('🔧 ' + data.tool + ': ' + data.input, 'tool');
                                } else if (data.result) {
                                    addMsg('✓ ' + data.result.slice(0, 300), 'tool');
                                } else if (data.error) {
                                    removeLoading();
                                    addMsg('Error: ' + data.error, 'error');
                                } else if (data.done) {
                                    removeLoading();
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
                addMsg('Error: ' + err.message, 'error');
            } finally {
                sendBtn.disabled = false;
                promptInput.focus();
            }
        }

        function newSession() {
            window.location.href = '/';
        }

        sendBtn.onclick = sendMessage;
        promptInput.onkeydown = e => { if (e.key === 'Enter') sendMessage(); };
        document.getElementById('session-display').textContent = sessionId.slice(0, 8);

        // Initialize: load models, commands, then history/sessions
        Promise.all([loadModels(), loadCommands()]).then(() => {
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
