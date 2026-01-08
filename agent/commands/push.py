"""
Push command - push messages to email.

Usage:
    /push email <job_id>            - Create Gmail draft for job
    /push email <job_id> --preview  - Preview without creating draft
"""

import asyncio
import queue
import threading
from . import register


def _create_runner(func, *args, **kwargs):
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
                result = func(*args, **kwargs) or {}
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
    "push",
    description="Push messages to email",
    usage="/push email <job_id> [--preview]"
)
async def handle_push(args: str):
    """Handle /push command."""
    parts = args.split()
    action = parts[0].lower() if parts else ""

    if not action:
        yield {"type": "error", "text": "Usage: /push email <job_id> [--preview]"}
        return

    if action == "email":
        # Parse arguments
        preview = "--preview" in parts
        remaining = [p for p in parts[1:] if not p.startswith("--")]

        if not remaining or not remaining[0].isdigit():
            yield {"type": "error", "text": "Usage: /push email <job_id> [--preview]"}
            return

        job_id = int(remaining[0])
        async for event in run_push_email(job_id, preview=preview):
            yield event

    else:
        yield {"type": "error", "text": f"Unknown action: {action}. Use 'email'"}


async def run_push_email(job_id: int, preview: bool = False):
    """Push email for a specific job."""
    mode = "preview" if preview else "draft creation"
    yield {"type": "progress", "text": f"Starting {mode} for job ID {job_id}..."}

    from outreach.push_email import push_email_draft, format_preview
    run, progress_queue, done_event, get_result = _create_runner(
        push_email_draft, job_id, preview=preview
    )

    thread = threading.Thread(target=run)
    thread.start()

    async for event in _stream_progress(progress_queue, done_event):
        yield event

    thread.join()
    result, error = get_result()

    if error:
        yield {"type": "error", "text": f"Push failed: {error}"}
        return

    if not result.get('success'):
        yield {"type": "error", "text": result.get('error', 'Unknown error')}
        return

    if preview:
        # Format and show preview
        preview_data = result['preview']
        yield {"type": "progress", "text": "=" * 50}
        yield {"type": "progress", "text": f"To: {', '.join(preview_data['to'])}"}
        yield {"type": "progress", "text": f"Subject: {preview_data['subject']}"}
        yield {"type": "progress", "text": "-" * 50}
        # Show plain text message
        for line in preview_data['plain_text'].split('\n'):
            yield {"type": "progress", "text": line}
        yield {"type": "progress", "text": "=" * 50}
        yield {"type": "done", "text": "Preview complete. Run without --preview to create draft."}
    else:
        draft = result['draft']
        yield {"type": "progress", "text": "=" * 50}
        yield {"type": "done", "text": f"Draft created! Open: {draft['link']}"}
