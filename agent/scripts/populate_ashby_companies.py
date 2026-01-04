#!/usr/bin/env python3
"""One-time script to populate Railway database with Ashby companies.

Usage:
    USE_REMOTE_DB=true DATABASE_URL="postgresql://..." python3 agent/scripts/populate_ashby_companies.py
"""

import asyncio
import sys
from pathlib import Path

# Add agent directory to path for imports
agent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(agent_dir))

from jobs_db import init_jobs_db, upsert_company, get_company_count


async def main():
    # Path to ashby companies file
    companies_file = Path(__file__).parent.parent.parent / "data" / "ashby_companies.txt"

    if not companies_file.exists():
        print(f"Error: {companies_file} not found")
        sys.exit(1)

    # Read company slugs (skip empty lines)
    slugs = [line.strip() for line in companies_file.read_text().splitlines() if line.strip()]
    print(f"Found {len(slugs)} companies to insert")

    # Initialize database (creates tables if needed)
    await init_jobs_db()

    initial_count = await get_company_count()
    print(f"Current company count: {initial_count}")

    # Insert companies
    inserted = 0
    updated = 0
    for slug in slugs:
        company = await upsert_company(
            name=slug,
            ats_platform="ashbyhq",
            ats_slug=slug,
            ats_url=f"https://jobs.ashbyhq.com/{slug}",
        )
        # upsert_company doesn't tell us if it was new or updated,
        # but we can infer from the count change later
        inserted += 1
        if inserted % 50 == 0:
            print(f"  Processed {inserted}/{len(slugs)}...")

    final_count = await get_company_count()
    new_companies = final_count - initial_count

    print(f"\nDone!")
    print(f"  Processed: {inserted}")
    print(f"  New companies added: {new_companies}")
    print(f"  Total companies now: {final_count}")


if __name__ == "__main__":
    asyncio.run(main())
