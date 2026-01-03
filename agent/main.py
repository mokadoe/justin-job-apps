"""Minimal Claude Agent SDK + FastAPI + SSE streaming chat."""

import json
import asyncio
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

app = FastAPI()

# Store active sessions, locks, and chat history
sessions: dict[str, ClaudeSDKClient] = {}
session_locks: dict[str, asyncio.Lock] = {}
chat_history: dict[str, list[dict]] = {}  # session_id -> [{role, content}, ...]


def get_options():
    return ClaudeAgentOptions(
        model="claude-haiku-4-5-20251001",
        allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep","WebSearch","WebFetch"],
        permission_mode="acceptEdits",
    )


async def get_or_create_session(session_id: str) -> ClaudeSDKClient:
    """Get existing session or create new one."""
    if session_id not in session_locks:
        session_locks[session_id] = asyncio.Lock()

    async with session_locks[session_id]:
        if session_id not in sessions:
            print(f"[{session_id[:8]}] Creating NEW session")
            client = ClaudeSDKClient(get_options())
            await client.connect()
            sessions[session_id] = client
        else:
            print(f"[{session_id[:8]}] REUSING existing session")
        return sessions[session_id]


async def collect_response(session_id: str, prompt: str) -> list[dict]:
    """Collect Claude's response messages."""
    print(f"[{session_id[:8]}] Starting request: {prompt[:50]}...")
    events = []

    # Initialize chat history for this session
    if session_id not in chat_history:
        chat_history[session_id] = []

    # Store user message
    chat_history[session_id].append({"role": "user", "content": prompt})

    try:
        client = await get_or_create_session(session_id)
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
            chat_history[session_id].append({"role": "assistant", "content": assistant_text})

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
    # Collect all events first, then stream them (avoids generator issues)
    events = await collect_response(session_id, prompt)
    return EventSourceResponse(stream_events(events))


@app.delete("/session/{session_id}")
async def end_session(session_id: str):
    """End a chat session."""
    if session_id in sessions:
        await sessions[session_id].disconnect()
        del sessions[session_id]
        return {"status": "closed"}
    return {"status": "not_found"}


@app.get("/session/{session_id}")
async def check_session(session_id: str):
    """Check if a session exists in memory."""
    if session_id in sessions:
        return {"exists": True, "session_id": session_id}
    return {"exists": False}


@app.get("/sessions")
async def list_sessions():
    """List all active sessions with preview."""
    result = []
    for sid in sessions.keys():
        history = chat_history.get(sid, [])
        preview = ""
        if history:
            first_user = next((m["content"][:50] for m in history if m["role"] == "user"), "")
            preview = first_user + "..." if len(first_user) == 50 else first_user
        result.append({
            "id": sid,
            "messages": len(history),
            "preview": preview
        })
    return {"sessions": result}


@app.get("/history/{session_id}")
async def get_history(session_id: str):
    """Get chat history for a session."""
    if session_id in chat_history:
        return {"history": chat_history[session_id]}
    return {"history": []}


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
        #input-area { display: flex; padding: 1rem; background: #0a0a1a; gap: 0.5rem; }
        #prompt { flex: 1; padding: 0.75rem; border: 1px solid #444; border-radius: 6px; background: #1a1a2e; color: #eee; font-size: 1rem; }
        #prompt:focus { outline: none; border-color: #6a6aaa; }
        button { padding: 0.75rem 1.5rem; border: none; border-radius: 6px; background: #4a4a8a; color: #fff; cursor: pointer; font-size: 1rem; }
        button:hover { background: #5a5a9a; }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
        pre { white-space: pre-wrap; word-break: break-word; margin: 0; }
        #debug { font-size: 0.7rem; color: #666; padding: 0.25rem 1rem; background: #0a0a1a; font-family: monospace; }
        #debug span { color: #888; }
    </style>
</head>
<body>
    <div id="sidebar">
        <button id="new-session" onclick="newSession()">+ New Chat</button>
        <div id="sessions-list"></div>
    </div>
    <div id="main">
        <div id="chat"></div>
        <div id="input-area">
            <input id="prompt" type="text" placeholder="Ask Claude..." autofocus>
            <button id="send">Send</button>
        </div>
        <div id="debug">Session: <span id="session-display">-</span></div>
    </div>
    <script>
        const chat = document.getElementById('chat');
        const promptInput = document.getElementById('prompt');
        const sendBtn = document.getElementById('send');

        // Check URL for session param, otherwise create new
        const urlParams = new URLSearchParams(window.location.search);
        let sessionId = urlParams.get('session') || crypto.randomUUID();
        let currentAssistant = null;

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
            try {
                const res = await fetch('/history/' + sessionId);
                const data = await res.json();
                if (data.history && data.history.length > 0) {
                    for (const msg of data.history) {
                        addMsg(msg.content, msg.role === 'user' ? 'user' : 'assistant');
                    }
                }
            } catch (e) {
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

        async function sendMessage() {
            const text = promptInput.value.trim();
            if (!text) return;

            addMsg(text, 'user');
            promptInput.value = '';
            sendBtn.disabled = true;
            currentAssistant = null;

            try {
                const response = await fetch('/chat/' + sessionId, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: text })
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
                                if (data.text) {
                                    if (!currentAssistant) {
                                        currentAssistant = addMsg('', 'assistant');
                                    }
                                    currentAssistant.querySelector('pre').textContent += data.text;
                                    chat.scrollTop = chat.scrollHeight;
                                } else if (data.tool) {
                                    addMsg('🔧 ' + data.tool + ': ' + data.input, 'tool');
                                } else if (data.result) {
                                    addMsg('✓ ' + data.result.slice(0, 300), 'tool');
                                } else if (data.error) {
                                    addMsg('Error: ' + data.error, 'error');
                                } else if (data.done) {
                                    loadSessions(); // Refresh session list
                                }
                            } catch (e) {
                                console.log('Parse error:', e, line);
                            }
                        }
                    }
                }
            } catch (err) {
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

        // Load history if resuming, then load session list
        if (urlParams.get('session')) {
            loadHistory().then(loadSessions);
        } else {
            // Update URL with new session ID
            history.replaceState(null, '', '/?session=' + sessionId);
            loadSessions();
        }
    </script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the chat interface."""
    return HTML


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
