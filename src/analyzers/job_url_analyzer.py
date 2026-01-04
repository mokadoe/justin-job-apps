#!/usr/bin/env python3
"""
Job URL Analyzer - Extract job details from any job posting URL using Claude + web search.

Shared utility for all aggregators to analyze unsupported ATS job links.

Usage:
    # Analyze pending job leads
    python -m src.analyzers.job_url_analyzer --process --limit 20

    # Single URL
    python -m src.analyzers.job_url_analyzer "https://jobs.intuit.com/..."

    # From aggregators - queue jobs for later analysis
    from src.analyzers.job_url_analyzer import queue_job_lead, queue_job_leads
    queue_job_lead(company_id, job_url, source='simplify')
"""

import os
import sys
import json
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import anthropic

# Load environment variables
load_dotenv(Path(__file__).parent.parent.parent / ".env")

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
from src.utils.db import get_connection, is_remote


def _placeholder():
    """Return SQL placeholder for current database."""
    return "%s" if is_remote() else "?"


PENDING_JOBS_FILE = Path(__file__).parent.parent.parent / "data" / "pending_jobs.json"

# Initialize Anthropic client
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

EXTRACTION_PROMPT = """Visit this job posting URL and extract the job details.

URL: {url}

Return a JSON object with these fields:
- job_title: The exact job title
- company: Company name
- location: Job location (city, state, country, or "Remote")
- description: Brief summary of the role (2-3 sentences)
- requirements: Key requirements as a list of strings
- experience_level: One of "intern", "entry", "mid", "senior", or "unknown"
- is_relevant_new_grad: true if this looks like a new grad/entry-level software engineering role

If you cannot access the page or it's not a job posting, return:
{{"error": "reason", "is_job_posting": false}}

Return ONLY valid JSON, no other text."""


def analyze_job_url(url: str) -> dict:
    """
    Analyze a job URL using Claude Sonnet with web search.
    """
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": EXTRACTION_PROMPT.format(url=url)
            }],
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 3
            }]
        )

        result_text = ""
        for block in response.content:
            if block.type == "text":
                result_text = block.text
                break

        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0]
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0]

        result = json.loads(result_text.strip())
        result["source_url"] = url
        result["analysis_success"] = True
        return result

    except json.JSONDecodeError as e:
        return {
            "source_url": url,
            "analysis_success": False,
            "error": f"Failed to parse response as JSON: {e}",
            "raw_response": result_text[:500] if 'result_text' in locals() else None
        }
    except Exception as e:
        return {
            "source_url": url,
            "analysis_success": False,
            "error": str(e)
        }


# =============================================================================
# Job Lead Queue (JSON file based)
# =============================================================================

def load_pending_jobs() -> list[dict]:
    """Load pending jobs from JSON file."""
    if not PENDING_JOBS_FILE.exists():
        return []
    with open(PENDING_JOBS_FILE) as f:
        return json.load(f)


def save_pending_jobs(jobs: list[dict]):
    """Save pending jobs to JSON file."""
    with open(PENDING_JOBS_FILE, 'w') as f:
        json.dump(jobs, f, indent=2)


def queue_job_lead(company_id: int, job_url: str, source: str):
    """
    Add a single job lead to the pending queue.

    Called by aggregators when they find an unsupported ATS job.
    """
    jobs = load_pending_jobs()

    # Check for duplicate
    if any(j['job_url'] == job_url for j in jobs):
        return False

    jobs.append({
        'company_id': company_id,
        'job_url': job_url,
        'source': source,
    })
    save_pending_jobs(jobs)
    return True


def queue_job_leads(leads: list[tuple[int, str]], source: str) -> int:
    """
    Add multiple job leads to the pending queue.

    Args:
        leads: List of (company_id, job_url) tuples
        source: Source identifier (e.g., 'simplify', 'yc')

    Returns:
        Number of new leads added
    """
    jobs = load_pending_jobs()
    existing_urls = {j['job_url'] for j in jobs}

    added = 0
    for company_id, job_url in leads:
        if job_url not in existing_urls:
            jobs.append({
                'company_id': company_id,
                'job_url': job_url,
                'source': source,
            })
            existing_urls.add(job_url)
            added += 1

    save_pending_jobs(jobs)
    return added


def get_pending_count() -> dict:
    """Get count of pending jobs by source."""
    jobs = load_pending_jobs()
    counts = {}
    for job in jobs:
        source = job.get('source', 'unknown')
        counts[source] = counts.get(source, 0) + 1
    return counts


# =============================================================================
# Analysis Functions
# =============================================================================

def get_existing_job_urls(cursor) -> set:
    """Get all existing job URLs to avoid duplicates."""
    cursor.execute("SELECT job_url FROM jobs")
    return {row['job_url'] for row in cursor.fetchall()}


def process_pending_jobs(limit: int = None, max_workers: int = 3, verbose: bool = True) -> dict:
    """
    Process pending job leads from the queue.

    Args:
        limit: Max number of jobs to analyze
        max_workers: Number of concurrent analysis threads
        verbose: Print progress

    Returns:
        dict with stats
    """
    jobs = load_pending_jobs()

    if not jobs:
        if verbose:
            print("No pending jobs to process")
        return {'total': 0, 'analyzed': 0, 'added': 0, 'failed': 0, 'skipped_dupe': 0}

    p = _placeholder()

    # Get existing URLs first
    with get_connection() as conn:
        cursor = conn.cursor()
        existing_urls = get_existing_job_urls(cursor)

    stats = {
        'total': len(jobs),
        'analyzed': 0,
        'added': 0,
        'failed': 0,
        'skipped_dupe': 0,
    }

    # Filter out already-processed jobs
    to_process = []
    remaining = []

    for job in jobs:
        if job['job_url'] in existing_urls:
            stats['skipped_dupe'] += 1
        else:
            to_process.append(job)

    if verbose:
        print(f"Pending jobs: {len(jobs)} total, {stats['skipped_dupe']} already in DB")

    # Apply limit
    if limit and len(to_process) > limit:
        if verbose:
            print(f"  Limiting to {limit} jobs")
        remaining = to_process[limit:]
        to_process = to_process[:limit]

    if not to_process:
        if verbose:
            print("  No new jobs to analyze")
        # Clear processed jobs from queue
        save_pending_jobs(remaining)
        return stats

    if verbose:
        print(f"Analyzing {len(to_process)} jobs with {max_workers} workers...")

    def analyze_one(job):
        result = analyze_job_url(job['job_url'])
        return job, result

    processed_urls = set()
    results_to_insert = []  # Collect successful results

    # Analyze jobs in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(analyze_one, job): job for job in to_process}

        for future in as_completed(futures):
            job, result = future.result()
            stats['analyzed'] += 1
            processed_urls.add(job['job_url'])

            if result.get('analysis_success'):
                job_title = result.get('job_title', 'Software Engineer')
                location = result.get('location')
                description = result.get('description')
                results_to_insert.append({
                    'company_id': job['company_id'],
                    'job_url': job['job_url'],
                    'job_title': job_title,
                    'description': description,
                    'location': location,
                    'source': job['source'],
                    'company_name': result.get('company', 'Unknown'),
                })
                if verbose:
                    print(f"  ✓ {job_title[:40]} @ {result.get('company', 'Unknown')[:20]}")
            else:
                stats['failed'] += 1
                if verbose:
                    print(f"  ✗ {job['job_url'][:50]}... - {result.get('error', 'Unknown')[:30]}")

    # Insert results in a single transaction
    if results_to_insert:
        # Use ON CONFLICT for PostgreSQL compatibility
        insert_sql = f"""
            INSERT INTO jobs (company_id, job_url, job_title, job_description, location, source)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p})
            ON CONFLICT (job_url) DO NOTHING
        """ if is_remote() else """
            INSERT OR IGNORE INTO jobs (company_id, job_url, job_title, job_description, location, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """

        with get_connection() as conn:
            cursor = conn.cursor()
            for r in results_to_insert:
                try:
                    cursor.execute(insert_sql, (
                        r['company_id'], r['job_url'], r['job_title'],
                        r['description'], r['location'], r['source']
                    ))
                    stats['added'] += 1
                except Exception as e:
                    stats['failed'] += 1
                    if verbose:
                        print(f"  ✗ DB error for {r['job_url'][:30]}: {e}")

    # Remove processed jobs from queue, keep remaining
    remaining_jobs = [j for j in jobs if j['job_url'] not in processed_urls
                      and j['job_url'] not in existing_urls]
    remaining_jobs.extend(remaining)
    save_pending_jobs(remaining_jobs)

    if verbose:
        print(f"\nResults: {stats['added']} added, {stats['failed']} failed")
        print(f"Remaining in queue: {len(remaining_jobs)}")

    return stats


def clear_pending_jobs():
    """Clear all pending jobs from the queue."""
    save_pending_jobs([])


def main():
    parser = argparse.ArgumentParser(description="Analyze job posting URLs")
    parser.add_argument("url", nargs="?", help="Single URL to analyze")
    parser.add_argument("--process", "-p", action="store_true",
                        help="Process pending job leads from queue")
    parser.add_argument("--limit", "-l", type=int, default=10,
                        help="Limit number of jobs to analyze (default: 10)")
    parser.add_argument("--workers", "-w", type=int, default=3,
                        help="Number of concurrent workers (default: 3)")
    parser.add_argument("--status", "-s", action="store_true",
                        help="Show pending jobs status")
    parser.add_argument("--clear", action="store_true",
                        help="Clear pending jobs queue")
    args = parser.parse_args()

    if args.status:
        counts = get_pending_count()
        total = sum(counts.values())
        print(f"Pending jobs: {total}")
        for source, count in sorted(counts.items()):
            print(f"  {source}: {count}")

    elif args.clear:
        clear_pending_jobs()
        print("Cleared pending jobs queue")

    elif args.process:
        print("Processing pending job leads...")
        print("=" * 60)
        stats = process_pending_jobs(limit=args.limit, max_workers=args.workers)
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Total in queue:     {stats['total']}")
        print(f"Analyzed:           {stats['analyzed']}")
        print(f"Added to DB:        {stats['added']}")
        print(f"Failed:             {stats['failed']}")
        print(f"Skipped (exists):   {stats['skipped_dupe']}")

    elif args.url:
        result = analyze_job_url(args.url)
        print(json.dumps(result, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
