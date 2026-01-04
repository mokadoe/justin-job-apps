"""
Scrape command - fetch jobs from ATS platforms.

Usage:
    /scrape ashby <company> [company...]  - Fetch jobs from Ashby ATS
    /scrape simplify                      - Refresh prospective companies from GitHub
"""

from . import register


@register(
    "scrape",
    description="Fetch jobs from ATS platforms",
    usage="/scrape ashby <company> [company...] | /scrape simplify"
)
async def handle_scrape(args: str):
    """Handle /scrape command."""
    parts = args.split()
    source = parts[0].lower() if parts else ""

    if not source:
        yield {"type": "error", "text": "Usage: /scrape ashby <company> [company...] | /scrape simplify"}
        return

    if source == "ashby":
        async for event in scrape_ashby(parts[1:]):
            yield event
    elif source == "simplify":
        async for event in scrape_simplify():
            yield event
    else:
        yield {"type": "error", "text": f"Unknown source: {source}. Use 'ashby' or 'simplify'"}


async def scrape_ashby(companies: list[str]):
    """Scrape jobs from Ashby ATS and persist to database."""

    # If no companies specified, get all Ashby companies from DB
    if not companies:
        import jobs_db
        yield {"type": "progress", "text": "No companies specified, fetching all Ashby companies from database..."}

        db_companies = await jobs_db.get_companies_by_platform("ashbyhq")
        if not db_companies:
            yield {"type": "error", "text": "No Ashby companies found in database. Use: /scrape ashby <company> to add some first."}
            return

        companies = [c["name"] for c in db_companies]
        yield {"type": "progress", "text": f"Found {len(companies)} Ashby companies in database"}

    yield {"type": "progress", "text": f"Fetching jobs from Ashby for {len(companies)} companies..."}

    try:
        import jobs_db
        from scrapers.ashby_scraper import fetch_ashby_jobs
        from scrapers.ats_mapper import ATSMapper
        from io import StringIO
        from contextlib import redirect_stdout

        # Fetch from API, capturing stdout for progress
        captured = StringIO()
        with redirect_stdout(captured):
            results = fetch_ashby_jobs(companies)

        # Stream fetch output
        captured.seek(0)
        for line in captured:
            line = line.rstrip()
            if line:
                yield {"type": "progress", "text": line}

        if not results:
            yield {"type": "done", "text": "Scrape complete (no results)"}
            return

        # Persist to database
        yield {"type": "progress", "text": "Saving to database..."}
        mapper = ATSMapper()
        stats = {"companies": 0, "inserted": 0, "skipped": 0, "failed": 0}
        last_job_progress = 0
        total_companies = len([r for r in results.values() if r.get("success")])

        for company_name, result in results.items():
            if not result.get("success"):
                stats["failed"] += 1
                continue

            try:
                # Extract jobs using mapper
                jobs_data = mapper.extract_jobs("ashbyhq", result["data"], company_name)
                if not jobs_data:
                    stats["failed"] += 1
                    continue

                # Upsert company
                ats_url = f"https://jobs.ashbyhq.com/{company_name}"
                company = await jobs_db.upsert_company(company_name, "ashbyhq", ats_url)

                # Upsert jobs
                company_inserted = 0
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
                        stats["inserted"] += 1
                        company_inserted += 1
                    else:
                        stats["skipped"] += 1

                stats["companies"] += 1

                # Progress update every 10 companies OR every 25 new jobs
                if stats["companies"] % 10 == 0:
                    yield {"type": "progress", "text": f"  [{stats['companies']}/{total_companies}] Processed {company_name} (+{company_inserted} new)"}
                elif stats["inserted"] - last_job_progress >= 25:
                    yield {"type": "progress", "text": f"  {stats['inserted']} new jobs saved..."}
                    last_job_progress = stats["inserted"]

            except Exception as e:
                stats["failed"] += 1
                yield {"type": "progress", "text": f"  Error saving {company_name}: {e}"}

        yield {
            "type": "done",
            "text": f"Scraped {stats['inserted'] + stats['skipped']} jobs from {stats['companies']} companies ({stats['inserted']} new, {stats['skipped']} already exist)"
        }

    except ImportError as e:
        yield {"type": "error", "text": f"Failed to import: {e}"}
    except Exception as e:
        yield {"type": "error", "text": f"Scrape failed: {e}"}


async def scrape_simplify():
    """Scrape prospective companies from Simplify Jobs GitHub."""
    yield {"type": "progress", "text": "Fetching Simplify Jobs README from GitHub..."}

    try:
        from scrapers import simplify_scraper
        from io import StringIO
        from contextlib import redirect_stdout

        # Capture output from main()
        captured = StringIO()
        with redirect_stdout(captured):
            simplify_scraper.main()

        # Stream captured output
        captured.seek(0)
        for line in captured:
            line = line.rstrip()
            if line:
                yield {"type": "progress", "text": line}

        yield {"type": "done", "text": "Simplify scrape complete. Check data/prospective_companies.txt"}

    except ImportError as e:
        yield {"type": "error", "text": f"Failed to import scraper: {e}"}
    except Exception as e:
        yield {"type": "error", "text": f"Scrape failed: {e}"}
