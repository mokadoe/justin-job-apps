#!/usr/bin/env python3
"""
Y Combinator Company Directory Aggregator - PoC

Uses YC's Algolia API to fetch all YC companies:
https://www.ycombinator.com/companies

YC companies are high-quality targets:
- Well-funded startups (5,598 companies)
- Strong engineering culture
- New grad friendly (many early stage)
"""

import sys
import sqlite3
import re
import requests
from pathlib import Path
from urllib.parse import urlparse
import time

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scrapers.ats_utils import extract_slug_from_ats_url

DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "jobs.db"

# YC uses Algolia to serve company data
ALGOLIA_APP_ID = "45BWZJ1SGC"
ALGOLIA_API_KEY = "MjBjYjRiMzY0NzdhZWY0NjExY2NhZjYxMGIxYjc2MTAwNWFkNTkwNTc4NjgxYjU0YzFhYTY2ZGQ5OGY5NDMxZnJlc3RyaWN0SW5kaWNlcz0lNUIlMjJZQ0NvbXBhbnlfcHJvZHVjdGlvbiUyMiUyQyUyMllDQ29tcGFueV9CeV9MYXVuY2hfRGF0ZV9wcm9kdWN0aW9uJTIyJTVEJnRhZ0ZpbHRlcnM9JTVCJTIyeWNkY19wdWJsaWMlMjIlNUQmYW5hbHl0aWNzVGFncz0lNUIlMjJ5Y2RjJTIyJTVE"
ALGOLIA_INDEX = "YCCompany_production"
ALGOLIA_URL = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"

# ATS platform detection patterns
ATS_PATTERNS = {
    'greenhouse': ['greenhouse.io', 'boards.greenhouse.io'],
    'lever': ['lever.co', 'jobs.lever.co'],
    'ashbyhq': ['ashbyhq.com', 'jobs.ashbyhq.com'],
    'workday': ['myworkdayjobs.com', 'wd1.myworkdayjobs.com', 'wd5.myworkdayjobs.com'],
    'icims': ['icims.com'],
    'smartrecruiters': ['smartrecruiters.com', 'jobs.smartrecruiters.com'],
    'jobvite': ['jobvite.com'],
    'taleo': ['taleo.net'],
}

SUPPORTED_ATS = {'greenhouse', 'lever', 'ashbyhq'}


def detect_ats_from_url(job_url: str) -> tuple[str, str]:
    """Detect ATS platform from job URL."""
    parsed = urlparse(job_url)
    domain = parsed.netloc.lower()

    for ats_platform, patterns in ATS_PATTERNS.items():
        for pattern in patterns:
            if pattern in domain:
                if ats_platform == 'greenhouse':
                    match = re.search(r'greenhouse\.io/([^/]+)', job_url)
                    if match:
                        return ats_platform, f"https://boards.greenhouse.io/{match.group(1)}"

                elif ats_platform == 'lever':
                    match = re.search(r'lever\.co/([^/]+)', job_url)
                    if match:
                        return ats_platform, f"https://jobs.lever.co/{match.group(1)}"

                elif ats_platform == 'ashbyhq':
                    match = re.search(r'ashbyhq\.com/([^/]+)', job_url)
                    if match:
                        return ats_platform, f"https://jobs.ashbyhq.com/{match.group(1)}"

                else:
                    return ats_platform, job_url

    return 'unknown', job_url


def fetch_yc_companies():
    """
    Fetch all YC companies using their Algolia API.

    Returns:
        List of (company_name, website_url) tuples
    """
    print("Fetching YC companies from Algolia API...")

    headers = {
        "X-Algolia-Application-Id": ALGOLIA_APP_ID,
        "X-Algolia-API-Key": ALGOLIA_API_KEY,
        "Content-Type": "application/json"
    }

    companies_data = []
    page = 0
    hits_per_page = 1000

    while True:
        # Fetch paginated results
        data = {
            "query": "",
            "hitsPerPage": hits_per_page,
            "page": page
        }

        response = requests.post(ALGOLIA_URL, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()

        hits = result.get('hits', [])
        if not hits:
            break

        for hit in hits:
            company_name = hit.get('name')
            website = hit.get('website', '').strip()

            if company_name and website:
                companies_data.append((company_name, website))

        print(f"  Fetched page {page + 1}: {len(hits)} companies")

        # Check if there are more pages
        if page >= result.get('nbPages', 0) - 1:
            break

        page += 1
        time.sleep(0.5)  # Be respectful with API calls

    print(f"\nTotal YC companies fetched: {len(companies_data)}")
    return companies_data


def try_ats_detection(company_name: str, website: str) -> tuple[str, str]:
    """
    Try to detect ATS platform for a company by checking common patterns.

    Args:
        company_name: Company name
        website: Company website

    Returns:
        (ats_platform, ats_url) tuple
    """
    # Slugify company name (simple version)
    slug = company_name.lower().replace(' ', '-').replace('.', '').replace(',', '')

    # Try common ATS patterns
    ats_patterns = [
        ('greenhouse', f'https://boards.greenhouse.io/{slug}'),
        ('lever', f'https://jobs.lever.co/{slug}'),
        ('ashbyhq', f'https://jobs.ashbyhq.com/{slug}'),
    ]

    for ats_platform, ats_url in ats_patterns:
        # Quick HEAD request to check if URL exists
        try:
            response = requests.head(ats_url, timeout=2, allow_redirects=True)
            if response.status_code == 200:
                return ats_platform, ats_url
        except:
            continue

    # If no ATS found, use website as fallback
    return 'unknown', website


def add_companies_to_db(companies_data: list, max_to_check: int = 100):
    """
    Add discovered companies to database.

    Args:
        companies_data: List of (company_name, website) tuples
        max_to_check: Maximum number of companies to check for ATS
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    stats = {
        'total': len(companies_data),
        'added': 0,
        'skipped_exists': 0,
        'supported': 0,
        'unsupported': 0,
        'checked_ats': 0,
    }

    print(f"Checking first {max_to_check} companies for ATS...")

    for idx, (company_name, website) in enumerate(companies_data):
        # Only check ATS for first N companies
        if idx < max_to_check:
            ats_platform, ats_url = try_ats_detection(company_name, website)
            stats['checked_ats'] += 1
            if idx % 10 == 0:
                print(f"  {idx}/{max_to_check}...")
        else:
            ats_platform = 'unknown'
            ats_url = website

        is_active = 1 if ats_platform in SUPPORTED_ATS else 0
        ats_slug = extract_slug_from_ats_url(ats_platform, ats_url)

        if is_active:
            stats['supported'] += 1
        else:
            stats['unsupported'] += 1

        cursor.execute("SELECT id FROM companies WHERE name = ?", (company_name,))
        existing = cursor.fetchone()

        if existing:
            stats['skipped_exists'] += 1
        else:
            cursor.execute("""
                INSERT INTO companies (name, discovery_source, ats_platform, ats_slug, ats_url, is_active, website)
                VALUES (?, 'yc', ?, ?, ?, ?, ?)
            """, (company_name, ats_platform, ats_slug, ats_url, is_active, website))
            stats['added'] += 1

    conn.commit()
    conn.close()

    return stats


def main():
    print("Y Combinator Aggregator")
    print("=" * 60)

    # Fetch YC companies from Algolia API
    companies_data = fetch_yc_companies()

    # Add to database (check ATS for first 100 companies)
    stats = add_companies_to_db(companies_data, max_to_check=100)

    print()
    print(f"Total: {stats['total']} | Added: {stats['added']} | Exists: {stats['skipped_exists']}")
    print(f"Supported: {stats['supported']} | Unsupported: {stats['unsupported']}")


if __name__ == "__main__":
    main()
