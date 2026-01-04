"""
Simplify Jobs Aggregator

Scrapes new grad job listings from SimplifyJobs GitHub repo:
https://github.com/SimplifyJobs/New-Grad-Positions

For supported ATS (Ashby, Greenhouse, Lever):
- Returns CompanyLead with ATS info for bulk scraping

For unsupported ATS (Workday, Oracle, etc.):
- Returns JobLead for later Sonnet analysis
"""

import requests
from bs4 import BeautifulSoup

from .types import CompanyLead, JobLead, AggregatorResult
from .utils import detect_ats_from_url, extract_clean_website, SUPPORTED_ATS


SIMPLIFY_README_URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md"


class SimplifyAggregator:
    """Aggregator for SimplifyJobs GitHub new grad positions."""

    name = 'simplify'

    def fetch(self) -> AggregatorResult:
        """
        Fetch companies and job leads from Simplify Jobs README.

        Returns:
            AggregatorResult with:
            - companies: All discovered companies with ATS info
            - jobs: Job URLs for unsupported ATS platforms
        """
        print("Fetching Simplify Jobs README...")
        print(f"  URL: {SIMPLIFY_README_URL}")
        response = requests.get(SIMPLIFY_README_URL, timeout=30)
        response.raise_for_status()
        print(f"  ✓ Downloaded ({len(response.text):,} bytes)")

        companies = []
        jobs = []
        seen_companies = set()  # Dedupe by company name
        ats_counts = {}  # Track ATS platform distribution

        # Parse markdown table
        print("Parsing job listings table...")
        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.find_all('tr')
        print(f"  Found {len(rows)} table rows")

        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 4:
                continue

            # Extract company name
            company_cell = cells[0]
            company_link = company_cell.find('a')
            if company_link:
                company_name = company_link.get_text(strip=True)
            else:
                company_name = company_cell.get_text(strip=True)

            if not company_name or company_name.lower() in seen_companies:
                continue

            # Extract job URL from apply column
            apply_cell = cells[3]
            apply_links = apply_cell.find_all('a')

            job_url = None
            for link in apply_links:
                href = link.get('href', '')
                if 'simplify.jobs' not in href and href.startswith('http'):
                    job_url = href
                    break

            if not job_url:
                continue

            seen_companies.add(company_name.lower())

            # Detect ATS platform
            ats_platform, ats_url = detect_ats_from_url(job_url)
            website = extract_clean_website(job_url)

            # Track ATS distribution
            ats_counts[ats_platform] = ats_counts.get(ats_platform, 0) + 1

            companies.append(CompanyLead(
                name=company_name,
                website=website,
                ats_platform=ats_platform,
                ats_url=ats_url,
            ))

            # Queue job URL for unsupported ATS
            if ats_platform not in SUPPORTED_ATS:
                jobs.append(JobLead(
                    company_name=company_name,
                    job_url=job_url,
                ))

            # Progress every 50 companies
            if len(companies) % 50 == 0:
                print(f"  Parsed {len(companies)} companies...")

        # Print ATS breakdown
        print(f"\nATS Platform Breakdown:")
        supported_count = 0
        for platform, count in sorted(ats_counts.items(), key=lambda x: -x[1]):
            marker = "✓" if platform in SUPPORTED_ATS else "✗"
            print(f"  {marker} {platform}: {count}")
            if platform in SUPPORTED_ATS:
                supported_count += count

        print(f"\nFound {len(companies)} companies total")
        print(f"  {supported_count} with supported ATS (Ashby/Lever/Greenhouse)")
        print(f"  {len(jobs)} job leads queued for unsupported ATS")
        return AggregatorResult(companies=companies, jobs=jobs)
