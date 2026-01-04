"""
Shared utilities for aggregators.

Provides ATS detection, URL parsing, and probing functions.
"""

import re
import time
import requests
from urllib.parse import urlparse
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass


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

# ATS platforms we can scrape via API
SUPPORTED_ATS = {'greenhouse', 'lever', 'ashbyhq'}


def detect_ats_from_url(job_url: str) -> tuple[str, str | None]:
    """
    Detect ATS platform from a job URL.

    Args:
        job_url: URL to a job posting or careers page

    Returns:
        Tuple of (ats_platform, ats_url) where:
        - ats_platform: 'ashbyhq', 'greenhouse', 'lever', or 'unknown'
        - ats_url: Normalized ATS board URL, or original URL if unknown
    """
    if not job_url:
        return 'unknown', None

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
                    # Unsupported ATS - return platform name but original URL
                    return ats_platform, job_url

    return 'unknown', job_url


def extract_clean_website(job_url: str) -> str | None:
    """
    Extract clean company website from a job URL.

    Filters out generic ATS domains and returns the base company domain.

    Args:
        job_url: URL to extract domain from

    Returns:
        Clean website URL like 'https://stripe.com', or None if generic domain
    """
    if not job_url:
        return None

    parsed = urlparse(job_url)
    domain = parsed.netloc.lower()

    # Skip generic ATS/job platform domains
    generic_domains = [
        'oraclecloud.com', 'myworkdayjobs.com', 'icims.com',
        'smartrecruiters.com', 'jobvite.com', 'taleo.net',
        'greenhouse.io', 'lever.co', 'ashbyhq.com'
    ]

    for generic in generic_domains:
        if generic in domain:
            return None

    # Extract base domain (e.g., 'careers.stripe.com' -> 'stripe.com')
    parts = domain.split('.')
    if len(parts) >= 2:
        base_domain = '.'.join(parts[-2:])
        return f"https://{base_domain}"

    return None


def generate_slugs(company_name: str, aliases: list[str] | None = None) -> list[str]:
    """
    Generate possible ATS slug variations for a company name.

    Args:
        company_name: Primary company name
        aliases: Alternative names to try (e.g., "MeetElise" for "EliseAI")

    Returns:
        List of slug variations to probe
    """
    slugs = set()

    names_to_try = [company_name]
    if aliases:
        names_to_try.extend(aliases)

    for name in names_to_try:
        clean = name.lower()

        # Basic variations
        slugs.add(clean.replace(' ', '-'))
        slugs.add(clean.replace(' ', ''))
        slugs.add(clean.replace(' ', '-').replace('&', 'and'))
        slugs.add(clean.replace(' ', '').replace('&', 'and'))
        slugs.add(clean.replace(' ', '-').replace('.', ''))
        slugs.add(clean.replace('.', '').replace(' ', ''))

        # Remove common suffixes
        for suffix in [' ai', ' inc', ' labs', ' health', ' robotics']:
            if clean.endswith(suffix):
                base = clean[:-len(suffix)]
                slugs.add(base.replace(' ', '-'))
                slugs.add(base.replace(' ', ''))

        # Handle special characters
        slug_clean = ''.join(c for c in clean if c.isalnum() or c in ' -')
        slugs.add(slug_clean.replace(' ', '-'))
        slugs.add(slug_clean.replace(' ', ''))

    # Remove empty strings and duplicates
    return [s for s in slugs if s]


def _probe_ashby(slug: str, timeout: int = 5) -> Optional[dict]:
    """Check if company exists on Ashby with jobs."""
    try:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        response = requests.get(url, params={'includeCompensation': 'true'}, timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            job_count = len(data.get('jobs', []))
            if job_count > 0:
                return {'platform': 'ashbyhq', 'slug': slug, 'job_count': job_count}
    except Exception:
        pass
    return None


def _probe_greenhouse(slug: str, timeout: int = 5) -> Optional[dict]:
    """Check if company exists on Greenhouse with jobs."""
    try:
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
        response = requests.get(url, timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            job_count = len(data.get('jobs', []))
            if job_count > 0:
                return {'platform': 'greenhouse', 'slug': slug, 'job_count': job_count}
    except Exception:
        pass
    return None


def _probe_lever(slug: str, timeout: int = 5) -> Optional[dict]:
    """Check if company exists on Lever with jobs."""
    try:
        url = f"https://api.lever.co/v0/postings/{slug}"
        response = requests.get(url, params={'mode': 'json'}, timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            job_count = len(data) if isinstance(data, list) else 0
            if job_count > 0:
                return {'platform': 'lever', 'slug': slug, 'job_count': job_count}
    except Exception:
        pass
    return None


def probe_ats_apis(
    company_name: str,
    aliases: list[str] | None = None,
    timeout: int = 5
) -> tuple[str, str | None, str | None]:
    """
    Probe ATS APIs to discover which platform a company uses.

    Tries Ashby, Greenhouse, and Lever with various slug variations.
    Only returns a match if the company has active job postings.

    Args:
        company_name: Company name to search for
        aliases: Alternative names to try
        timeout: Request timeout in seconds

    Returns:
        Tuple of (platform, slug, ats_url) where:
        - platform: 'ashbyhq', 'greenhouse', 'lever', or 'unknown'
        - slug: The working slug if found, else None
        - ats_url: Full ATS board URL if found, else None
    """
    slugs = generate_slugs(company_name, aliases)

    for slug in slugs:
        # Try Ashby first (most common for startups)
        result = _probe_ashby(slug, timeout)
        if result:
            return 'ashbyhq', slug, f"https://jobs.ashbyhq.com/{slug}"

        # Try Greenhouse
        result = _probe_greenhouse(slug, timeout)
        if result:
            return 'greenhouse', slug, f"https://boards.greenhouse.io/{slug}"

        # Try Lever
        result = _probe_lever(slug, timeout)
        if result:
            return 'lever', slug, f"https://jobs.lever.co/{slug}"

        # Small delay between attempts to be nice to APIs
        time.sleep(0.05)

    return 'unknown', None, None


def extract_slug_from_ats_url(ats_platform: str, ats_url: str) -> str | None:
    """
    Extract slug from an ATS URL.

    Args:
        ats_platform: 'ashbyhq', 'greenhouse', or 'lever'
        ats_url: Full ATS board URL

    Returns:
        The slug portion of the URL, or None if not extractable
    """
    if not ats_url:
        return None

    if ats_platform == 'ashbyhq':
        return ats_url.replace('https://jobs.ashbyhq.com/', '').split('/')[0]
    elif ats_platform == 'lever':
        return ats_url.replace('https://jobs.lever.co/', '').split('/')[0]
    elif ats_platform == 'greenhouse':
        return ats_url.replace('https://boards.greenhouse.io/', '').split('/')[0]

    return None


# =============================================================================
# Parallel ATS Probing for Bulk Aggregators
# =============================================================================

@dataclass
class ProbeResult:
    """Result of probing a company for ATS."""
    company_name: str
    ats_platform: str
    slug: str | None
    ats_url: str | None


def probe_companies_parallel(
    company_names: list[str],
    max_workers: int = 30,
    progress_every: int = 100,
    limit: int | None = None,
) -> tuple[list[ProbeResult], dict[str, int]]:
    """
    Probe ATS APIs for multiple companies in parallel.

    Args:
        company_names: List of company names to probe
        max_workers: Number of parallel threads (default 30)
        progress_every: Log progress every N companies (default 100)
        limit: Only probe first N companies (None = all)

    Returns:
        Tuple of (results, ats_counts) where:
        - results: List of ProbeResult for each company
        - ats_counts: Dict of platform -> count
    """
    to_probe = company_names[:limit] if limit else company_names
    total = len(to_probe)

    if total == 0:
        return [], {}

    results = []
    ats_counts = {}
    completed = 0

    print(f"\nProbing ATS APIs for {total:,} companies ({max_workers} parallel workers)...")
    print("  (checking Ashby, Lever, Greenhouse)", flush=True)

    def probe_one(company_name: str) -> ProbeResult:
        """Probe a single company."""
        platform, slug, ats_url = probe_ats_apis(company_name)
        return ProbeResult(
            company_name=company_name,
            ats_platform=platform,
            slug=slug,
            ats_url=ats_url,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_company = {
            executor.submit(probe_one, name): name
            for name in to_probe
        }

        # Process results as they complete
        for future in as_completed(future_to_company):
            result = future.result()
            results.append(result)

            # Track counts
            ats_counts[result.ats_platform] = ats_counts.get(result.ats_platform, 0) + 1
            completed += 1

            # Progress logging
            if completed % progress_every == 0:
                found = sum(v for k, v in ats_counts.items() if k != 'unknown')
                print(f"  [{completed:,}/{total:,}] {found} ATS found so far...", flush=True)
            elif result.ats_platform != 'unknown':
                print(f"  [{completed:,}/{total:,}] ✓ {result.company_name} → {result.ats_platform}", flush=True)

    # Final summary
    found = sum(v for k, v in ats_counts.items() if k != 'unknown')
    print(f"\n  ✓ Probing complete: {found} ATS found out of {total:,} companies", flush=True)

    return results, ats_counts
