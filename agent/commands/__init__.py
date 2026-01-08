"""
Command registry and dispatcher for slash commands.

Usage:
    from commands import dispatch, list_commands

    # In your command module:
    from commands import register

    @register("mycommand",
              description="What it does",
              usage="/mycommand <arg>")
    async def handle_mycommand(args: str):
        yield {"type": "progress", "text": "Working..."}
        yield {"type": "done", "text": "Complete!"}
"""

import sys
import asyncio
from pathlib import Path
from typing import AsyncGenerator, Callable
from io import StringIO
from contextlib import redirect_stdout
import threading

# Add src/ to path for scraper imports
SRC_PATH = Path(__file__).parent.parent.parent / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

# Command registry: name -> {handler, description, usage}
COMMANDS: dict[str, dict] = {}


def register(name: str, description: str, usage: str):
    """
    Decorator to register a slash command.

    The handler should be an async generator that yields dicts with:
        {"type": "progress", "text": "..."}  - Progress update
        {"type": "done", "text": "..."}      - Final result
        {"type": "error", "text": "..."}     - Error message
    """
    def decorator(fn: Callable):
        COMMANDS[name] = {
            "handler": fn,
            "description": description,
            "usage": usage,
        }
        return fn
    return decorator


def list_commands() -> list[dict]:
    """Return command metadata for UI display."""
    return [
        {
            "name": name,
            "description": cmd["description"],
            "usage": cmd["usage"],
        }
        for name, cmd in COMMANDS.items()
    ]


async def dispatch(text: str) -> AsyncGenerator[dict, None]:
    """
    Parse input and dispatch to appropriate command handler.

    Yields progress events from the command handler.
    """
    if not text.startswith("/"):
        yield {"type": "error", "text": "Not a command (must start with /)"}
        return

    # Parse command and args
    text = text[1:]  # Remove leading /
    parts = text.split(maxsplit=1)
    cmd_name = parts[0].lower() if parts else ""
    args = parts[1] if len(parts) > 1 else ""

    if not cmd_name:
        yield {"type": "error", "text": "Empty command"}
        return

    if cmd_name not in COMMANDS:
        available = ", ".join(f"/{name}" for name in COMMANDS.keys())
        yield {"type": "error", "text": f"Unknown command: /{cmd_name}. Available: {available}"}
        return

    # Dispatch to handler
    handler = COMMANDS[cmd_name]["handler"]
    try:
        async for event in handler(args):
            yield event
    except Exception as e:
        yield {"type": "error", "text": f"Command failed: {str(e)}"}


def run_sync_with_output(fn: Callable, *args, **kwargs) -> AsyncGenerator[str, None]:
    """
    Run a synchronous function that uses print() and yield output lines.

    This captures stdout from the function and yields each line.
    Returns an async generator for use in command handlers.
    """
    async def generator():
        output_lines = []
        result = None
        exception = None

        def run_in_thread():
            nonlocal result, exception
            # Capture stdout
            captured = StringIO()
            try:
                with redirect_stdout(captured):
                    result = fn(*args, **kwargs)
            except Exception as e:
                exception = e
            finally:
                # Get all output
                captured.seek(0)
                for line in captured:
                    output_lines.append(line.rstrip())

        # Run in thread to not block
        loop = asyncio.get_event_loop()
        thread = threading.Thread(target=run_in_thread)
        thread.start()

        # Poll for output while thread runs
        last_seen = 0
        while thread.is_alive():
            await asyncio.sleep(0.1)
            # Yield any new lines
            while last_seen < len(output_lines):
                yield output_lines[last_seen]
                last_seen += 1

        thread.join()

        # Yield any remaining lines
        while last_seen < len(output_lines):
            yield output_lines[last_seen]
            last_seen += 1

        if exception:
            raise exception

    return generator()


# Import command modules to register them
from . import scrape
from . import jobs
from . import filter
from . import discover
from . import generate
from . import push


# ============================================================
# Documentation generation (for CLAUDE.md and system prompts)
# ============================================================

import os

AGENT_PATH = Path(__file__).parent.parent.resolve()


def generate_db_access_docs() -> str:
    """Generate database access instructions based on current environment.

    Checks USE_REMOTE_DB and RAILWAY_ENVIRONMENT to determine which DB is active.
    """
    use_remote = (
        os.environ.get("RAILWAY_ENVIRONMENT") or
        os.environ.get("USE_REMOTE_DB", "").lower() == "true"
    )

    if use_remote:
        return """## Database Access

**Environment:** Railway PostgreSQL (all tables in one database)

```bash
# Run a query
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM companies;"

# Interactive session
psql "$DATABASE_URL"
```

**Tables:** sessions, chat_messages, companies, jobs, target_jobs, contacts, messages

**Examples:**
```bash
# Job stats
psql "$DATABASE_URL" -c "SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE evaluated) as evaluated FROM jobs;"

# Pending targets
psql "$DATABASE_URL" -c "SELECT j.job_title, c.name FROM target_jobs t JOIN jobs j ON t.job_id = j.id JOIN companies c ON j.company_id = c.id WHERE t.status = 1;"

# Companies by platform
psql "$DATABASE_URL" -c "SELECT ats_platform, COUNT(*) FROM companies GROUP BY ats_platform;"
```

See [db_setup.md](db_setup.md) for full schema."""
    else:
        return """## Database Access

**Environment:** Local SQLite (two separate database files)

| Database | Path | Tables |
|----------|------|--------|
| Jobs | `data/jobs.db` | companies, jobs, target_jobs, contacts, messages |
| Chat | `agent/data/chat.db` | sessions, chat_messages |

```bash
# Jobs database
sqlite3 data/jobs.db "SELECT COUNT(*) FROM companies;"

# Chat database
sqlite3 agent/data/chat.db "SELECT COUNT(*) FROM sessions;"
```

**Examples:**
```bash
# Job stats
sqlite3 data/jobs.db "SELECT COUNT(*) as total, SUM(evaluated) as evaluated FROM jobs;"

# Pending targets
sqlite3 data/jobs.db "SELECT j.job_title, c.name FROM target_jobs t JOIN jobs j ON t.job_id = j.id JOIN companies c ON j.company_id = c.id WHERE t.status = 1;"

# Companies by platform
sqlite3 data/jobs.db "SELECT ats_platform, COUNT(*) FROM companies GROUP BY ats_platform;"

# Show tables
sqlite3 data/jobs.db ".tables"
sqlite3 data/jobs.db ".schema companies"
```

See [db_setup.md](db_setup.md) for full schema."""


def generate_command_docs() -> str:
    """Generate markdown documentation for all registered commands.

    Used by:
    - Agent SDK system prompt
    - CLAUDE.md generation
    """
    lines = []

    for name, cmd in COMMANDS.items():
        lines.append(f"### /{name}")
        lines.append(f"{cmd['description']}")
        lines.append("```")
        lines.append(cmd['usage'])
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def generate_dispatch_snippet() -> str:
    """Generate Python snippet for running commands programmatically."""
    return f'''```python
import asyncio
from commands import dispatch

async def run(cmd: str):
    async for event in dispatch(cmd):
        print(f"{{event['type']}}: {{event['text']}}")

# Example: asyncio.run(run('/jobs stats'))
```'''


def generate_system_prompt() -> str:
    """Generate complete system prompt for Claude Agent SDK.

    This is used in main.py to give Claude awareness of job pipeline commands.
    """
    return f"""You have access to job pipeline commands and direct database access.

## Running Commands

Commands can be run in two ways:

**1. Direct dispatch (recommended):**
{generate_dispatch_snippet()}

**2. Via Bash:**
```bash
cd {AGENT_PATH} && python3 -c "
import asyncio
from commands import dispatch
async def run():
    async for e in dispatch('/jobs stats'):
        print(e['text'])
asyncio.run(run())
"
```

## Available Commands

{generate_command_docs()}

{generate_db_access_docs()}

Use these commands when the user asks about jobs, companies, scraping, or filtering.
For custom queries, use the database access commands above.
"""


def generate_claude_md() -> str:
    """Generate CLAUDE.md by combining CLAUDE_HEADER.md + auto-generated command docs.

    Called by main.py lifespan() on server startup.
    """
    header_path = AGENT_PATH / "CLAUDE_HEADER.md"

    # Read static header if it exists
    header = ""
    if header_path.exists():
        header = header_path.read_text().strip()

    # Auto-generated sections
    commands_section = f"""## Commands

> Auto-generated from command registry. Do not edit manually.

Commands can be triggered via:
1. **Web UI**: Type `/filter 100` in chat
2. **Programmatically**: Use `dispatch()` function

{generate_dispatch_snippet()}

### Available Commands

{generate_command_docs()}"""

    # Database access (environment-specific)
    db_section = generate_db_access_docs()

    return f"""<!--
  AUTO-GENERATED - DO NOT EDIT THIS FILE

  This file is regenerated on server startup by main.py lifespan().

  To modify:
  - Static content: Edit CLAUDE_HEADER.md
  - Command/DB docs: Auto-generated from commands/__init__.py
-->

{header}

---

{db_section}

---

{commands_section}
"""
