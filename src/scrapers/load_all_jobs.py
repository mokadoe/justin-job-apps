#!/usr/bin/env python3
"""Load jobs from ALL ATS platforms (Ashby, Lever, Greenhouse) into the database.

This script:
1. Queries companies table for active companies by ATS platform
2. Fetches job data from respective ATS APIs
3. Uses ATSMapper to extract and normalize job data
4. Upserts companies and jobs into database
5. Skips duplicates based on job_url
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

# Add utils to path for db import
sys.path.insert(0, str(Path(__file__).parent.parent / "utils"))
from jobs_db_conn import get_connection, is_remote

from ats_mapper import ATSMapper
from ashby_scraper import fetch_ashby_jobs
from lever_scraper import fetch_lever_jobs
from greenhouse_scraper import fetch_greenhouse_jobs


def _placeholder():
    """Return SQL placeholder for current database."""
    return "%s" if is_remote() else "?"


def get_companies_by_platform(platform: str) -> list:
    """Get list of active companies for a specific ATS platform from database."""
    p = _placeholder()
    with get_connection() as conn:
        cursor = conn.cursor()

        # Query for active companies on this platform
        cursor.execute(f'''
            SELECT name FROM companies
            WHERE (ats_platform = {p} OR ats_platform = {p})
            AND is_active = 1
        ''', (platform, f"{platform}hq"))

        companies = [row['name'] if is_remote() else row[0] for row in cursor.fetchall()]

        return companies


def upsert_company(cursor, company_name: str, ats_platform: str) -> int:
    """
    Upsert company and return company_id.

    Updates last_scraped if company exists, otherwise inserts new.
    """
    p = _placeholder()
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
        # This shouldn't happen since we're loading from DB, but handle it
        print(f"    ⚠ Company {company_name} not in database, skipping...")
        return None

    return company_id


def upsert_jobs(cursor, company_id: int, jobs: list) -> dict:
    """
    Upsert jobs for a company.

    Returns stats: {'inserted': N, 'skipped': N, 'pre_rejected': N}
    """
    p = _placeholder()
    stats = {'inserted': 0, 'skipped': 0, 'pre_rejected': 0}

    for job in jobs:
        try:
            job_description = job.get('job_description')

            # Mark jobs without descriptions as already evaluated (skip filtering)
            evaluated = 1 if not job_description else 0

            # Try to insert, ignore if job_url already exists
            if is_remote():
                cursor.execute(f'''
                    INSERT INTO jobs (company_id, job_url, job_title, job_description, location, posted_date, evaluated)
                    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
                    ON CONFLICT (job_url) DO NOTHING
                ''', (
                    company_id,
                    job.get('job_url'),
                    job.get('job_title'),
                    job_description,
                    job.get('location'),
                    job.get('posted_date'),
                    evaluated,
                ))
            else:
                cursor.execute(f'''
                    INSERT OR IGNORE INTO jobs (company_id, job_url, job_title, job_description, location, posted_date, evaluated)
                    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
                ''', (
                    company_id,
                    job.get('job_url'),
                    job.get('job_title'),
                    job_description,
                    job.get('location'),
                    job.get('posted_date'),
                    evaluated,
                ))

            if cursor.rowcount > 0:
                if not job_description:
                    stats['pre_rejected'] += 1
                else:
                    stats['inserted'] += 1
            else:
                stats['skipped'] += 1

        except Exception as e:
            print(f"    ⚠ Error inserting job {job.get('job_title')}: {e}")
            stats['skipped'] += 1

    return stats


def load_platform_jobs(platform: str, fetch_function, batch_size: int = 20):
    """
    Load jobs from a specific ATS platform into the database.

    Args:
        platform: ATS platform name (ashby, lever, greenhouse)
        fetch_function: Function to fetch jobs for this platform
        batch_size: Number of companies to fetch/commit at once
    """
    # Get companies for this platform
    companies = get_companies_by_platform(platform)

    if not companies:
        print(f"  No active {platform} companies found in database")
        return {
            'companies_processed': 0,
            'companies_success': 0,
            'companies_failed': 0,
            'jobs_inserted': 0,
            'jobs_skipped': 0,
            'jobs_total': 0
        }

    # Initialize mapper
    mapper = ATSMapper()

    # Check if mapping exists
    platform_key = f"{platform}hq" if platform == "ashby" else platform
    if platform_key not in mapper.list_platforms() and platform not in mapper.list_platforms():
        print(f"  ⚠ No {platform} mapping found in ats_mappings.json")
        return {
            'companies_processed': 0,
            'companies_success': 0,
            'companies_failed': 0,
            'jobs_inserted': 0,
            'jobs_skipped': 0,
            'jobs_total': 0
        }

    # Connect to database
    with get_connection() as conn:
        cursor = conn.cursor()
        return _load_platform_jobs_impl(conn, cursor, mapper, platform, platform_key, fetch_function, companies, batch_size)


def _load_platform_jobs_impl(conn, cursor, mapper, platform, platform_key, fetch_function, companies, batch_size):

    total_stats = {
        'companies_processed': 0,
        'companies_success': 0,
        'companies_failed': 0,
        'jobs_inserted': 0,
        'jobs_skipped': 0,
        'jobs_pre_rejected': 0,
        'jobs_total': 0
    }

    print(f"\nLoading {platform.upper()} jobs from {len(companies)} companies...")
    print("=" * 80)

    # Process in batches
    num_batches = (len(companies) + batch_size - 1) // batch_size

    for i in range(0, len(companies), batch_size):
        batch = companies[i:i + batch_size]
        batch_num = i // batch_size + 1

        # Fetch jobs for batch
        print(f"\nBatch {batch_num}/{num_batches}: Fetching {len(batch)} companies...")
        results = fetch_function(batch)

        # Process each company
        for company_name, result in results.items():
            total_stats['companies_processed'] += 1

            if not result['success']:
                print(f"  ✗ {company_name}: API fetch failed - {result.get('error')}")
                total_stats['companies_failed'] += 1
                continue

            try:
                # Extract jobs using mapper
                jobs = mapper.extract_jobs(platform_key, result['data'], company_name)

                if not jobs:
                    print(f"  ⚠ {company_name}: No jobs found")
                    total_stats['companies_failed'] += 1
                    continue

                # Upsert company
                company_id = upsert_company(cursor, company_name, platform)

                if not company_id:
                    total_stats['companies_failed'] += 1
                    continue

                # Upsert jobs
                job_stats = upsert_jobs(cursor, company_id, jobs)

                total_stats['companies_success'] += 1
                total_stats['jobs_inserted'] += job_stats['inserted']
                total_stats['jobs_skipped'] += job_stats['skipped']
                total_stats['jobs_pre_rejected'] += job_stats['pre_rejected']
                total_stats['jobs_total'] += len(jobs)

                desc_info = f", {job_stats['pre_rejected']} no desc" if job_stats['pre_rejected'] > 0 else ""
                print(f"  ✓ {company_name}: {job_stats['inserted']} new, {job_stats['skipped']} existing{desc_info}")

            except Exception as e:
                print(f"  ✗ {company_name}: Error - {e}")
                total_stats['companies_failed'] += 1

        # Commit batch
        conn.commit()
        print(f"  → Batch {batch_num}/{num_batches} committed")

    # Final commit (context manager will also commit)
    conn.commit()

    return total_stats


def main():
    """Load jobs from all ATS platforms."""

    print("=" * 80)
    print("LOADING JOBS FROM ALL ATS PLATFORMS")
    print("=" * 80)

    # Track overall stats
    overall_stats = {
        'companies_processed': 0,
        'companies_success': 0,
        'companies_failed': 0,
        'jobs_inserted': 0,
        'jobs_skipped': 0,
        'jobs_total': 0
    }

    # Load from each platform
    platforms = [
        ('ashbyhq', fetch_ashby_jobs),
        ('lever', fetch_lever_jobs),
        ('greenhouse', fetch_greenhouse_jobs),
    ]

    for platform, fetch_func in platforms:
        stats = load_platform_jobs(platform, fetch_func, batch_size=20)

        # Add to overall stats
        for key in overall_stats:
            overall_stats[key] += stats[key]

    # Print overall summary
    print("\n" + "=" * 80)
    print("OVERALL SUMMARY (All Platforms)")
    print("=" * 80)
    print(f"Companies processed:  {overall_stats['companies_processed']}")
    print(f"  ✓ Successful:       {overall_stats['companies_success']}")
    print(f"  ✗ Failed:           {overall_stats['companies_failed']}")
    print(f"\nJobs:")
    print(f"  Total found:        {overall_stats['jobs_total']}")
    print(f"  ✓ Newly inserted:   {overall_stats['jobs_inserted']}")
    print(f"  ⊘ Already existed:  {overall_stats['jobs_skipped']}")

    if overall_stats['companies_success'] > 0:
        avg_jobs = overall_stats['jobs_total'] / overall_stats['companies_success']
        print(f"\nAverage jobs/company: {avg_jobs:.1f}")

    print("\n✓ Job loading complete!")
    print("\nNext steps:")
    print("  1. Run 'make inspect' to view the database contents")
    print("  2. Run 'make filter' to filter jobs with AI")
    print("  3. Run 'make targets' to see target jobs")


if __name__ == "__main__":
    main()
