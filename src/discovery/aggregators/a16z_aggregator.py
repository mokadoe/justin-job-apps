"""
Andreessen Horowitz (a16z) Portfolio Aggregator

Scrapes a16z's investment list page to get ~1,100 portfolio companies.
https://a16z.com/investment-list/

Note: a16z only provides company names (no websites or job URLs).
We probe ATS APIs to discover which platforms companies use.
"""

import re
import requests

from .types import CompanyLead, AggregatorResult
from .utils import probe_companies_parallel, SUPPORTED_ATS


A16Z_URL = "https://a16z.com/investment-list/"


class A16ZAggregator:
    """Aggregator for a16z portfolio companies."""

    name = 'a16z'

    def __init__(self, check_ats: bool = True, max_check: int = None):
        """
        Initialize a16z aggregator.

        Args:
            check_ats: Whether to probe ATS APIs for companies (default True)
            max_check: Maximum number of companies to probe. None = check ALL.
        """
        self.check_ats = check_ats
        self.max_check = max_check  # None means check all

    def fetch(self) -> AggregatorResult:
        """
        Fetch a16z portfolio companies.

        Returns:
            AggregatorResult with companies (no job leads)
        """
        print("Fetching a16z portfolio from investment list page...")
        print(f"  URL: {A16Z_URL}")

        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(A16Z_URL, headers=headers, timeout=30)
        response.raise_for_status()
        html = response.text
        print(f"  ✓ Downloaded ({len(html):,} bytes)")

        # Find simple li tags with just text (company names)
        print("Parsing portfolio companies...")
        pattern = r'<li>([^<>]+)</li>'
        matches = re.findall(pattern, html)

        # Filter out navigation items
        skip_terms = ['news', 'portfolio', 'team', 'about', 'jobs', 'connect', 'crypto',
                      'consumer', 'enterprise', 'fintech', 'infrastructure', 'growth',
                      'bio', 'health', 'speedrun', 'perennial', 'talent', 'cultural',
                      'american dynamism', 'cookie', 'privacy', 'terms', 'ai']

        company_names = []
        for m in matches:
            m = m.strip()
            if m and len(m) > 1:
                if not any(skip.lower() == m.lower() for skip in skip_terms):
                    company_names.append(m)

        print(f"  Found {len(company_names)} portfolio companies")

        # Probe ATS APIs in parallel
        if self.check_ats:
            probe_results, ats_counts = probe_companies_parallel(
                company_names,
                max_workers=30,
                progress_every=100,
                limit=self.max_check,
            )
        else:
            print("\nSkipping ATS probing (use --check-ats to enable)")
            probe_results = []
            ats_counts = {}

        # Build company leads
        probe_lookup = {r.company_name: r for r in probe_results}

        companies = []
        for name in company_names:
            if name in probe_lookup:
                result = probe_lookup[name]
                ats_platform = result.ats_platform
                ats_url = result.ats_url
            else:
                ats_platform = 'unknown'
                ats_url = None

            companies.append(CompanyLead(
                name=name,
                website=None,  # a16z doesn't provide websites
                ats_platform=ats_platform,
                ats_url=ats_url,
            ))

        # Print ATS breakdown
        if ats_counts:
            print(f"\nATS Discovery Results:")
            for platform, count in sorted(ats_counts.items(), key=lambda x: -x[1]):
                if platform != 'unknown':
                    print(f"  ✓ {platform}: {count}")
            unknown = ats_counts.get('unknown', 0)
            print(f"  ✗ unknown/none: {unknown}")

        supported = sum(1 for c in companies if c.ats_platform in SUPPORTED_ATS)
        print(f"\nTotal: {len(companies)} a16z companies, {supported} with supported ATS")

        # No job leads - a16z doesn't provide job URLs
        return AggregatorResult(companies=companies, jobs=[])
