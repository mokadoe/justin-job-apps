#!/usr/bin/env python3
"""
Common utilities for ATS scrapers.
"""

from typing import List


def try_simple_variations(company_name: str) -> List[str]:
    """Generate simple slug variations for ATS platforms."""
    variations = [
        company_name.lower().replace(' ', '-'),
        company_name.lower().replace(' ', ''),
        company_name.lower().replace(' ', '-').replace('&', 'and'),
        company_name.lower().replace(' ', '').replace('&', 'and'),
        company_name.lower().replace(' ', '-').replace('.', ''),
    ]
    # Remove duplicates while preserving order
    seen = set()
    unique = []
    for slug in variations:
        if slug and slug not in seen:
            seen.add(slug)
            unique.append(slug)
    return unique


def extract_slug_from_ats_url(ats_platform: str, ats_url: str) -> str:
    """Extract slug from ATS URL for supported platforms."""
    if ats_platform == 'ashbyhq':
        return ats_url.replace('https://jobs.ashbyhq.com/', '')
    elif ats_platform == 'lever':
        return ats_url.replace('https://jobs.lever.co/', '')
    elif ats_platform == 'greenhouse':
        return ats_url.replace('https://boards.greenhouse.io/', '')
    return None
