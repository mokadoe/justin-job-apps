#!/usr/bin/env python3
"""
Aggregator Runner

Unified CLI for running aggregators and storing results.

Usage:
    python -m src.discovery.aggregators.run simplify
    python -m src.discovery.aggregators.run yc --check 100
    python -m src.discovery.aggregators.run a16z --check-ats
    python -m src.discovery.aggregators.run manual
    python -m src.discovery.aggregators.run --all
    python -m src.discovery.aggregators.run --list
"""

import sys
import argparse
from pathlib import Path

# Add src/ to path for imports (works for both direct run and agent import)
src_path = Path(__file__).parent.parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
from utils.jobs_db_conn import get_connection, is_remote

from .types import CompanyLead, JobLead, AggregatorResult
from .utils import extract_slug_from_ats_url, SUPPORTED_ATS


def _placeholder():
    """Return SQL placeholder for current database."""
    return "%s" if is_remote() else "?"


# Late imports to avoid circular dependencies
def _get_aggregators():
    from .simplify_aggregator import SimplifyAggregator
    from .yc_aggregator import YCAggregator
    from .a16z_aggregator import A16ZAggregator
    from .manual_aggregator import ManualAggregator

    return {
        'simplify': SimplifyAggregator,
        'yc': YCAggregator,
        'a16z': A16ZAggregator,
        'manual': ManualAggregator,
    }


def store_companies(companies: list[CompanyLead], source: str) -> dict:
    """
    Store companies in database.

    Args:
        companies: List of CompanyLead objects
        source: Discovery source name (e.g., 'simplify', 'yc')

    Returns:
        Stats dict with 'added', 'existed', 'supported_ats', 'unsupported_ats', 'by_platform'
    """
    p = _placeholder()
    stats = {
        'added': 0,
        'existed': 0,
        'supported_ats': 0,
        'unsupported_ats': 0,
        'by_platform': {},  # Track additions per platform
    }

    print(f"\nStoring {len(companies)} companies to database...")
    db_type = "PostgreSQL (remote)" if is_remote() else "SQLite (local)"
    print(f"  Database: {db_type}")

    with get_connection() as conn:
        cursor = conn.cursor()

        for i, company in enumerate(companies):
            # Check if company exists
            cursor.execute(f"SELECT id FROM companies WHERE name = {p}", (company.name,))
            existing = cursor.fetchone()

            if existing:
                stats['existed'] += 1
                continue

            # Extract slug from ATS URL
            ats_slug = extract_slug_from_ats_url(company.ats_platform, company.ats_url)
            is_active = company.ats_platform in SUPPORTED_ATS

            cursor.execute(f"""
                INSERT INTO companies (name, discovery_source, ats_platform, ats_slug, ats_url, website, is_active)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
            """, (
                company.name,
                source,
                company.ats_platform,
                ats_slug,
                company.ats_url,
                company.website,
                is_active,
            ))

            stats['added'] += 1

            # Track by platform
            platform = company.ats_platform
            stats['by_platform'][platform] = stats['by_platform'].get(platform, 0) + 1

            if company.ats_platform in SUPPORTED_ATS:
                stats['supported_ats'] += 1
            else:
                stats['unsupported_ats'] += 1

            # Progress every 100 companies
            processed = i + 1
            if processed % 100 == 0:
                print(f"  [{processed}/{len(companies)}] {stats['added']} added, {stats['existed']} existed...")

    print(f"  ✓ Done storing companies")
    return stats


def queue_jobs(jobs: list[JobLead], source: str) -> int:
    """
    Queue job URLs for Sonnet analysis.

    Args:
        jobs: List of JobLead objects
        source: Discovery source name

    Returns:
        Number of jobs queued
    """
    if not jobs:
        return 0

    p = _placeholder()
    job_leads = []

    # Get company IDs for the job leads
    with get_connection() as conn:
        cursor = conn.cursor()

        for job in jobs:
            cursor.execute(f"SELECT id FROM companies WHERE name = {p}", (job.company_name,))
            result = cursor.fetchone()
            if result:
                job_leads.append((result['id'], job.job_url))

    if not job_leads:
        return 0

    # Import and call the analyzer
    from analyzers.job_url_analyzer import queue_job_leads
    return queue_job_leads(job_leads, source=source)


def run_aggregator(name: str, **options) -> dict:
    """
    Run a single aggregator and store results.

    Args:
        name: Aggregator name
        **options: Aggregator-specific options

    Returns:
        Stats dict with results
    """
    aggregators = _get_aggregators()

    if name not in aggregators:
        raise ValueError(f"Unknown aggregator: {name}. Available: {list(aggregators.keys())}")

    # Instantiate aggregator with options
    aggregator_class = aggregators[name]

    # Pass relevant options to constructor
    if name == 'yc':
        # None = check all (default), 0 = skip, N = check first N
        check_count = options.get('check', None)
        aggregator = aggregator_class(check_ats_count=check_count)
    elif name == 'a16z':
        # check_ats defaults to True, max_check None = check all
        check_ats = options.get('check_ats', True)
        max_check = options.get('max_check', None)
        aggregator = aggregator_class(check_ats=check_ats, max_check=max_check)
    elif name == 'manual':
        force = options.get('force', False)
        limit = options.get('limit')
        aggregator = aggregator_class(force=force, limit=limit)
    else:
        aggregator = aggregator_class()

    # Fetch data
    print(f"\n{'=' * 60}")
    print(f"Running {name} aggregator")
    print('=' * 60)

    result = aggregator.fetch()

    # Store results
    company_stats = store_companies(result.companies, source=aggregator.name)
    jobs_queued = queue_jobs(result.jobs, source=aggregator.name)

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"SUMMARY - {name.upper()} AGGREGATOR")
    print('=' * 60)
    print(f"Companies discovered: {len(result.companies)}")
    print(f"Database updates:")
    print(f"  + Added:          {company_stats['added']}")
    print(f"  = Already existed: {company_stats['existed']}")

    # Show platform breakdown for added companies
    if company_stats.get('by_platform'):
        print(f"\nAdded by ATS platform:")
        for platform, count in sorted(company_stats['by_platform'].items(), key=lambda x: -x[1]):
            marker = "✓" if platform in SUPPORTED_ATS else "✗"
            print(f"  {marker} {platform}: {count}")

    print(f"\nReady for job loading:")
    print(f"  Supported ATS:    {company_stats['supported_ats']} (Ashby/Lever/Greenhouse)")
    print(f"  Unsupported ATS:  {company_stats['unsupported_ats']} (need manual review)")

    if result.jobs:
        print(f"\nJob leads queued:   {jobs_queued} (for Sonnet analysis)")

    return {
        'companies': len(result.companies),
        **company_stats,
        'jobs_queued': jobs_queued,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run aggregators to discover companies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m src.discovery.aggregators.run simplify
    python -m src.discovery.aggregators.run yc --check 200
    python -m src.discovery.aggregators.run a16z --check-ats
    python -m src.discovery.aggregators.run manual --force
    python -m src.discovery.aggregators.run --all
        """
    )

    parser.add_argument('aggregator', nargs='?',
                        help='Aggregator to run (simplify, yc, a16z, manual)')
    parser.add_argument('--all', action='store_true',
                        help='Run all aggregators')
    parser.add_argument('--list', action='store_true',
                        help='List available aggregators')

    # YC/A16Z options
    parser.add_argument('--check', type=int, default=None,
                        help='Limit ATS probing to first N companies (default: check ALL)')

    # A16Z options
    parser.add_argument('--no-check-ats', action='store_true',
                        help='Skip ATS probing entirely (a16z)')

    # Manual options
    parser.add_argument('--force', '-f', action='store_true',
                        help='Re-check existing companies (manual)')
    parser.add_argument('--limit', '-l', type=int,
                        help='Limit number of companies (manual)')

    args = parser.parse_args()

    aggregators = _get_aggregators()

    if args.list:
        print("Available aggregators:")
        for name in aggregators:
            print(f"  - {name}")
        return

    if args.all:
        print("Running all aggregators...")
        for name in aggregators:
            try:
                run_aggregator(name, check=args.check)
            except Exception as e:
                print(f"Error running {name}: {e}")
        return

    if not args.aggregator:
        parser.print_help()
        return

    if args.aggregator not in aggregators:
        print(f"Unknown aggregator: {args.aggregator}")
        print(f"Available: {', '.join(aggregators.keys())}")
        sys.exit(1)

    run_aggregator(
        args.aggregator,
        check=args.check,
        check_ats=not args.no_check_ats,
        max_check=args.check,
        force=args.force,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
