#!/usr/bin/env python3
"""
Simplify Jobs Aggregator - PoC

Scrapes new grad job listings from SimplifyJobs GitHub repo:
https://github.com/SimplifyJobs/New-Grad-Positions

Extracts:
- Company names
- Job links (to detect ATS platform)
- Adds companies to database with detected ATS platform
"""

import sys
import re
import requests
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scrapers.ats_utils import extract_slug_from_ats_url

# Add utils to path for db import
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "utils"))
from db import get_connection, is_remote


def _placeholder():
    """Return SQL placeholder for current database."""
    return "%s" if is_remote() else "?"


SIMPLIFY_README_URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md"

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

# Supported ATS platforms (will set is_active=1)
SUPPORTED_ATS = {'greenhouse', 'lever', 'ashbyhq'}


def detect_ats_from_url(job_url: str) -> tuple[str, str]:
    """
    Detect ATS platform from job URL.

    Returns:
        (ats_platform, ats_url) tuple
    """
    parsed = urlparse(job_url)
    domain = parsed.netloc.lower()

    # Check each ATS pattern
    for ats_platform, patterns in ATS_PATTERNS.items():
        for pattern in patterns:
            if pattern in domain:
                # Construct base ATS URL
                if ats_platform == 'greenhouse':
                    # Extract company slug from URL
                    match = re.search(r'greenhouse\.io/([^/]+)', job_url)
                    if match:
                        company_slug = match.group(1)
                        return ats_platform, f"https://boards.greenhouse.io/{company_slug}"

                elif ats_platform == 'lever':
                    match = re.search(r'lever\.co/([^/]+)', job_url)
                    if match:
                        company_slug = match.group(1)
                        return ats_platform, f"https://jobs.lever.co/{company_slug}"

                elif ats_platform == 'ashbyhq':
                    match = re.search(r'ashbyhq\.com/([^/]+)', job_url)
                    if match:
                        company_slug = match.group(1)
                        return ats_platform, f"https://jobs.ashbyhq.com/{company_slug}"

                else:
                    # Unsupported ATS - just return the job URL
                    return ats_platform, job_url

    # Unknown ATS
    return 'unknown', job_url


def parse_simplify_readme():
    """
    Parse Simplify Jobs README to extract companies and job links.

    The README uses HTML table format with:
    - Company name in: <td><strong><a href="...">Company</a></strong></td>
    - Job link in: <a href="JOB_URL">Apply button</a>

    Returns:
        List of (company_name, job_url) tuples
    """
    print("Fetching Simplify Jobs README...")
    response = requests.get(SIMPLIFY_README_URL)
    response.raise_for_status()

    readme_content = response.text

    # Parse with BeautifulSoup
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(readme_content, 'html.parser')

    companies_data = []

    # Find all table rows
    rows = soup.find_all('tr')

    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 4:
            continue

        # First cell: company name
        company_cell = cells[0]
        company_link = company_cell.find('a')
        if not company_link:
            # Try getting text directly (some companies don't have links)
            company_name = company_cell.get_text(strip=True)
            if not company_name:
                continue
        else:
            company_name = company_link.get_text(strip=True)

        # Fourth cell (index 3): contains apply button with job URL
        apply_cell = cells[3]
        apply_links = apply_cell.find_all('a')

        for link in apply_links:
            href = link.get('href', '')
            # Look for the actual job board URL (not Simplify internal links)
            if 'simplify.jobs' not in href and href.startswith('http'):
                companies_data.append((company_name, href))
                break

    print(f"Found {len(companies_data)} job listings in Simplify Jobs README")

    return companies_data


def add_companies_to_db(companies_data: list):
    """
    Add discovered companies to database.

    Args:
        companies_data: List of (company_name, job_url) tuples
    """
    p = _placeholder()
    stats = {
        'total': len(companies_data),
        'added': 0,
        'skipped_exists': 0,
        'supported': 0,
        'unsupported': 0,
    }

    with get_connection() as conn:
        cursor = conn.cursor()

        for company_name, job_url in companies_data:
            # Detect ATS platform
            ats_platform, ats_url = detect_ats_from_url(job_url)
            is_active = 1 if ats_platform in SUPPORTED_ATS else 0
            ats_slug = extract_slug_from_ats_url(ats_platform, ats_url)

            if is_active:
                stats['supported'] += 1
            else:
                stats['unsupported'] += 1

            # Check if company exists
            cursor.execute(f"SELECT id FROM companies WHERE name = {p}", (company_name,))
            existing = cursor.fetchone()

            if existing:
                stats['skipped_exists'] += 1
            else:
                # Insert new company with discovery_source
                cursor.execute(f"""
                    INSERT INTO companies (name, discovery_source, ats_platform, ats_slug, ats_url, is_active)
                    VALUES ({p}, 'simplify', {p}, {p}, {p}, {p})
                """, (company_name, ats_platform, ats_slug, ats_url, is_active))
                stats['added'] += 1
                active_label = "✓" if is_active else "✗"
                print(f"  {active_label} {company_name} ({ats_platform})")

        conn.commit()

    return stats


def main():
    print("Simplify Jobs Aggregator")
    print("=" * 60)

    # Parse Simplify Jobs README
    companies_data = parse_simplify_readme()

    # Add to database
    stats = add_companies_to_db(companies_data)

    print()
    print(f"Total: {stats['total']} | Added: {stats['added']} | Exists: {stats['skipped_exists']}")
    print(f"Supported: {stats['supported']} | Unsupported: {stats['unsupported']}")


if __name__ == "__main__":
    main()
