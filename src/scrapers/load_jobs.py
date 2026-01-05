#!/usr/bin/env python3
"""Load jobs from Ashby ATS companies into the database.

This script:
1. Reads company list from ashby_companies.txt
2. Fetches job data from Ashby API for each company
3. Upserts companies and jobs into database
4. Skips duplicates based on job_url
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

# Add utils to path for db import
sys.path.insert(0, str(Path(__file__).parent.parent / "utils"))
from jobs_db_conn import get_connection, is_remote

from ats_mapper import ATSMapper
from ashby_scraper import fetch_ashby_jobs
COMPANIES_FILE = Path(__file__).parent.parent.parent / "data" / "ashby_companies.txt"
ATS_PLATFORM = "ashbyhq"


def _placeholder():
    """Return SQL placeholder for current database."""
    return "%s" if is_remote() else "?"


def load_company_list(filepath: Path) -> list:
    """Load company names from text file."""
    with open(filepath, 'r') as f:
        return [line.strip() for line in f if line.strip()]


def upsert_company(cursor, company_name: str) -> int:
    """
    Upsert company and return company_id.

    Updates last_scraped if company exists, otherwise inserts new.
    """
    p = _placeholder()
    ats_url = f"https://jobs.{ATS_PLATFORM}.com/{company_name}"
    now = datetime.now(timezone.utc).isoformat()

    # Check if company exists
    cursor.execute(f'SELECT id FROM companies WHERE name = {p}', (company_name,))
    result = cursor.fetchone()

    if result:
        # Update existing company
        company_id = result['id'] if is_remote() else result[0]
        cursor.execute(f'''
            UPDATE companies
            SET last_scraped = {p}, is_active = 1
            WHERE id = {p}
        ''', (now, company_id))
    else:
        # Insert new company
        if is_remote():
            cursor.execute(f'''
                INSERT INTO companies (name, ats_platform, ats_url, last_scraped)
                VALUES ({p}, {p}, {p}, {p})
                RETURNING id
            ''', (company_name, ATS_PLATFORM, ats_url, now))
            company_id = cursor.fetchone()['id']
        else:
            cursor.execute(f'''
                INSERT INTO companies (name, ats_platform, ats_url, last_scraped)
                VALUES ({p}, {p}, {p}, {p})
            ''', (company_name, ATS_PLATFORM, ats_url, now))
            company_id = cursor.lastrowid

    return company_id


def upsert_jobs(cursor, company_id: int, jobs: list) -> dict:
    """
    Upsert jobs for a company.

    Returns stats: {'inserted': N, 'skipped': N}
    """
    p = _placeholder()
    stats = {'inserted': 0, 'skipped': 0}

    for job in jobs:
        try:
            # Try to insert, ignore if job_url already exists
            if is_remote():
                cursor.execute(f'''
                    INSERT INTO jobs (company_id, job_url, job_title, job_description, location, posted_date)
                    VALUES ({p}, {p}, {p}, {p}, {p}, {p})
                    ON CONFLICT (job_url) DO NOTHING
                ''', (
                    company_id,
                    job.get('job_url'),
                    job.get('job_title'),
                    job.get('job_description'),
                    job.get('location'),
                    job.get('posted_date')
                ))
            else:
                cursor.execute(f'''
                    INSERT OR IGNORE INTO jobs (company_id, job_url, job_title, job_description, location, posted_date)
                    VALUES ({p}, {p}, {p}, {p}, {p}, {p})
                ''', (
                    company_id,
                    job.get('job_url'),
                    job.get('job_title'),
                    job.get('job_description'),
                    job.get('location'),
                    job.get('posted_date')
                ))

            if cursor.rowcount > 0:
                stats['inserted'] += 1
            else:
                stats['skipped'] += 1

        except Exception as e:
            print(f"    ⚠ Error inserting job {job.get('job_title')}: {e}")
            stats['skipped'] += 1

    return stats


def load_ashby_jobs(company_names: list, batch_size: int = 20):
    """
    Load jobs from Ashby companies into the database.

    Args:
        company_names: List of Ashby company slugs
        batch_size: Number of companies to fetch/commit at once
    """
    # Initialize mapper
    mapper = ATSMapper()

    if ATS_PLATFORM not in mapper.list_platforms():
        print(f"⚠ No {ATS_PLATFORM} mapping found. Run ats_mapper.py first to create it.")
        return

    # Connect to database
    with get_connection() as conn:
        cursor = conn.cursor()
        _load_ashby_jobs_impl(conn, cursor, mapper, company_names, batch_size)


def _load_ashby_jobs_impl(conn, cursor, mapper, company_names, batch_size):

    total_stats = {
        'companies_processed': 0,
        'companies_success': 0,
        'companies_failed': 0,
        'jobs_inserted': 0,
        'jobs_skipped': 0,
        'jobs_total': 0
    }

    print(f"Loading jobs from {len(company_names)} Ashby companies...")
    print("=" * 80)

    # Process in batches
    num_batches = (len(company_names) + batch_size - 1) // batch_size

    for i in range(0, len(company_names), batch_size):
        batch = company_names[i:i + batch_size]
        batch_num = i // batch_size + 1

        # Fetch jobs for batch
        print(f"\nBatch {batch_num}/{num_batches}: Fetching {len(batch)} companies...")
        results = fetch_ashby_jobs(batch)

        # Process each company
        for company_name, result in results.items():
            total_stats['companies_processed'] += 1

            if not result['success']:
                print(f"  ✗ {company_name}: API fetch failed - {result.get('error')}")
                total_stats['companies_failed'] += 1
                continue

            try:
                # Extract jobs using mapper
                jobs = mapper.extract_jobs(ATS_PLATFORM, result['data'], company_name)

                if not jobs:
                    print(f"  ⚠ {company_name}: No jobs found")
                    total_stats['companies_failed'] += 1
                    continue

                # Upsert company
                company_id = upsert_company(cursor, company_name)

                # Upsert jobs
                job_stats = upsert_jobs(cursor, company_id, jobs)

                total_stats['companies_success'] += 1
                total_stats['jobs_inserted'] += job_stats['inserted']
                total_stats['jobs_skipped'] += job_stats['skipped']
                total_stats['jobs_total'] += len(jobs)

                print(f"  ✓ {company_name}: {job_stats['inserted']} new, {job_stats['skipped']} existing ({len(jobs)} total)")

            except Exception as e:
                print(f"  ✗ {company_name}: Error - {e}")
                total_stats['companies_failed'] += 1

        # Commit batch
        conn.commit()
        print(f"  → Batch {batch_num}/{num_batches} committed")

    # Final commit (context manager will also commit)
    conn.commit()

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Companies processed:  {total_stats['companies_processed']}")
    print(f"  ✓ Successful:       {total_stats['companies_success']}")
    print(f"  ✗ Failed:           {total_stats['companies_failed']}")
    print(f"\nJobs:")
    print(f"  Total found:        {total_stats['jobs_total']}")
    print(f"  ✓ Newly inserted:   {total_stats['jobs_inserted']}")
    print(f"  ⊘ Already existed:  {total_stats['jobs_skipped']}")

    if total_stats['companies_success'] > 0:
        avg_jobs = total_stats['jobs_total'] / total_stats['companies_success']
        print(f"\nAverage jobs/company: {avg_jobs:.1f}")

    print("\n✓ Job loading complete!")
    print("\nRun 'make inspect' to view the database contents")


if __name__ == "__main__":
    # Load company list
    companies = load_company_list(COMPANIES_FILE)
    print(f"Found {len(companies)} Ashby companies in {COMPANIES_FILE}\n")

    # Load all companies
    load_ashby_jobs(companies)
