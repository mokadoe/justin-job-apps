"""
Scrape command - fetch jobs from ATS platforms.

Usage:
    /scrape ashby [--force]               - Fetch jobs from all Ashby companies
    /scrape ashby <company> [company...]  - Fetch jobs from specific companies

    # Aggregators (discover companies - checks ALL for ATS by default)
    /scrape simplify                      - SimplifyJobs GitHub new grad positions
    /scrape yc [--check N]                - YC companies (default: probe ALL for ATS)
    /scrape a16z [--check N]              - a16z portfolio (default: probe ALL for ATS)
    /scrape manual [--limit N]            - Companies from data/manual_companies.txt

    # Google dorking (discover companies via Google search)
    /scrape dork <ats>                    - Google dork for ATS (ashbyhq, lever, greenhouse)
    /scrape dork <ats> [--max-pages N]    - Limit pages (default 10, max 10)
    /scrape dork <ats> [--start-page N]   - Resume from page N
"""

from datetime import datetime, timezone
from . import register


@register(
    "scrape",
    description="Fetch jobs from ATS platforms",
    usage="/scrape ashby | /scrape simplify | /scrape yc | /scrape a16z | /scrape manual | /scrape dork <ats>"
)
async def handle_scrape(args: str):
    """Handle /scrape command."""
    parts = args.split()
    source = parts[0].lower() if parts else ""

    if not source:
        yield {"type": "error", "text": "Usage: /scrape <source>\n\nSources: ashby, simplify, yc, a16z, manual, dork"}
        return

    if source == "ashby":
        # Check for --force flag
        force = "--force" in parts
        companies = [p for p in parts[1:] if p != "--force"]
        async for event in scrape_ashby(companies, force=force):
            yield event

    elif source == "simplify":
        async for event in scrape_simplify():
            yield event

    elif source == "yc":
        # Parse --check N option (default None = check all)
        check = None
        for i, opt in enumerate(parts[1:], 1):
            if opt == "--check" and i < len(parts) - 1:
                try:
                    check = int(parts[i + 1])
                except ValueError:
                    pass
        async for event in scrape_yc(check=check):
            yield event

    elif source == "a16z":
        # Parse --check N option (default None = check all)
        max_check = None
        for i, opt in enumerate(parts[1:], 1):
            if opt == "--check" and i < len(parts) - 1:
                try:
                    max_check = int(parts[i + 1])
                except ValueError:
                    pass
        async for event in scrape_a16z(max_check=max_check):
            yield event

    elif source == "manual":
        # Parse --limit N and --force options
        force = "--force" in parts
        limit = None
        for i, opt in enumerate(parts[1:], 1):
            if opt == "--limit" and i < len(parts) - 1:
                try:
                    limit = int(parts[i + 1])
                except ValueError:
                    pass
        async for event in scrape_manual(limit=limit, force=force):
            yield event

    elif source == "dork":
        # Parse: /scrape dork <ats> [--max-pages N] [--start-page N]
        ats = parts[1].lower() if len(parts) > 1 else ""
        max_pages = 10  # default
        start_page = 1  # default
        for i, opt in enumerate(parts[2:], 2):
            if opt == "--max-pages" and i < len(parts) - 1:
                try:
                    max_pages = int(parts[i + 1])
                except ValueError:
                    pass
            elif opt == "--start-page" and i < len(parts) - 1:
                try:
                    start_page = int(parts[i + 1])
                except ValueError:
                    pass
        async for event in scrape_dork(ats=ats, max_pages=max_pages, start_page=start_page):
            yield event

    else:
        yield {"type": "error", "text": f"Unknown source: {source}. Use: ashby, simplify, yc, a16z, manual, dork"}


async def scrape_ashby(companies: list[str], force: bool = False):
    """Scrape jobs from Ashby ATS and persist to database.

    Args:
        companies: List of company slugs to scrape. If empty, scrapes all from DB.
        force: If True, scrape all companies. If False, skip recently scraped (today).
    """
    import asyncio
    import queue
    import threading
    import jobs_db
    from scrapers.ashby_scraper import fetch_ashby_jobs
    from scrapers.ats_mapper import ATSMapper

    # If no companies specified, get all Ashby companies from DB
    if not companies:
        yield {"type": "progress", "text": "Loading Ashby companies from database..."}

        db_companies = await jobs_db.get_companies_by_platform("ashbyhq")
        if not db_companies:
            yield {"type": "error", "text": "No Ashby companies found in database."}
            return

        # Partition into already-scraped-today vs needs-scraping
        today = datetime.now(timezone.utc).date().isoformat()
        already_done = []
        needs_scrape = []

        for c in db_companies:
            last = c.get("last_scraped")
            if not force and last and last.startswith(today):
                already_done.append(c["name"])
            else:
                needs_scrape.append(c["name"])

        # Show clear status
        yield {"type": "progress", "text": f"Found {len(db_companies)} Ashby companies total"}

        if already_done and not force:
            yield {"type": "progress", "text": f"  ✓ {len(already_done)} already scraped today (skipping)"}
            yield {"type": "progress", "text": f"  → {len(needs_scrape)} need scraping"}
            if not needs_scrape:
                yield {"type": "done", "text": "All companies already scraped today. Use --force to re-scrape."}
                return

        companies = needs_scrape

    total = len(companies)
    yield {"type": "progress", "text": f"Fetching jobs from {total} companies (10 concurrent)..."}
    yield {"type": "progress", "text": "=" * 50}

    # Queue for real-time progress from worker threads
    progress_queue = queue.Queue()

    def progress_callback(company, result, completed, total_count):
        """Called by scraper for each completed company."""
        if result.get('success'):
            progress_queue.put(f"[{completed}/{total_count}] ✓ {company}: {result['job_count']} jobs")
        else:
            progress_queue.put(f"[{completed}/{total_count}] ✗ {company}: {result['error']}")

    # Run scraper in background thread
    results = {}
    scrape_done = threading.Event()
    scrape_error = None

    def run_scraper():
        nonlocal results, scrape_error
        try:
            results = fetch_ashby_jobs(companies, progress_callback=progress_callback)
        except Exception as e:
            scrape_error = e
        finally:
            scrape_done.set()

    thread = threading.Thread(target=run_scraper)
    thread.start()

    # Stream progress while scraper runs
    while not scrape_done.is_set():
        try:
            while True:
                msg = progress_queue.get_nowait()
                yield {"type": "progress", "text": msg}
        except queue.Empty:
            pass
        await asyncio.sleep(0.1)

    # Drain remaining messages
    while not progress_queue.empty():
        msg = progress_queue.get_nowait()
        yield {"type": "progress", "text": msg}

    thread.join()

    if scrape_error:
        yield {"type": "error", "text": f"Scrape failed: {scrape_error}"}
        return

    if not results:
        yield {"type": "done", "text": "Scrape complete (no results)"}
        return

    # Persist to database
    successful_results = {k: v for k, v in results.items() if v.get("success")}
    failed_count = len(results) - len(successful_results)

    yield {"type": "progress", "text": "=" * 50}
    yield {"type": "progress", "text": f"Fetch complete: {len(successful_results)} succeeded, {failed_count} failed"}
    yield {"type": "progress", "text": f"Saving to database (10 concurrent)..."}

    mapper = ATSMapper()
    stats = {"companies": 0, "inserted": 0, "skipped": 0, "errors": 0}
    stats_lock = asyncio.Lock()
    total_to_save = len(successful_results)

    # Progress queue for real-time updates from concurrent saves
    save_progress_queue = asyncio.Queue()

    async def save_company(company_name: str, result: dict) -> tuple[int, int, str]:
        """Save a single company and its jobs. Returns (inserted, skipped, error)."""
        try:
            jobs_data = mapper.extract_jobs("ashbyhq", result["data"], company_name)
            if not jobs_data:
                return 0, 0, None

            # Upsert company (updates last_scraped)
            ats_url = f"https://jobs.ashbyhq.com/{company_name}"
            company = await jobs_db.upsert_company(company_name, "ashbyhq", ats_url)

            # Upsert jobs
            inserted = 0
            skipped = 0
            for job in jobs_data:
                _, is_new = await jobs_db.upsert_job(
                    company_id=company.id,
                    job_url=job.get("job_url"),
                    job_title=job.get("job_title"),
                    job_description=job.get("job_description"),
                    location=job.get("location"),
                    posted_date=job.get("posted_date")
                )
                if is_new:
                    inserted += 1
                else:
                    skipped += 1

            return inserted, skipped, None
        except Exception as e:
            return 0, 0, str(e)

    # Process in batches with semaphore for concurrency control
    semaphore = asyncio.Semaphore(10)

    async def save_with_progress(company_name: str, result: dict):
        async with semaphore:
            inserted, skipped, error = await save_company(company_name, result)
            await save_progress_queue.put((company_name, inserted, skipped, error))

    # Start all save tasks
    save_tasks = [
        asyncio.create_task(save_with_progress(name, result))
        for name, result in successful_results.items()
    ]

    # Process progress as saves complete
    completed = 0
    while completed < len(save_tasks):
        try:
            company_name, inserted, skipped, error = await asyncio.wait_for(
                save_progress_queue.get(), timeout=0.5
            )
            completed += 1

            async with stats_lock:
                if error:
                    stats["errors"] += 1
                else:
                    stats["companies"] += 1
                    stats["inserted"] += inserted
                    stats["skipped"] += skipped

            # Progress every 10 companies or on error
            if completed % 10 == 0 or error:
                if error:
                    yield {"type": "progress", "text": f"  [{completed}/{total_to_save}] ✗ {company_name}: {error}"}
                else:
                    yield {"type": "progress", "text": f"  [{completed}/{total_to_save}] Saved (+{stats['inserted']} new jobs so far)"}

        except asyncio.TimeoutError:
            # Just continue waiting
            pass

    # Wait for all tasks to complete (should already be done)
    await asyncio.gather(*save_tasks, return_exceptions=True)

    yield {"type": "progress", "text": "=" * 50}
    yield {
        "type": "done",
        "text": f"Done! {stats['companies']} companies, {stats['inserted']} new jobs, {stats['skipped']} existing"
    }


async def _run_aggregator(name: str, **options):
    """Run an aggregator and yield progress events.

    Args:
        name: Aggregator name (simplify, yc, a16z, manual)
        **options: Aggregator-specific options
    """
    yield {"type": "progress", "text": f"Running {name} aggregator..."}

    try:
        from io import StringIO
        from contextlib import redirect_stdout
        import sys
        from pathlib import Path
        # Add project root to path for src imports
        project_root = Path(__file__).parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        from src.discovery.aggregators.run import run_aggregator

        # Capture output from run_aggregator
        captured = StringIO()
        with redirect_stdout(captured):
            run_aggregator(name, **options)

        # Stream captured output
        captured.seek(0)
        for line in captured:
            line = line.rstrip()
            if line:
                yield {"type": "progress", "text": line}

        yield {"type": "done", "text": f"{name} aggregator complete"}

    except ImportError as e:
        yield {"type": "error", "text": f"Failed to import aggregator runner: {e}"}
    except Exception as e:
        yield {"type": "error", "text": f"Aggregator failed: {e}"}


async def scrape_simplify():
    """Discover companies from SimplifyJobs GitHub new grad positions."""
    async for event in _run_aggregator('simplify'):
        yield event


async def scrape_yc(check: int = None):
    """Discover companies from Y Combinator.

    Args:
        check: Number of companies to probe for ATS. None = check ALL (default).
    """
    async for event in _run_aggregator('yc', check=check):
        yield event


async def scrape_a16z(max_check: int = None):
    """Discover companies from a16z portfolio.

    Args:
        max_check: Maximum number of companies to probe for ATS. None = check ALL (default).
    """
    async for event in _run_aggregator('a16z', max_check=max_check):
        yield event


async def scrape_manual(limit: int = None, force: bool = False):
    """Discover companies from data/manual_companies.txt.

    Args:
        limit: Maximum number of companies to process
        force: Re-check existing companies (ignored - runner handles deduplication)
    """
    async for event in _run_aggregator('manual', limit=limit, force=force):
        yield event


async def scrape_dork(ats: str = "", max_pages: int = 10, start_page: int = 1):
    """Discover companies via Google dorking on ATS platforms.

    Args:
        ats: ATS platform (ashbyhq, lever, greenhouse)
        max_pages: Maximum pages to fetch (default 10, max 10 due to Google CSE limits)
        start_page: Page to start from (for resuming)
    """
    valid_ats = ['ashbyhq', 'lever', 'greenhouse']

    if not ats:
        yield {"type": "info", "text": "Google Dork - Discover companies via Google Custom Search"}
        yield {"type": "info", "text": "\nUsage: /scrape dork <ats> [--max-pages N] [--start-page N]"}
        yield {"type": "info", "text": f"\nATS platforms: {', '.join(valid_ats)}"}
        yield {"type": "info", "text": "\nExamples:"}
        yield {"type": "info", "text": "  /scrape dork ashbyhq"}
        yield {"type": "info", "text": "  /scrape dork lever --max-pages 5"}
        yield {"type": "info", "text": "  /scrape dork greenhouse --start-page 3"}
        return

    if ats not in valid_ats:
        yield {"type": "error", "text": f"Unknown ATS: {ats}. Use: {', '.join(valid_ats)}"}
        return

    # Cap max_pages to Google CSE limit
    if start_page + max_pages - 1 > 10:
        max_pages = max(1, 10 - start_page + 1)
        yield {"type": "progress", "text": f"Note: Google CSE limits to 10 pages. Capped to {max_pages} pages."}

    yield {"type": "progress", "text": f"Running Google dork for {ats}..."}

    try:
        from io import StringIO
        from contextlib import redirect_stdout
        from discovery.dork_ats import dork_ats, check_credentials

        # Check credentials first
        check_credentials()

        # Capture output from dork_ats
        captured = StringIO()
        with redirect_stdout(captured):
            dork_ats(ats, start_page=start_page, max_pages=max_pages)

        # Stream captured output
        captured.seek(0)
        for line in captured:
            line = line.rstrip()
            if line:
                yield {"type": "progress", "text": line}

        yield {"type": "done", "text": f"Google dork for {ats} complete"}

    except SystemExit as e:
        yield {"type": "error", "text": "Missing Google API credentials. Set GOOGLE_API_KEY and GOOGLE_CSE_ID in .env"}
    except ImportError as e:
        yield {"type": "error", "text": f"Failed to import dork module: {e}"}
    except Exception as e:
        yield {"type": "error", "text": f"Dork failed: {e}"}
