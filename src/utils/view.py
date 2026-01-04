#!/usr/bin/env python3
"""Consolidated tool for viewing and analyzing job database."""

import sys
from pathlib import Path
from collections import Counter
from tabulate import tabulate
import re

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from constants import STATUS_LABELS, STATUS_PENDING, STATUS_NOT_RELEVANT, STATUS_REVIEWED, STATUS_APPLIED
from db import get_connection, is_remote


# ============================================================================
# DATABASE OVERVIEW (formerly inspect_db.py)
# ============================================================================

def inspect_database():
    """Display first few rows from each table."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _inspect_database_impl(cursor)


def _inspect_database_impl(cursor):

    # Check companies table
    print("=" * 80)
    print("COMPANIES TABLE")
    print("=" * 80)
    cursor.execute("SELECT * FROM companies LIMIT 10")
    companies = cursor.fetchall()

    if companies:
        headers = companies[0].keys()
        rows = [tuple(row) for row in companies]
        print(tabulate(rows, headers=headers, tablefmt="grid"))

        # Get total count
        cursor.execute("SELECT COUNT(*) as cnt FROM companies")
        total = cursor.fetchone()['cnt']
        print(f"\nTotal companies: {total}")
    else:
        print("No companies in database")

    print("\n" + "=" * 80)
    print("JOBS TABLE")
    print("=" * 80)
    cursor.execute("SELECT * FROM jobs LIMIT 10")
    jobs = cursor.fetchall()

    if jobs:
        headers = jobs[0].keys()
        rows = [tuple(row) for row in jobs]
        print(tabulate(rows, headers=headers, tablefmt="grid"))

        # Get total count
        cursor.execute("SELECT COUNT(*) as cnt FROM jobs")
        total = cursor.fetchone()['cnt']
        print(f"\nTotal jobs: {total}")
    else:
        print("No jobs in database")

    # Show target jobs (PENDING ONLY - relevant jobs to apply to)
    print("\n" + "=" * 80)
    print("TARGET JOBS (PENDING - status=1)")
    print("=" * 80)
    cursor.execute("""
        SELECT t.id, t.job_id, j.job_title, c.name as company, t.relevance_score, t.match_reason
        FROM target_jobs t
        JOIN jobs j ON t.job_id = j.id
        JOIN companies c ON j.company_id = c.id
        WHERE t.status = 1
        ORDER BY t.relevance_score DESC
        LIMIT 10
    """)
    target_jobs = cursor.fetchall()

    if target_jobs:
        headers = ["ID", "Job ID", "Title", "Company", "Score", "Reason"]
        rows = []
        for row in target_jobs:
            # Truncate title and reason if too long
            title = row['job_title'][:40] if len(row['job_title']) > 40 else row['job_title']
            company = row['company'][:20] if len(row['company']) > 20 else row['company']
            reason = row['match_reason'][:50] + "..." if len(row['match_reason']) > 50 else row['match_reason']
            rows.append((row['id'], row['job_id'], title, company, f"{row['relevance_score']:.2f}", reason))

        print(tabulate(rows, headers=headers, tablefmt="grid"))

        # Get counts by status
        cursor.execute("""
            SELECT
                SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 0 THEN 1 ELSE 0 END) as rejected,
                COUNT(*) as total
            FROM target_jobs
        """)
        counts = cursor.fetchone()
        print(f"\nPending (relevant): {counts['pending']}")
        print(f"Rejected (not relevant): {counts['rejected']}")
        print(f"Total filtered: {counts['total']}")
    else:
        print("No pending jobs yet (run 'make filter' to evaluate jobs)")

    # Show summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    cursor.execute("""
        SELECT
            c.ats_platform,
            COUNT(DISTINCT c.id) as companies,
            COUNT(DISTINCT j.id) as total_jobs,
            SUM(CASE WHEN j.evaluated = 1 THEN 1 ELSE 0 END) as evaluated_jobs,
            COUNT(DISTINCT CASE WHEN t.status = 1 THEN t.id END) as pending_jobs,
            COUNT(DISTINCT CASE WHEN t.status = 0 THEN t.id END) as rejected_jobs
        FROM companies c
        LEFT JOIN jobs j ON c.id = j.company_id
        LEFT JOIN target_jobs t ON j.id = t.job_id
        GROUP BY c.ats_platform
    """)
    summary = cursor.fetchall()

    if summary:
        headers = ["Platform", "Companies", "Total Jobs", "Evaluated", "Pending", "Rejected"]
        rows = [tuple(row) for row in summary]
        print(tabulate(rows, headers=headers, tablefmt="grid"))
    else:
        print("No data in database")


# ============================================================================
# TARGET JOBS VIEWING (formerly view_targets.py and view_targets_stats.py)
# ============================================================================

def get_filtered_jobs(status_filter=None, limit=None, random_sample=False):
    """Get filtered jobs from target_jobs table."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Build query - use %s for postgres, ? for sqlite
        placeholder = "%s" if is_remote() else "?"

        query = """
            SELECT
                t.id,
                t.job_id,
                j.job_title,
                c.name as company_name,
                t.relevance_score,
                t.match_reason,
                t.status,
                j.location,
                j.job_url,
                t.added_date
            FROM target_jobs t
            JOIN jobs j ON t.job_id = j.id
            JOIN companies c ON j.company_id = c.id
        """

        params = []
        if status_filter is not None:
            query += f" WHERE t.status = {placeholder}"
            params.append(status_filter)

        if random_sample:
            query += " ORDER BY RANDOM()"
        else:
            query += " ORDER BY t.id DESC"

        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query, params)
        jobs = [dict(row) for row in cursor.fetchall()]

        return jobs


def get_target_stats():
    """Get statistics about filtered jobs."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 0 THEN 1 ELSE 0 END) as not_relevant,
                SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 2 THEN 1 ELSE 0 END) as reviewed,
                SUM(CASE WHEN status = 3 THEN 1 ELSE 0 END) as applied,
                AVG(CASE WHEN status = 1 THEN relevance_score ELSE NULL END) as avg_score_relevant,
                AVG(CASE WHEN status = 0 THEN relevance_score ELSE NULL END) as avg_score_rejected
            FROM target_jobs
        """)

        row = cursor.fetchone()
        stats = dict(row) if row else {}

        return stats


def display_jobs(jobs, show_url=False):
    """Display jobs in a formatted table."""
    if not jobs:
        print("No jobs found.")
        return

    # Prepare table data
    headers = ["ID", "Company", "Title", "Score", "Status", "Reason"]
    if show_url:
        headers.append("URL")

    rows = []
    for job in jobs:
        status_label = STATUS_LABELS.get(job['status'], 'Unknown')

        # Truncate reason if too long
        reason = job['match_reason']
        if len(reason) > 60:
            reason = reason[:57] + "..."

        row = [
            job['job_id'],
            job['company_name'][:20],  # Truncate company name
            job['job_title'][:40],      # Truncate title
            f"{job['relevance_score']:.2f}",
            status_label,
            reason
        ]

        if show_url:
            row.append(job['job_url'])

        rows.append(row)

    print(tabulate(rows, headers=headers, tablefmt="grid"))


def view_targets(args):
    """View filtered target jobs with various options."""
    show_url = '--url' in args
    status_filter = None
    limit = None
    random_sample = False

    # Check for status filter
    if '--pending' in args:
        status_filter = STATUS_PENDING
    elif '--rejected' in args:
        status_filter = STATUS_NOT_RELEVANT
    elif '--reviewed' in args:
        status_filter = STATUS_REVIEWED
    elif '--applied' in args:
        status_filter = STATUS_APPLIED

    # Check for sample
    if '--sample' in args:
        random_sample = True
        idx = args.index('--sample')
        if idx + 1 < len(args) and args[idx + 1].isdigit():
            limit = int(args[idx + 1])
        else:
            limit = 10  # Default sample size

    # Check for limit
    if '--limit' in args:
        idx = args.index('--limit')
        if idx + 1 < len(args) and args[idx + 1].isdigit():
            limit = int(args[idx + 1])

    # Get and display stats
    print("=" * 80)
    print("FILTERED JOBS STATISTICS")
    print("=" * 80)

    stats = get_target_stats()

    if stats['total'] == 0:
        print("\nNo filtered jobs yet. Run 'make filter' first.")
        return

    print(f"\nTotal filtered jobs: {stats['total']}")
    print(f"  ✓ Pending (to apply):     {stats['pending']} ({stats['pending']/stats['total']*100:.1f}%)")
    print(f"  ✗ Not relevant:           {stats['not_relevant']} ({stats['not_relevant']/stats['total']*100:.1f}%)")
    print(f"  ⊙ Reviewed (skipped):     {stats['reviewed']} ({stats['reviewed']/stats['total']*100:.1f}%)")
    print(f"  ✉ Applied:                {stats['applied']} ({stats['applied']/stats['total']*100:.1f}%)")

    if stats['avg_score_relevant']:
        print(f"\nAverage score (relevant): {stats['avg_score_relevant']:.2f}")
    if stats['avg_score_rejected']:
        print(f"Average score (rejected): {stats['avg_score_rejected']:.2f}")

    # Get and display jobs
    print("\n" + "=" * 80)
    if random_sample:
        print(f"RANDOM SAMPLE ({limit or 10} jobs)")
    else:
        print("FILTERED JOBS")

    if status_filter is not None:
        print(f"Filter: {STATUS_LABELS[status_filter]}")
    print("=" * 80)
    print()

    jobs = get_filtered_jobs(status_filter, limit, random_sample)
    display_jobs(jobs, show_url)

    print(f"\nShowing {len(jobs)} jobs")


# ============================================================================
# JOB ANALYSIS (formerly analyze_jobs.py)
# ============================================================================

def analyze_jobs():
    """Analyze job data and display insights."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _analyze_jobs_impl(cursor)


def _analyze_jobs_impl(cursor):
    print("=" * 80)
    print("JOB DATABASE ANALYSIS")
    print("=" * 80)

    # Total counts
    cursor.execute("SELECT COUNT(*) as cnt FROM companies")
    total_companies = cursor.fetchone()['cnt']

    cursor.execute("SELECT COUNT(*) as cnt FROM jobs")
    total_jobs = cursor.fetchone()['cnt']

    print(f"\nTotal Companies: {total_companies}")
    print(f"Total Jobs: {total_jobs}")
    print(f"Average Jobs/Company: {total_jobs / total_companies:.1f}")

    # Location analysis
    print("\n" + "=" * 80)
    print("LOCATION ANALYSIS")
    print("=" * 80)

    cursor.execute("""
        SELECT location, COUNT(*) as count
        FROM jobs
        GROUP BY location
        ORDER BY count DESC
        LIMIT 20
    """)

    locations = cursor.fetchall()

    # Categorize locations
    us_states = set(['AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
                     'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
                     'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
                     'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
                     'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'])

    null_count = 0
    remote_count = 0
    us_count = 0
    international_count = 0

    location_breakdown = []

    for row in locations:
        loc = row['location']
        count = row['count']

        if loc is None:
            null_count = count
            location_breakdown.append(f"  [NULL] No location specified: {count}")
        elif 'remote' in str(loc).lower():
            remote_count += count
            location_breakdown.append(f"  Remote: {count}")
        elif any(state in str(loc) for state in us_states):
            us_count += count
            location_breakdown.append(f"  US - {loc}: {count}")
        else:
            international_count += count
            location_breakdown.append(f"  International - {loc}: {count}")

    print(f"\nLocation Summary:")
    print(f"  No location (NULL): {null_count} ({null_count/total_jobs*100:.1f}%)")
    print(f"  Remote: {remote_count} ({remote_count/total_jobs*100:.1f}%)")
    print(f"  US-based: {us_count} ({us_count/total_jobs*100:.1f}%)")
    print(f"  International: {international_count} ({international_count/total_jobs*100:.1f}%)")

    print(f"\nTop 20 Locations:")
    for loc in location_breakdown[:20]:
        print(loc)

    # Job title analysis
    print("\n" + "=" * 80)
    print("JOB TITLE ANALYSIS")
    print("=" * 80)

    cursor.execute("SELECT job_title FROM jobs")
    titles = [row['job_title'].lower() for row in cursor.fetchall()]

    # Keywords to search for
    keywords = {
        'engineer': r'\bengineer',
        'software': r'\bsoftware',
        'backend': r'\bbackend|back-end|back end',
        'frontend': r'\bfrontend|front-end|front end',
        'fullstack': r'\bfullstack|full-stack|full stack',
        'ml/ai': r'\bmachine learning|ML|\bAI\b|artificial intelligence',
        'data': r'\bdata',
        'senior': r'\bsenior|sr\.',
        'staff': r'\bstaff',
        'principal': r'\bprincipal',
        'manager': r'\bmanager',
        'intern': r'\bintern',
        'new grad': r'\bnew grad|new-grad|recent grad',
        'junior': r'\bjunior|jr\.',
    }

    keyword_counts = {}
    for keyword, pattern in keywords.items():
        count = sum(1 for title in titles if re.search(pattern, title))
        keyword_counts[keyword] = count

    print("\nKeyword Frequency:")
    for keyword, count in sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {keyword:15} {count:5} ({count/total_jobs*100:5.1f}%)")

    # Common job titles
    print("\n" + "=" * 80)
    print("TOP 20 JOB TITLES")
    print("=" * 80)

    cursor.execute("""
        SELECT job_title, COUNT(*) as count
        FROM jobs
        GROUP BY job_title
        ORDER BY count DESC
        LIMIT 20
    """)

    for row in cursor.fetchall():
        print(f"  {row['count']:3}x {row['job_title']}")

    # Top companies by job count
    print("\n" + "=" * 80)
    print("TOP 20 COMPANIES BY JOB COUNT")
    print("=" * 80)

    cursor.execute("""
        SELECT c.name, COUNT(j.id) as job_count
        FROM companies c
        LEFT JOIN jobs j ON c.id = j.company_id
        GROUP BY c.id
        ORDER BY job_count DESC
        LIMIT 20
    """)

    for row in cursor.fetchall():
        print(f"  {row['job_count']:3}x {row['name']}")

    # Filter recommendations
    print("\n" + "=" * 80)
    print("FILTERING RECOMMENDATIONS")
    print("=" * 80)

    # Estimate target jobs
    potential_targets = sum(1 for title in titles if
        (re.search(r'\bengineer', title) or re.search(r'\bsoftware', title)) and
        not re.search(r'\bsenior|sr\.|staff|principal|manager|lead', title)
    )

    print(f"\nEstimated relevant jobs (Software/Engineer, non-senior):")
    print(f"  ~{potential_targets} jobs ({potential_targets/total_jobs*100:.1f}%)")

    print("\nSuggested filters:")
    print("  1. Location: US-based or Remote")
    print("  2. Title: Software Engineer, Backend, Frontend, Fullstack")
    print("  3. Level: Exclude Senior, Staff, Principal, Manager")
    print("  4. Keywords: New grad, Junior, Entry-level (or no seniority indicator)")


# ============================================================================
# MAIN CLI
# ============================================================================

def show_help():
    """Show help message."""
    print("""
Usage: python3 view.py [COMMAND] [OPTIONS]

Commands:
  db              Show database overview (companies, jobs, targets, summary)
  targets         Show filtered target jobs with statistics
  analyze         Analyze raw job data (locations, titles, keywords)

Target Options (use with 'targets' command):
  --pending       Show only pending jobs (status=1)
  --rejected      Show only rejected jobs (status=0)
  --reviewed      Show only reviewed jobs (status=2)
  --applied       Show only applied jobs (status=3)
  --sample N      Show random sample of N jobs (default: 10)
  --limit N       Limit results to N jobs
  --url           Include job URLs in output

Examples:
  python3 view.py db                          # Database overview
  python3 view.py targets                     # All targets with stats
  python3 view.py targets --pending           # Only pending jobs
  python3 view.py targets --sample 20         # Random 20 jobs
  python3 view.py targets --pending --url     # Pending with URLs
  python3 view.py analyze                     # Analyze raw data

Make shortcuts:
  make inspect    # Same as: python3 view.py db
  make targets    # Same as: python3 view.py targets
  make analyze    # Same as: python3 view.py analyze
    """)


def main():
    """Main CLI entry point."""
    # For local SQLite, check if DB exists
    if not is_remote():
        db_path = Path(__file__).parent.parent.parent / "data" / "jobs.db"
        if not db_path.exists():
            print(f"Database not found at {db_path}")
            print("Run 'make init' and 'make load' first")
            sys.exit(1)

    args = sys.argv[1:]

    # No arguments or help flag
    if not args or '--help' in args or '-h' in args:
        show_help()
        return

    command = args[0]

    if command == 'db':
        inspect_database()
    elif command == 'targets':
        view_targets(args[1:])
    elif command == 'analyze':
        analyze_jobs()
    else:
        print(f"Unknown command: {command}")
        print("Run 'python3 view.py --help' for usage")
        sys.exit(1)


if __name__ == "__main__":
    main()
