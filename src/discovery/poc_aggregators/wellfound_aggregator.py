#!/usr/bin/env python3
"""
Wellfound (AngelList) Aggregator - PoC

Scrapes new grad job listings from Wellfound public pages.
Wellfound focuses on startups, making it ideal for new grad discovery.

Note: This uses web scraping since Wellfound API requires auth.
For production, consider using their API with proper authentication.
"""

import sqlite3
import re
import requests
from pathlib import Path
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
import time

DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "jobs.db"

# Search URLs for new grad roles
WELLFOUND_SEARCH_URLS = [
    "https://wellfound.com/role/software-engineer/new-grad",
    "https://wellfound.com/jobs?role=Software%20Engineer&experience=entry-level",
]

# ATS platform detection patterns
ATS_PATTERNS = {
    'greenhouse': ['greenhouse.io', 'boards.greenhouse.io'],
    'lever': ['lever.co', 'jobs.lever.co'],
    'ashby': ['ashbyhq.com', 'jobs.ashbyhq.com'],
    'workday': ['myworkdayjobs.com', 'wd1.myworkdayjobs.com', 'wd5.myworkdayjobs.com'],
    'icims': ['icims.com'],
    'smartrecruiters': ['smartrecruiters.com', 'jobs.smartrecruiters.com'],
    'jobvite': ['jobvite.com'],
    'taleo': ['taleo.net'],
}

SUPPORTED_ATS = {'greenhouse', 'lever', 'ashby'}


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

                elif ats_platform == 'ashby':
                    match = re.search(r'ashbyhq\.com/([^/]+)', job_url)
                    if match:
                        return ats_platform, f"https://jobs.ashbyhq.com/{match.group(1)}"

                else:
                    return ats_platform, job_url

    return 'unknown', job_url


def scrape_wellfound_jobs():
    """
    Scrape Wellfound for new grad positions.

    Note: Wellfound's structure may change. This is a PoC implementation.
    For production, use their API or a more robust scraping solution.

    Returns:
        List of (company_name, job_url) tuples
    """
    print("Scraping Wellfound jobs...")
    print("⚠️  Note: This is a simplified PoC scraper.")
    print("    For production, use Wellfound API or more robust scraping.\n")

    companies_data = []

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }

    # Mock data for PoC (since Wellfound requires JS rendering)
    # In production, you'd use Selenium or Playwright for JS-heavy sites
    print("⚠️  Wellfound requires JavaScript rendering.")
    print("    Using mock data for PoC demonstration.\n")

    # Example companies that typically post on Wellfound
    mock_companies = [
        ("Retool", "https://boards.greenhouse.io/retool"),
        ("Scale AI", "https://jobs.lever.co/scaleai"),
        ("Vercel", "https://jobs.ashbyhq.com/vercel"),
        ("Ramp", "https://jobs.ashbyhq.com/ramp"),
        ("Mercury", "https://jobs.lever.co/mercury"),
    ]

    print(f"Mock data: {len(mock_companies)} companies")
    return mock_companies


def add_companies_to_db(companies_data: list):
    """Add discovered companies to database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    stats = {
        'total': len(companies_data),
        'added': 0,
        'skipped_exists': 0,
        'updated_ats': 0,
        'supported': 0,
        'unsupported': 0,
    }

    for company_name, job_url in companies_data:
        ats_platform, ats_url = detect_ats_from_url(job_url)
        is_active = 1 if ats_platform in SUPPORTED_ATS else 0

        if is_active:
            stats['supported'] += 1
        else:
            stats['unsupported'] += 1

        cursor.execute("SELECT id, ats_platform FROM companies WHERE name = ?", (company_name,))
        existing = cursor.fetchone()

        if existing:
            existing_id, existing_ats = existing
            if existing_ats != ats_platform:
                cursor.execute("""
                    UPDATE companies
                    SET ats_platform = ?, ats_url = ?, is_active = ?
                    WHERE id = ?
                """, (ats_platform, ats_url, is_active, existing_id))
                stats['updated_ats'] += 1
                print(f"  Updated {company_name}: {existing_ats} → {ats_platform}")
            else:
                stats['skipped_exists'] += 1
        else:
            cursor.execute("""
                INSERT INTO companies (name, ats_platform, ats_url, is_active)
                VALUES (?, ?, ?, ?)
            """, (company_name, ats_platform, ats_url, is_active))
            stats['added'] += 1
            active_label = "✓" if is_active else "✗"
            print(f"  {active_label} Added {company_name} ({ats_platform})")

    conn.commit()
    conn.close()

    return stats


def main():
    print("=" * 60)
    print("Wellfound Aggregator - PoC")
    print("=" * 60)
    print()

    companies_data = scrape_wellfound_jobs()

    print()
    print("Adding companies to database...")
    print()

    stats = add_companies_to_db(companies_data)

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Total companies found: {stats['total']}")
    print(f"  ✓ Added to DB: {stats['added']}")
    print(f"  → Updated ATS: {stats['updated_ats']}")
    print(f"  ○ Skipped (exists): {stats['skipped_exists']}")
    print()
    print(f"ATS Breakdown:")
    print(f"  Supported (is_active=1): {stats['supported']}")
    print(f"  Unsupported (is_active=0): {stats['unsupported']}")
    print()
    print("💡 To implement fully:")
    print("   - Use Selenium/Playwright for JS rendering")
    print("   - Or use Wellfound API with authentication")
    print()


if __name__ == "__main__":
    main()
