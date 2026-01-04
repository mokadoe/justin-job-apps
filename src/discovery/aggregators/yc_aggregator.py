"""
Y Combinator Company Directory Aggregator

Uses yc-oss API (https://github.com/yc-oss/api) to fetch all YC companies.
This is a static JSON file updated daily with 5,598+ companies.

YC companies are high-quality targets:
- Well-funded startups (5,598 companies)
- Strong engineering culture
- New grad friendly (many early stage)

Note: yc-oss only provides company names and websites, no job URLs.
We probe ATS APIs to discover which platforms companies use.
"""

import requests

from .types import CompanyLead, AggregatorResult
from .utils import probe_companies_parallel, SUPPORTED_ATS


YC_OSS_API_URL = "https://yc-oss.github.io/api/companies/all.json"


class YCAggregator:
    """Aggregator for Y Combinator companies via yc-oss API."""

    name = 'yc'

    def __init__(self, check_ats_count: int = None):
        """
        Initialize YC aggregator.

        Args:
            check_ats_count: Number of companies to probe for ATS platforms.
                            Default None = check ALL companies.
                            Set to 0 to skip ATS detection.
        """
        self.check_ats_count = check_ats_count  # None means check all

    def fetch(self) -> AggregatorResult:
        """
        Fetch YC companies from yc-oss API.

        Returns:
            AggregatorResult with companies (no job leads - yc-oss doesn't have job URLs)
        """
        print("Fetching YC companies from yc-oss API...")
        print(f"  URL: {YC_OSS_API_URL}")
        response = requests.get(YC_OSS_API_URL, timeout=30)
        response.raise_for_status()
        raw_data = response.json()
        print(f"  ✓ Downloaded {len(raw_data):,} companies")

        # Extract company names and websites
        company_data = {}
        for item in raw_data:
            name = item.get('name')
            if name:
                company_data[name] = (item.get('website') or '').strip() or None

        company_names = list(company_data.keys())

        # Determine probing limit
        if self.check_ats_count == 0:
            print("\nSkipping ATS probing (--check 0)")
            probe_results = []
            ats_counts = {}
        else:
            # Use parallel probing
            probe_results, ats_counts = probe_companies_parallel(
                company_names,
                max_workers=30,
                progress_every=100,
                limit=self.check_ats_count,
            )

        # Build company leads
        # First, create a lookup from probe results
        probe_lookup = {r.company_name: r for r in probe_results}

        companies = []
        for name in company_names:
            website = company_data[name]

            if name in probe_lookup:
                result = probe_lookup[name]
                ats_platform = result.ats_platform
                ats_url = result.ats_url
            else:
                ats_platform = 'unknown'
                ats_url = None

            companies.append(CompanyLead(
                name=name,
                website=website,
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
        print(f"\nTotal: {len(companies):,} YC companies, {supported} with supported ATS")

        # No job leads - yc-oss doesn't provide job URLs
        return AggregatorResult(companies=companies, jobs=[])
