"""
Discover command - find contacts and companies.

Usage:
    /discover contacts [limit]              - Find contacts for companies with pending jobs
    /discover contacts --use-linkedin       - Use LinkedIn for company sizing (more API calls)
    /discover dork <platform>               - Google dork for new companies (ashby, lever, greenhouse)
"""

import asyncio
import queue
import threading
from . import register


ATS_PLATFORMS = ['ashbyhq', 'lever', 'greenhouse']


@register(
    "discover",
    description="Find contacts and companies",
    usage="/discover contacts [limit] | /discover dork <platform>"
)
async def handle_discover(args: str):
    """Handle /discover command."""
    parts = args.split()
    action = parts[0].lower() if parts else ""

    if not action:
        yield {"type": "error", "text": "Usage: /discover contacts [limit] | /discover dork <platform>"}
        return

    if action == "contacts":
        # Parse options
        use_linkedin = "--use-linkedin" in parts
        remaining = [p for p in parts[1:] if not p.startswith("--")]
        limit = int(remaining[0]) if remaining and remaining[0].isdigit() else 10

        async for event in discover_contacts(limit=limit, use_linkedin=use_linkedin):
            yield event

    elif action == "dork":
        platform = parts[1].lower() if len(parts) > 1 else ""
        if not platform:
            yield {"type": "error", "text": f"Usage: /discover dork <platform>\nAvailable: {', '.join(ATS_PLATFORMS)}"}
            return
        if platform not in ATS_PLATFORMS:
            yield {"type": "error", "text": f"Unknown platform: {platform}. Available: {', '.join(ATS_PLATFORMS)}"}
            return

        async for event in dork_companies(platform):
            yield event

    else:
        yield {"type": "error", "text": f"Unknown action: {action}. Use 'contacts' or 'dork'"}


async def discover_contacts(limit: int = 10, use_linkedin: bool = False):
    """Find contacts for companies with pending jobs.

    Uses Google Custom Search API to find LinkedIn profiles of decision-makers.
    """
    import jobs_db
    from io import StringIO
    from contextlib import redirect_stdout

    yield {"type": "progress", "text": "Loading companies with pending jobs..."}

    # Get companies with pending target jobs
    await jobs_db.init_jobs_db()

    # Use raw SQL to get companies with pending jobs that haven't been searched yet
    from sqlalchemy import text
    async with jobs_db.jobs_session_factory() as db:
        result = await db.execute(text("""
            SELECT c.id, c.name, c.ats_url, COUNT(t.id) as pending_count
            FROM companies c
            JOIN jobs j ON c.id = j.company_id
            JOIN target_jobs t ON j.id = t.job_id
            WHERE t.status = 1
              AND c.contacts_searched_at IS NULL
            GROUP BY c.id, c.name, c.ats_url
            ORDER BY pending_count DESC
            LIMIT :limit
        """), {"limit": limit})
        rows = result.fetchall()

    if not rows:
        yield {"type": "error", "text": "No companies with pending jobs found. Run /filter first."}
        return

    companies = [{"id": r[0], "name": r[1], "ats_url": r[2]} for r in rows]

    method = "LinkedIn employee count" if use_linkedin else "job count proxy"
    yield {"type": "progress", "text": f"Found {len(companies)} companies with pending jobs"}
    yield {"type": "progress", "text": f"Company sizing method: {method}"}
    yield {"type": "progress", "text": "=" * 50}

    # Run discover_contacts_for_companies in background thread
    progress_queue = queue.Queue()
    results = []
    done_event = threading.Event()
    error = None

    def run_discovery():
        nonlocal results, error
        try:
            from discovery.discover_contacts import discover_contacts_for_companies

            # Capture stdout and send to queue
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
                results = discover_contacts_for_companies(
                    companies,
                    use_linkedin_for_size=use_linkedin
                )
            finally:
                sys.stdout = old_stdout

        except Exception as e:
            error = str(e)
        finally:
            done_event.set()

    thread = threading.Thread(target=run_discovery)
    thread.start()

    # Stream progress while discovery runs
    while not done_event.is_set():
        try:
            while True:
                msg = progress_queue.get_nowait()
                yield {"type": "progress", "text": msg}
        except queue.Empty:
            pass
        await asyncio.sleep(0.2)

    # Drain remaining messages
    while not progress_queue.empty():
        msg = progress_queue.get_nowait()
        yield {"type": "progress", "text": msg}

    thread.join()

    if error:
        yield {"type": "error", "text": f"Discovery failed: {error}"}
        return

    # Summary
    yield {"type": "progress", "text": "=" * 50}
    total_contacts = sum(r.get('new_contacts', 0) for r in results)
    total_people = sum(len(r.get('people', [])) for r in results)

    yield {"type": "done", "text": f"Done! Found {total_people} contacts, {total_contacts} new. Processed {len(results)} companies."}


async def dork_companies(platform: str):
    """Google dork for new companies on an ATS platform.

    Uses Google Custom Search API to find company job boards.
    """
    import queue
    import threading

    yield {"type": "progress", "text": f"Dorking {platform.upper()} for new companies..."}
    yield {"type": "progress", "text": "Using Google Custom Search API (max 100 results)"}
    yield {"type": "progress", "text": "=" * 50}

    # Run dork_ats in background thread
    progress_queue = queue.Queue()
    done_event = threading.Event()
    error = None
    stats = {}

    def run_dork():
        nonlocal error, stats
        try:
            from discovery.dork_ats import dork_ats

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
                dork_ats(platform, start_page=1, max_pages=10)
            finally:
                sys.stdout = old_stdout

        except SystemExit:
            # dork_ats calls sys.exit on some errors
            pass
        except Exception as e:
            error = str(e)
        finally:
            done_event.set()

    thread = threading.Thread(target=run_dork)
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
        yield {"type": "error", "text": f"Dorking failed: {error}"}
        return

    yield {"type": "done", "text": f"Dorking complete for {platform}"}
