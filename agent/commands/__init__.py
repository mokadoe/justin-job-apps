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
