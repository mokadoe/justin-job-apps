"""
Manual Companies Aggregator

Reads company names from data/manual_companies.txt and discovers their ATS platforms
by probing Ashby, Greenhouse, and Lever APIs.

File format:
    # Comments start with #
    Anduril
    EliseAI (MeetElise)  # Parentheses indicate aliases to try
    Wiz (US HQ)          # Descriptive parentheses are ignored
"""

import re
from pathlib import Path

from .types import CompanyLead, AggregatorResult
from .utils import probe_ats_apis


MANUAL_FILE = Path(__file__).parent.parent.parent.parent / "data" / "manual_companies.txt"


class ManualAggregator:
    """Aggregator for manually specified companies."""

    name = 'manual'

    def __init__(self, force: bool = False, limit: int | None = None):
        """
        Initialize manual aggregator.

        Args:
            force: Ignored (kept for CLI compatibility, runner handles deduplication)
            limit: Maximum number of companies to process
        """
        self.limit = limit

    def fetch(self) -> AggregatorResult:
        """
        Read companies from file and probe for ATS platforms.

        Returns:
            AggregatorResult with discovered companies (no job leads)
        """
        print(f"Reading companies from {MANUAL_FILE.name}...")
        print(f"  Path: {MANUAL_FILE}")

        if not MANUAL_FILE.exists():
            print(f"  ✗ File not found!")
            print(f"  Create {MANUAL_FILE.name} with one company name per line")
            return AggregatorResult(companies=[], jobs=[])

        # Load and parse companies from file
        company_entries = []
        with open(MANUAL_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                name, aliases = self._parse_company_line(line)
                company_entries.append((name, aliases))

        print(f"  ✓ Loaded {len(company_entries)} companies")

        if self.limit:
            company_entries = company_entries[:self.limit]
            print(f"  Limited to first {self.limit} companies")

        print(f"\nProbing ATS APIs for {len(company_entries)} companies...")
        print("  (checking Ashby, Lever, Greenhouse)")
        print("=" * 60)

        companies = []
        found = 0
        ats_counts = {}  # Track ATS platform distribution

        for i, (company_name, aliases) in enumerate(company_entries, 1):
            alias_str = f" (alias: {aliases[0]})" if aliases else ""
            print(f"[{i}/{len(company_entries)}] {company_name}{alias_str}...", end=" ", flush=True)

            ats_platform, slug, ats_url = probe_ats_apis(company_name, aliases)

            # Track ATS distribution
            ats_counts[ats_platform] = ats_counts.get(ats_platform, 0) + 1

            if ats_platform != 'unknown':
                found += 1
                print(f"✓ {ats_platform}")
            else:
                print("✗ Not found")

            companies.append(CompanyLead(
                name=company_name,
                website=None,
                ats_platform=ats_platform,
                ats_url=ats_url,
            ))

        print("=" * 60)

        # Print ATS breakdown
        if ats_counts:
            print(f"\nATS Discovery Results:")
            for platform, count in sorted(ats_counts.items(), key=lambda x: -x[1]):
                if platform != 'unknown':
                    print(f"  ✓ {platform}: {count}")
            unknown = ats_counts.get('unknown', 0)
            if unknown:
                print(f"  ✗ unknown/none: {unknown}")

        print(f"\nFound {found}/{len(company_entries)} companies with supported ATS")

        # No job leads for manual aggregator
        return AggregatorResult(companies=companies, jobs=[])

    def _parse_company_line(self, line: str) -> tuple[str, list[str]]:
        """
        Parse a company line, extracting name and any aliases in parentheses.

        Examples:
            "EliseAI (MeetElise)" -> ("EliseAI", ["MeetElise"])
            "Anduril" -> ("Anduril", [])
            "Wiz (US HQ)" -> ("Wiz", [])  # Ignores non-name parentheses
        """
        # Extract parenthetical content
        match = re.match(r'^([^(]+)\s*\(([^)]+)\)\s*$', line)
        if match:
            name = match.group(1).strip()
            paren_content = match.group(2).strip()

            # Check if parenthetical is an alias (not descriptive like "US HQ")
            descriptive_patterns = ['HQ', 'US ', 'ops', 'Office']
            is_alias = not any(p in paren_content for p in descriptive_patterns)

            if is_alias:
                return name, [paren_content]

        return line, []
