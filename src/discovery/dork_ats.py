#!/usr/bin/env python3
"""
Google Dorking for ATS Platform Discovery

Discovers companies on major ATS platforms using Google Custom Search API.
Saves raw results and extracts company information for database insertion.
"""

import os
import sys
import json
import requests
import time
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

# Configuration
ATS_PLATFORMS = {
    'ashbyhq': {
        'search_query': 'site:jobs.ashbyhq.com',
        'url_pattern': 'jobs.ashbyhq.com/',
        'base_url': 'https://jobs.ashbyhq.com/'
    },
    'lever': {
        'search_query': 'site:jobs.lever.co',
        'url_pattern': 'jobs.lever.co/',
        'base_url': 'https://jobs.lever.co/'
    },
    'greenhouse': {
        'search_query': 'site:boards.greenhouse.io',
        'url_pattern': 'boards.greenhouse.io/',
        'base_url': 'https://boards.greenhouse.io/'
    }
}

# Output directory for raw JSON results
OUTPUT_DIR = Path(__file__).parent.parent.parent / 'data' / 'dork_results'
OUTPUT_DIR.mkdir(exist_ok=True)

# Google Custom Search API credentials
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')

if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
    print("Error: GOOGLE_API_KEY and GOOGLE_CSE_ID must be set in .env file")
    sys.exit(1)


def google_search(query: str, max_pages: int = 3) -> list:
    """
    Execute Google Custom Search API query and paginate through results.

    Args:
        query: Search query string
        max_pages: Number of pages to fetch (each page = 10 results, 1 API call)

    Returns:
        List of search result items
    """
    results = []

    # Google CSE API returns max 10 results per request
    print(f"  Fetching {max_pages} pages ({max_pages * 10} results max)...")

    for page in range(max_pages):
        start_index = page * 10 + 1

        try:
            response = requests.get(
                'https://www.googleapis.com/customsearch/v1',
                params={
                    'key': GOOGLE_API_KEY,
                    'cx': GOOGLE_CSE_ID,
                    'q': query,
                    'start': start_index,
                    'num': 10,  # Max per request
                },
                timeout=10
            )

            response.raise_for_status()
            data = response.json()

            items = data.get('items', [])
            if not items:
                print(f"    No more results at page {page + 1}")
                break

            results.extend(items)
            print(f"    Page {page + 1}: {len(items)} results")

            # Rate limiting - be nice to Google
            time.sleep(0.5)

        except requests.exceptions.RequestException as e:
            print(f"    Error fetching page {page + 1}: {e}")
            break

    return results


def extract_company_slug(url: str, ats_platform: str) -> str | None:
    """
    Extract company slug from ATS URL.

    Examples:
        https://boards.greenhouse.io/airbnb -> airbnb
        https://jobs.lever.co/figma/abc123 -> figma
        https://jobs.ashbyhq.com/openai -> openai
    """
    import re

    patterns = {
        'greenhouse': r'boards\.greenhouse\.io/([^/\?#]+)',
        'lever': r'jobs\.lever\.co/([^/\?#]+)',
        'ashbyhq': r'jobs\.ashbyhq\.com/([^/\?#]+)',
    }

    pattern = patterns.get(ats_platform)
    if not pattern:
        return None

    match = re.search(pattern, url)
    if match:
        return match.group(1)

    return None


def verify_ats_url(url: str) -> bool:
    """
    Verify that an ATS URL is active (returns 200).
    Uses HEAD request for efficiency.
    """
    try:
        response = requests.head(url, timeout=5, allow_redirects=True)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def process_search_results(ats_platform: str, search_results: list) -> list:
    """
    Process raw Google search results and extract company information.

    Returns:
        List of dicts with company info for database insertion.
    """
    companies = []
    slugs_seen = set()

    print(f"  Processing {len(search_results)} results...")

    for result in search_results:
        url = result.get('link', '')

        # Extract company slug
        slug = extract_company_slug(url, ats_platform)
        if not slug:
            continue

        # Skip duplicates
        if slug in slugs_seen:
            continue
        slugs_seen.add(slug)

        # Build canonical ATS URL
        base_url = ATS_PLATFORMS[ats_platform]['base_url']
        ats_url = f"{base_url}{slug}"

        # Verify URL is active
        is_active = verify_ats_url(ats_url)
        status = "✓" if is_active else "✗"
        print(f"    {status} {slug}")

        companies.append({
            'company_slug': slug,
            'ats_platform': ats_platform,
            'ats_slug': slug,
            'ats_url': ats_url,
            'is_active': is_active,
            'discovery_source': 'google_dork',
        })

        time.sleep(0.2)

    return companies


def main():
    """Main execution: Dork each ATS platform and save results."""
    print("Google Dorking - ATS Platform Discovery")
    print("=" * 60)

    all_companies = []
    stats = {
        'api_calls': 0,
        'companies_discovered': 0,
        'active_companies': 0,
    }

    # Dork each ATS platform
    for ats_platform, config in ATS_PLATFORMS.items():
        print(f"\n{ats_platform.upper()}: {config['search_query']}")

        # Execute search (3 pages = 3 API calls)
        search_results = google_search(config['search_query'], max_pages=3)
        stats['api_calls'] += 3

        # Save raw results
        raw_file = OUTPUT_DIR / f'{ats_platform}_raw.json'
        with open(raw_file, 'w') as f:
            json.dump(search_results, f, indent=2)

        # Process results
        companies = process_search_results(ats_platform, search_results)
        all_companies.extend(companies)

        active = sum(1 for c in companies if c['is_active'])
        stats['companies_discovered'] += len(companies)
        stats['active_companies'] += active

        print(f"  {len(companies)} companies ({active} active)")

    # Save processed companies
    companies_file = OUTPUT_DIR / 'companies_discovered.json'
    with open(companies_file, 'w') as f:
        json.dump(all_companies, f, indent=2)

    print()
    print(f"Total: {stats['companies_discovered']} companies ({stats['active_companies']} active)")
    print(f"API calls: {stats['api_calls']} (${stats['api_calls'] * 0.005:.3f})")
    print(f"Saved to: {companies_file}")


if __name__ == '__main__':
    main()
