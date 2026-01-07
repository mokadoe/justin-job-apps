"""
Generate command - create outreach email drafts.

Usage:
    /generate all                    - Generate emails for all companies with priority contacts
    /generate one <company_name>     - Generate email for a specific company by name
"""

import asyncio
import queue
import threading
from . import register


@register(
    "generate",
    description="Generate outreach email drafts",
    usage="/generate all | /generate one <company_name>"
)
async def handle_generate(args: str):
    """Handle /generate command."""
    parts = args.split()
    action = parts[0].lower() if parts else ""

    if not action:
        yield {"type": "error", "text": "Usage: /generate all | /generate one <company_name>"}
        return

    if action == "all":
        async for event in run_generate_all():
            yield event

    elif action == "one":
        # Get company name from remaining args
        remaining = parts[1:]
        if not remaining:
            yield {"type": "error", "text": "Usage: /generate one <company_name>"}
            return
        company_name = " ".join(remaining)

        async for event in run_generate_one(company_name):
            yield event

    else:
        yield {"type": "error", "text": f"Unknown action: {action}. Use 'all' or 'one'"}


async def run_generate_all():
    """Generate emails for all companies with priority contacts."""
    yield {"type": "progress", "text": "Starting message generation..."}

    progress_queue = queue.Queue()
    stats = {}
    done_event = threading.Event()
    error = None

    def run_generation():
        nonlocal stats, error
        try:
            from outreach.generate_messages import generate_all

            # Capture stdout
            class QueueWriter:
                def write(self, text):
                    if text.strip():
                        progress_queue.put(text.rstrip())

                def flush(self):
                    pass

            import sys
            old_stdout = sys.stdout
            sys.stdout = QueueWriter()

            try:
                stats = generate_all()
            finally:
                sys.stdout = old_stdout

        except Exception as e:
            error = str(e)
            import traceback
            traceback.print_exc()
        finally:
            done_event.set()

    thread = threading.Thread(target=run_generation)
    thread.start()

    # Stream progress
    while not done_event.is_set():
        try:
            while True:
                msg = progress_queue.get_nowait()
                yield {"type": "progress", "text": msg}
        except queue.Empty:
            pass
        await asyncio.sleep(0.2)

    # Drain remaining
    while not progress_queue.empty():
        msg = progress_queue.get_nowait()
        yield {"type": "progress", "text": msg}

    thread.join()

    if error:
        yield {"type": "error", "text": f"Generation failed: {error}"}
        return

    yield {"type": "progress", "text": "=" * 50}
    yield {"type": "done", "text": f"Done! Generated: {stats.get('generated', 0)}, Skipped: {stats.get('skipped', 0)}, Failed: {stats.get('failed', 0)}"}


async def run_generate_one(company_name: str):
    """Generate email for a specific company by name."""
    yield {"type": "progress", "text": f"Generating message for '{company_name}'..."}

    progress_queue = queue.Queue()
    result = {}
    done_event = threading.Event()
    error = None

    def run_generation():
        nonlocal result, error
        try:
            from outreach.generate_messages import generate_for_company

            # Capture stdout
            class QueueWriter:
                def write(self, text):
                    if text.strip():
                        progress_queue.put(text.rstrip())

                def flush(self):
                    pass

            import sys
            old_stdout = sys.stdout
            sys.stdout = QueueWriter()

            try:
                result = generate_for_company(company_name) or {}
            finally:
                sys.stdout = old_stdout

        except Exception as e:
            error = str(e)
            import traceback
            traceback.print_exc()
        finally:
            done_event.set()

    thread = threading.Thread(target=run_generation)
    thread.start()

    # Stream progress
    while not done_event.is_set():
        try:
            while True:
                msg = progress_queue.get_nowait()
                yield {"type": "progress", "text": msg}
        except queue.Empty:
            pass
        await asyncio.sleep(0.2)

    # Drain remaining
    while not progress_queue.empty():
        msg = progress_queue.get_nowait()
        yield {"type": "progress", "text": msg}

    thread.join()

    if error:
        yield {"type": "error", "text": f"Generation failed: {error}"}
        return

    if not result:
        yield {"type": "error", "text": f"Company '{company_name}' not found"}
        return

    if result.get('message'):
        yield {"type": "progress", "text": "-" * 40}
        yield {"type": "progress", "text": result['message']}
        yield {"type": "progress", "text": "-" * 40}

    status = "Generated new message" if result.get('created') else "Using existing message"
    yield {"type": "done", "text": f"{status} for {result.get('company')}"}
