#!/usr/bin/env python3
"""
ATS Company Discovery via Google Dorking

Discovers companies on ATS platforms using Google Custom Search API
and inserts directly into database.

Usage:
    python3 dork_ats.py --ats ashbyhq
    python3 dork_ats.py --ats lever --start-page 3
    python3 dork_ats.py --ats greenhouse --max-pages 10
"""

import argparse
import os
import sys
import json
import sqlite3
import requests
import re
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
load_dotenv()

# Configuration
ATS_PLATFORMS = {
    'ashbyhq': {
        'search_query': 'site:jobs.ashbyhq.com',
        'url_pattern': r'jobs\.ashbyhq\.com/([^/\?#]+)',
        'base_url': 'https://jobs.ashbyhq.com/'
    },
    'lever': {
        'search_query': 'site:jobs.lever.co',
        'url_pattern': r'jobs\.lever\.co/([^/\?#]+)',
        'base_url': 'https://jobs.lever.co/'
    },
    'greenhouse': {
        'search_query': 'site:boards.greenhouse.io',
        'url_pattern': r'boards\.greenhouse\.io/([^/\?#]+)',
        'base_url': 'https://boards.greenhouse.io/'
    }
}

# Paths
DB_PATH = Path(__file__).parent.parent.parent / 'data' / 'jobs.db'
OUTPUT_DIR = Path(__file__).parent.parent.parent / 'data' / 'dork_results'
OUTPUT_DIR.mkdir(exist_ok=True)

# Google Custom Search API credentials
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')

# Parallelization settings
PAGES_PER_BATCH = 5  # Fetch 5 pages in parallel


def check_credentials():
    """Check that Google API credentials are set."""
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        print("Error: GOOGLE_API_KEY and GOOGLE_CSE_ID must be set in .env file")
        sys.exit(1)


def fetch_single_page(query: str, page: int) -> dict:
    """
    Fetch a single page of Google search results.

    Args:
        query: Search query string
        page: Page number (1-indexed)

    Returns:
        Dict with 'success', 'page', 'items' or 'error'
    """
    start_index = (page - 1) * 10 + 1

    try:
        response = requests.get(
            'https://www.googleapis.com/customsearch/v1',
            params={
                'key': GOOGLE_API_KEY,
                'cx': GOOGLE_CSE_ID,
                'q': query,
                'start': start_index,
                'num': 10,
            },
            timeout=15
        )

        response.raise_for_status()
        data = response.json()

        items = data.get('items', [])
        return {
            'success': True,
            'page': page,
            'items': items,
            'count': len(items)
        }

    except requests.exceptions.RequestException as e:
        return {
            'success': False,
            'page': page,
            'error': str(e),
            'items': []
        }


def fetch_pages_parallel(query: str, pages: list[int]) -> list[dict]:
    """
    Fetch multiple pages in parallel.

    Args:
        query: Search query string
        pages: List of page numbers to fetch

    Returns:
        List of results (success or failure for each page)
    """
    results = []

    with ThreadPoolExecutor(max_workers=PAGES_PER_BATCH) as executor:
        futures = {
            executor.submit(fetch_single_page, query, page): page
            for page in pages
        }

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

    # Sort by page number for consistent ordering
    results.sort(key=lambda x: x['page'])
    return results


def extract_company_slug(url: str, ats_platform: str) -> str | None:
    """
    Extract company slug from ATS URL.

    Examples:
        https://boards.greenhouse.io/airbnb -> airbnb
        https://jobs.lever.co/figma/abc123 -> figma
        https://jobs.ashbyhq.com/openai -> openai
    """
    pattern = ATS_PLATFORMS[ats_platform]['url_pattern']
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    return None


def process_search_results(ats_platform: str, all_results: list[dict]) -> list[dict]:
    """
    Process raw Google search results and extract unique companies.

    Args:
        ats_platform: ATS platform name
        all_results: List of page results from parallel fetch

    Returns:
        List of company dicts for database insertion
    """
    companies = []
    slugs_seen = set()
    base_url = ATS_PLATFORMS[ats_platform]['base_url']

    for page_result in all_results:
        if not page_result['success']:
            continue

        for item in page_result['items']:
            url = item.get('link', '')

            # Extract company slug
            slug = extract_company_slug(url, ats_platform)
            if not slug:
                continue

            # Skip duplicates
            if slug in slugs_seen:
                continue
            slugs_seen.add(slug)

            # Build canonical ATS URL
            ats_url = f"{base_url}{slug}"

            companies.append({
                'name': slug,
                'ats_platform': ats_platform,
                'ats_slug': slug,
                'ats_url': ats_url,
                'discovery_source': 'google_dork',
            })

    return companies


def insert_companies_batch(companies: list[dict]) -> dict:
    """
    Insert a batch of companies into the database.

    Returns:
        Dict with 'added' and 'skipped' counts
    """
    if not companies:
        return {'added': 0, 'skipped': 0}

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    stats = {'added': 0, 'skipped': 0}

    for company in companies:
        # Check if exists
        cursor.execute("SELECT id FROM companies WHERE name = ?", (company['name'],))
        if cursor.fetchone():
            stats['skipped'] += 1
        else:
            # discovered_date uses DEFAULT CURRENT_TIMESTAMP from schema
            cursor.execute("""
                INSERT INTO companies (name, discovery_source, ats_platform, ats_slug, ats_url, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (
                company['name'],
                company['discovery_source'],
                company['ats_platform'],
                company['ats_slug'],
                company['ats_url'],
            ))
            stats['added'] += 1

    conn.commit()
    conn.close()

    return stats


def save_raw_results(ats_platform: str, all_results: list[dict]):
    """Save raw search results to JSON file for backup."""
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    filename = OUTPUT_DIR / f'{ats_platform}_raw_{timestamp}.json'

    # Flatten items from all pages
    all_items = []
    for result in all_results:
        if result['success']:
            all_items.extend(result['items'])

    with open(filename, 'w') as f:
        json.dump({
            'ats_platform': ats_platform,
            'timestamp': timestamp,
            'total_items': len(all_items),
            'items': all_items
        }, f, indent=2)

    print(f"  Saved raw results to {filename.name}")


def dork_ats(ats_platform: str, start_page: int = 1, max_pages: int = 10):
    """
    Main dorking function for a single ATS platform.

    Args:
        ats_platform: ATS platform to dork (ashbyhq, lever, greenhouse)
        start_page: Page to start from (for resuming)
        max_pages: Maximum pages to fetch
    """
    if ats_platform not in ATS_PLATFORMS:
        print(f"Error: Unknown ATS platform '{ats_platform}'")
        print(f"Available: {', '.join(ATS_PLATFORMS.keys())}")
        sys.exit(1)

    config = ATS_PLATFORMS[ats_platform]
    query = config['search_query']

    print(f"\n{'='*60}")
    print(f"Dorking: {ats_platform.upper()}")
    print(f"Query: {query}")
    print(f"Pages: {start_page} to {start_page + max_pages - 1}")
    print(f"{'='*60}\n")

    # Calculate pages to fetch
    end_page = start_page + max_pages
    all_pages = list(range(start_page, end_page))

    # Track stats
    total_stats = {'added': 0, 'skipped': 0, 'api_calls': 0}
    all_results = []
    failed_pages = []

    # Process in batches
    for batch_start in range(0, len(all_pages), PAGES_PER_BATCH):
        batch_pages = all_pages[batch_start:batch_start + PAGES_PER_BATCH]
        batch_num = batch_start // PAGES_PER_BATCH + 1
        total_batches = (len(all_pages) + PAGES_PER_BATCH - 1) // PAGES_PER_BATCH

        print(f"[Batch {batch_num}/{total_batches}] Fetching pages {batch_pages[0]}-{batch_pages[-1]}...")

        # Fetch pages in parallel
        results = fetch_pages_parallel(query, batch_pages)
        total_stats['api_calls'] += len(batch_pages)

        # Check for failures
        batch_failed = [r['page'] for r in results if not r['success']]
        if batch_failed:
            failed_pages.extend(batch_failed)
            for r in results:
                if not r['success']:
                    print(f"  ✗ Page {r['page']} failed: {r['error']}")

        # Count successful results
        successful = [r for r in results if r['success']]
        total_items = sum(r['count'] for r in successful)

        if not successful:
            print(f"  ✗ All pages in batch failed")
            continue

        print(f"  ✓ Fetched {total_items} results from {len(successful)} pages")

        # Process and extract companies
        companies = process_search_results(ats_platform, results)
        print(f"  → {len(companies)} unique companies extracted")

        # Insert to database
        if companies:
            stats = insert_companies_batch(companies)
            total_stats['added'] += stats['added']
            total_stats['skipped'] += stats['skipped']
            print(f"  → DB: +{stats['added']} added, {stats['skipped']} already exist")

        # Accumulate results for backup
        all_results.extend(results)

        # Check if we got empty results (end of search)
        if total_items == 0:
            print(f"\n  No more results. Stopping early.")
            break

    # Save raw results backup
    if all_results:
        save_raw_results(ats_platform, all_results)

    # Summary
    print(f"\n{'='*60}")
    print(f"SUMMARY: {ats_platform}")
    print(f"{'='*60}")
    print(f"API calls: {total_stats['api_calls']}")
    print(f"Companies added: {total_stats['added']}")
    print(f"Companies skipped (already exist): {total_stats['skipped']}")

    if failed_pages:
        print(f"\n⚠️  Failed pages: {failed_pages}")
        print(f"   Resume with: --ats {ats_platform} --start-page {min(failed_pages)}")
    else:
        print(f"\n✓ All pages fetched successfully")


def main():
    parser = argparse.ArgumentParser(
        description='Discover companies on ATS platforms via Google dorking',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 dork_ats.py --ats ashbyhq
  python3 dork_ats.py --ats lever --max-pages 20
  python3 dork_ats.py --ats greenhouse --start-page 5
        """
    )

    parser.add_argument(
        '--ats',
        required=True,
        choices=list(ATS_PLATFORMS.keys()),
        help='ATS platform to dork'
    )

    parser.add_argument(
        '--start-page',
        type=int,
        default=1,
        help='Page to start from (default: 1)'
    )

    parser.add_argument(
        '--max-pages',
        type=int,
        default=10,
        help='Maximum pages to fetch (default: 10, which is Google CSE max = 100 results)'
    )

    args = parser.parse_args()

    # Validate
    check_credentials()

    if args.start_page < 1:
        print("Error: --start-page must be >= 1")
        sys.exit(1)

    if args.max_pages < 1:
        print("Error: --max-pages must be >= 1")
        sys.exit(1)

    # Google CSE limit: max 100 results (10 pages)
    if args.start_page + args.max_pages - 1 > 10:
        effective_max = max(1, 10 - args.start_page + 1)
        print(f"Note: Google CSE limits to 100 results (10 pages). Capping to {effective_max} pages.")
        args.max_pages = effective_max

    # Run
    dork_ats(args.ats, args.start_page, args.max_pages)


if __name__ == '__main__':
    main()
