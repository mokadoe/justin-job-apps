"""
Generate command - create outreach email drafts.

Usage:
    /generate all           - Generate for all pending target jobs
    /generate job <job_id>  - Generate for a specific job ID
"""

import asyncio
import queue
import threading
from . import register


def _create_runner(func, *args):
    """Create a threaded runner that captures stdout and returns results."""
    progress_queue = queue.Queue()
    result = {}
    done_event = threading.Event()
    error = None

    def run():
        nonlocal result, error
        try:
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
                result = func(*args) or {}
            finally:
                sys.stdout = old_stdout

        except Exception as e:
            error = str(e)
            import traceback
            traceback.print_exc()
        finally:
            done_event.set()

    return run, progress_queue, done_event, lambda: (result, error)


async def _stream_progress(progress_queue, done_event):
    """Stream progress from a background thread."""
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


@register(
    "generate",
    description="Generate outreach email drafts",
    usage="/generate all | /generate job <id>"
)
async def handle_generate(args: str):
    """Handle /generate command."""
    parts = args.split()
    action = parts[0].lower() if parts else ""

    if not action:
        yield {"type": "error", "text": "Usage: /generate all | /generate job <id>"}
        return

    if action == "all":
        async for event in run_generate_all():
            yield event

    elif action == "job":
        if len(parts) < 2 or not parts[1].isdigit():
            yield {"type": "error", "text": "Usage: /generate job <job_id>"}
            return
        job_id = int(parts[1])
        async for event in run_generate_job(job_id):
            yield event

    else:
        yield {"type": "error", "text": f"Unknown action: {action}. Use 'all' or 'job'"}


async def run_generate_all():
    """Generate for all pending target jobs."""
    yield {"type": "progress", "text": "Starting message generation..."}

    from outreach.generate_messages import generate_all
    run, progress_queue, done_event, get_result = _create_runner(generate_all)

    thread = threading.Thread(target=run)
    thread.start()

    async for event in _stream_progress(progress_queue, done_event):
        yield event

    thread.join()
    result, error = get_result()

    if error:
        yield {"type": "error", "text": f"Generation failed: {error}"}
        return

    yield {"type": "progress", "text": "=" * 50}
    yield {"type": "done", "text": f"Done! Generated: {result.get('generated', 0)}, Skipped: {result.get('skipped', 0)}, Failed: {result.get('failed', 0)}"}


async def run_generate_job(job_id: int):
    """Generate for a specific job."""
    yield {"type": "progress", "text": f"Generating for job ID {job_id}..."}

    from outreach.generate_messages import generate_for_job
    run, progress_queue, done_event, get_result = _create_runner(generate_for_job, job_id)

    thread = threading.Thread(target=run)
    thread.start()

    async for event in _stream_progress(progress_queue, done_event):
        yield event

    thread.join()
    result, error = get_result()

    if error:
        yield {"type": "error", "text": f"Generation failed: {error}"}
        return

    if not result:
        yield {"type": "error", "text": f"Job ID {job_id} not found"}
        return

    yield {"type": "progress", "text": "=" * 50}
    yield {"type": "done", "text": f"Done! {result.get('job_title')}: Generated {result.get('generated', 0)}, Skipped {result.get('skipped', 0)}, Failed {result.get('failed', 0)}"}
