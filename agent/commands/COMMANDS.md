# Adding Slash Commands

> How to add new commands to the agent chat interface.
>
> See [spec.md](../spec.md) for application architecture.
> See [db_setup.md](../db_setup.md) for database access patterns.

## Quick Start

```python
# commands/mycommand.py
from . import register

@register(
    "mycommand",
    description="Short description for UI",
    usage="/mycommand <arg> | /mycommand action"
)
async def handle_mycommand(args: str):
    """Handle /mycommand."""
    yield {"type": "progress", "text": "Working..."}
    # ... do work ...
    yield {"type": "done", "text": "Complete!"}
```

Then add to `commands/__init__.py`:
```python
from . import mycommand  # Add at bottom with other imports
```

## Event Types

Commands yield event dicts that stream to the frontend:

| Type | Purpose | Example |
|------|---------|---------|
| `progress` | Status updates during execution | `{"type": "progress", "text": "Processing 50/100..."}` |
| `done` | Final success message | `{"type": "done", "text": "✓ Completed successfully"}` |
| `error` | Error message (stops execution) | `{"type": "error", "text": "Failed: reason"}` |

## Argument Parsing

The `args` parameter contains everything after the command name:

```
/mycommand foo bar --flag  →  args = "foo bar --flag"
/mycommand                 →  args = ""
```

**Common patterns:**

```python
# Subcommands: /jobs stats, /jobs pending
parts = args.split()
action = parts[0].lower() if parts else ""
if action == "stats":
    async for event in jobs_stats():
        yield event

# Flags: /scrape ashby --force
force = "--force" in args.split()
companies = [p for p in args.split()[1:] if p != "--force"]

# Optional limit: /filter 100
limit = int(args) if args.strip().isdigit() else None
```

## Importing from src/

The `commands/__init__.py` adds `src/` to `sys.path`, so you can import directly:

```python
# Import scrapers
from scrapers.ashby_scraper import fetch_ashby_jobs
from scrapers.ats_mapper import ATSMapper

# Import filters
from filters.filter_jobs import should_reject_with_regex, batch_jobs

# Import discovery
from discovery.discover_contacts import discover_contacts

# Import outreach
from outreach.prepare_outreach import generate_message
```

**Note:** These imports happen at runtime. Put them inside your handler or helper functions, not at module level, if the module has side effects.

## Database Access

Use `jobs_db` for the jobs pipeline database:

```python
async def handle_mycommand(args: str):
    import jobs_db

    # Always init first (idempotent)
    await jobs_db.init_jobs_db()

    # Use async helpers
    stats = await jobs_db.get_stats()
    jobs = await jobs_db.get_unevaluated_jobs(limit=100)
    await jobs_db.mark_jobs_evaluated([job_id])
```

**Key helpers in `jobs_db.py`:**
- `get_stats()` - Database counts
- `get_unevaluated_jobs(limit)` - Jobs needing filtering
- `get_companies_by_platform(platform)` - Companies for scraping
- `upsert_company()`, `upsert_job()` - Insert/update records
- `mark_jobs_evaluated()` - Update evaluated flag

## Running Synchronous Code

For sync functions (like scrapers), use threading to avoid blocking:

```python
import asyncio
import threading

async def scrape_something():
    results = {}
    done = threading.Event()

    def run_scraper():
        nonlocal results
        results = some_sync_function()  # Blocking call
        done.set()

    thread = threading.Thread(target=run_scraper)
    thread.start()

    # Yield progress while waiting
    while not done.is_set():
        yield {"type": "progress", "text": "Still working..."}
        await asyncio.sleep(1)

    thread.join()
    yield {"type": "done", "text": f"Got {len(results)} results"}
```

**For stdout capture**, use `run_sync_with_output()` from `__init__.py`:

```python
from . import run_sync_with_output

async def handle_legacy(args: str):
    async for line in run_sync_with_output(legacy_function_that_prints):
        yield {"type": "progress", "text": line}
    yield {"type": "done", "text": "Complete"}
```

## Parallel Async Operations

Use `asyncio.Semaphore` for concurrent API calls:

```python
async def process_items(items: list):
    semaphore = asyncio.Semaphore(10)  # Max 10 concurrent

    async def process_one(item):
        async with semaphore:
            return await some_async_operation(item)

    tasks = [asyncio.create_task(process_one(i)) for i in items]

    for coro in asyncio.as_completed(tasks):
        result = await coro
        yield {"type": "progress", "text": f"Processed: {result}"}
```

## File Structure

```
agent/commands/
├── __init__.py     # Registry, dispatch(), list_commands(), sys.path setup
├── COMMANDS.md     # This file
├── scrape.py       # /scrape ashby, /scrape simplify
├── filter.py       # /filter, /filter reset
└── jobs.py         # /jobs stats, /jobs pending
```

## Checklist for New Commands

1. [ ] Create `commands/<name>.py` with `@register` decorator
2. [ ] Add import to `commands/__init__.py`
3. [ ] Handler is async generator yielding `{type, text}` dicts
4. [ ] Validate args and yield `error` for invalid input
5. [ ] Use `progress` events for long operations
6. [ ] End with `done` event on success
7. [ ] Test locally: type `/name` in chat interface
8. [ ] Update [spec.md](../spec.md) command table if needed

## Examples

### Simple command (jobs.py pattern)
```python
@register("ping", description="Test command", usage="/ping")
async def handle_ping(args: str):
    yield {"type": "done", "text": "pong"}
```

### Subcommands (jobs.py pattern)
```python
@register("data", description="Data operations", usage="/data export | /data import <file>")
async def handle_data(args: str):
    parts = args.split()
    action = parts[0].lower() if parts else ""

    if action == "export":
        async for event in data_export():
            yield event
    elif action == "import":
        filename = parts[1] if len(parts) > 1 else None
        if not filename:
            yield {"type": "error", "text": "Usage: /data import <file>"}
            return
        async for event in data_import(filename):
            yield event
    else:
        yield {"type": "error", "text": "Usage: /data export | /data import <file>"}
```

### Long-running with progress (scrape.py pattern)
```python
@register("process", description="Process all items", usage="/process [limit]")
async def handle_process(args: str):
    limit = int(args) if args.strip().isdigit() else None

    yield {"type": "progress", "text": "Loading items..."}
    items = get_items(limit=limit)

    for i, item in enumerate(items):
        process(item)
        if (i + 1) % 10 == 0:
            yield {"type": "progress", "text": f"Processed {i+1}/{len(items)}"}

    yield {"type": "done", "text": f"✓ Processed {len(items)} items"}
```
