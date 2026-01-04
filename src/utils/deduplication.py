#!/usr/bin/env python3
"""
Handle duplicates across discovery sources.

This module provides utilities to:
1. Detect duplicate companies from multiple sources
2. Merge company records with priority logic
3. Detect duplicate jobs (same URL, similar titles)
4. Detect duplicate contacts (same person at same company)

Deduplication Strategy:
- Companies: Match by normalized name, merge metadata from multiple sources
- Jobs: Match by job_url (unique constraint), skip if already exists
- Contacts: Match by (company_id, normalized_name), keep first found
"""

import sqlite3
import re
from pathlib import Path
from typing import Tuple, Optional, List, Dict
from difflib import SequenceMatcher

DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"


def normalize_company_name(name: str) -> str:
    """
    Normalize company name for duplicate detection.

    Rules:
    - Lowercase
    - Remove common suffixes (Inc, Inc., LLC, Corp, etc.)
    - Remove special characters except alphanumeric and spaces
    - Strip whitespace

    Examples:
        "OpenAI, Inc." → "openai"
        "Stripe Inc" → "stripe"
        "1Password" → "1password"
    """
    # Lowercase
    normalized = name.lower()

    # Remove common company suffixes
    suffixes = [
        r'\s*,?\s*inc\.?$',
        r'\s*,?\s*llc\.?$',
        r'\s*,?\s*corp\.?$',
        r'\s*,?\s*corporation$',
        r'\s*,?\s*ltd\.?$',
        r'\s*,?\s*limited$',
        r'\s*,?\s*co\.?$',
        r'\s*,?\s*company$',
    ]

    for suffix_pattern in suffixes:
        normalized = re.sub(suffix_pattern, '', normalized)

    # Remove special characters except alphanumeric and spaces
    normalized = re.sub(r'[^a-z0-9\s]', '', normalized)

    # Collapse multiple spaces to single space
    normalized = re.sub(r'\s+', ' ', normalized)

    # Strip
    normalized = normalized.strip()

    return normalized


def normalize_contact_name(name: str) -> str:
    """
    Normalize contact name for duplicate detection.

    Rules:
    - Lowercase
    - Remove titles (Dr., Mr., Ms., etc.)
    - Remove middle initials
    - Strip whitespace

    Examples:
        "Dr. John A. Smith" → "john smith"
        "Jane Doe, PhD" → "jane doe"
    """
    # Lowercase
    normalized = name.lower()

    # Remove titles
    titles = [r'\bdr\.?\s*', r'\bmr\.?\s*', r'\bms\.?\s*', r'\bmrs\.?\s*', r'\bprof\.?\s*']
    for title in titles:
        normalized = re.sub(title, '', normalized)

    # Remove suffixes like "PhD", "Jr.", "Sr."
    suffixes = [r',?\s*phd\.?$', r',?\s*jr\.?$', r',?\s*sr\.?$', r',?\s*iii?$']
    for suffix in suffixes:
        normalized = re.sub(suffix, '', normalized)

    # Remove middle initials (single letter followed by period)
    normalized = re.sub(r'\s+[a-z]\.\s+', ' ', normalized)

    # Collapse multiple spaces
    normalized = re.sub(r'\s+', ' ', normalized)

    # Strip
    normalized = normalized.strip()

    return normalized


def find_duplicate_company(name: str, ats_platform: str = None) -> Optional[int]:
    """
    Find existing company by normalized name.

    Args:
        name: Company name to search for
        ats_platform: Optional ATS platform to narrow search

    Returns:
        company_id if found, None otherwise
    """
    normalized = normalize_company_name(name)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if ats_platform:
        # Prefer exact match on same ATS platform
        cursor.execute("""
            SELECT id FROM companies
            WHERE ats_platform = ? AND name = ?
        """, (ats_platform, name))

        exact_match = cursor.fetchone()
        if exact_match:
            conn.close()
            return exact_match[0]

    # Check all companies for normalized match
    cursor.execute("SELECT id, name FROM companies")
    companies = cursor.fetchall()

    conn.close()

    for company_id, company_name in companies:
        if normalize_company_name(company_name) == normalized:
            return company_id

    return None


def fuzzy_match_company(name: str, threshold: float = 0.85) -> List[Tuple[int, str, float]]:
    """
    Find similar company names using fuzzy matching.

    Useful for detecting duplicates with typos or slight variations.

    Args:
        name: Company name to search for
        threshold: Similarity threshold (0.0-1.0), default 0.85

    Returns:
        List of (company_id, company_name, similarity_score) for matches above threshold
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id, name FROM companies")
    companies = cursor.fetchall()

    conn.close()

    normalized_input = normalize_company_name(name)
    matches = []

    for company_id, company_name in companies:
        normalized_existing = normalize_company_name(company_name)

        # Calculate similarity
        similarity = SequenceMatcher(None, normalized_input, normalized_existing).ratio()

        if similarity >= threshold:
            matches.append((company_id, company_name, similarity))

    # Sort by similarity (highest first)
    matches.sort(key=lambda x: x[2], reverse=True)

    return matches


def merge_company_metadata(existing_id: int, new_data: Dict) -> bool:
    """
    Merge metadata from a newly discovered company into existing record.

    Strategy:
    - Keep existing name (first discovered)
    - Add new ATS platform if different
    - Update website if existing is NULL
    - Update last_scraped to most recent

    Args:
        existing_id: ID of existing company
        new_data: Dict with new company data (name, ats_platform, website, ats_url)

    Returns:
        True if updated, False if no changes needed
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get existing data
    cursor.execute("SELECT ats_platform, website FROM companies WHERE id = ?", (existing_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return False

    existing_ats, existing_website = row
    updated = False

    # Update website if NULL
    if not existing_website and new_data.get('website'):
        cursor.execute("UPDATE companies SET website = ? WHERE id = ?",
                      (new_data['website'], existing_id))
        updated = True

    # If different ATS platform, create a mapping (future: support multi-ATS companies)
    # For now, just log it
    if new_data.get('ats_platform') != existing_ats:
        print(f"  ℹ Company {existing_id} found on multiple ATS: {existing_ats} and {new_data['ats_platform']}")

    # Update last_scraped
    cursor.execute("UPDATE companies SET last_scraped = CURRENT_TIMESTAMP WHERE id = ?", (existing_id,))

    conn.commit()
    conn.close()

    return updated


def is_duplicate_job(job_url: str) -> bool:
    """
    Check if job already exists in database.

    Jobs are uniquely identified by job_url (UNIQUE constraint).

    Args:
        job_url: Job URL to check

    Returns:
        True if job already exists
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM jobs WHERE job_url = ?", (job_url,))
    exists = cursor.fetchone() is not None

    conn.close()

    return exists


def is_duplicate_contact(company_id: int, name: str) -> bool:
    """
    Check if contact already exists for this company.

    Contacts are uniquely identified by (company_id, name) UNIQUE constraint.
    Also checks normalized names to catch duplicates like "John Smith" vs "Dr. John Smith".

    Args:
        company_id: Company ID
        name: Contact name

    Returns:
        True if contact already exists
    """
    normalized = normalize_contact_name(name)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check exact match first (UNIQUE constraint)
    cursor.execute("SELECT id FROM contacts WHERE company_id = ? AND name = ?",
                  (company_id, name))
    if cursor.fetchone():
        conn.close()
        return True

    # Check normalized match
    cursor.execute("SELECT name FROM contacts WHERE company_id = ?", (company_id,))
    existing_contacts = cursor.fetchall()

    conn.close()

    for (existing_name,) in existing_contacts:
        if normalize_contact_name(existing_name) == normalized:
            return True

    return False


def get_duplicate_stats() -> Dict:
    """
    Get statistics on potential duplicates in the database.

    Returns:
        Dict with counts of potential duplicates
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    stats = {}

    # Companies with very similar normalized names
    cursor.execute("SELECT name FROM companies")
    company_names = [row[0] for row in cursor.fetchall()]

    normalized_names = {}
    for name in company_names:
        norm = normalize_company_name(name)
        if norm in normalized_names:
            normalized_names[norm].append(name)
        else:
            normalized_names[norm] = [name]

    duplicate_companies = {k: v for k, v in normalized_names.items() if len(v) > 1}
    stats['potential_duplicate_companies'] = len(duplicate_companies)
    stats['duplicate_company_examples'] = list(duplicate_companies.items())[:5]

    # Jobs with same title at same company (potential duplicates if URLs differ)
    cursor.execute("""
        SELECT company_id, job_title, COUNT(*) as count
        FROM jobs
        GROUP BY company_id, job_title
        HAVING count > 1
    """)
    duplicate_job_titles = cursor.fetchall()
    stats['jobs_with_duplicate_titles'] = len(duplicate_job_titles)

    # Contacts with similar names at same company
    cursor.execute("SELECT company_id, name FROM contacts")
    contacts = cursor.fetchall()

    contact_groups = {}
    for company_id, name in contacts:
        norm = f"{company_id}:{normalize_contact_name(name)}"
        if norm in contact_groups:
            contact_groups[norm].append(name)
        else:
            contact_groups[norm] = [name]

    duplicate_contacts = {k: v for k, v in contact_groups.items() if len(v) > 1}
    stats['potential_duplicate_contacts'] = len(duplicate_contacts)

    conn.close()

    return stats


def display_duplicate_report():
    """Display a report of potential duplicates in the database."""
    print("=" * 80)
    print("DEDUPLICATION REPORT")
    print("=" * 80)

    stats = get_duplicate_stats()

    print(f"\nPotential duplicate companies: {stats['potential_duplicate_companies']}")
    if stats['duplicate_company_examples']:
        print("\nExamples:")
        for norm_name, variants in stats['duplicate_company_examples']:
            print(f"  '{norm_name}': {variants}")

    print(f"\nJobs with duplicate titles: {stats['jobs_with_duplicate_titles']}")
    print(f"Potential duplicate contacts: {stats['potential_duplicate_contacts']}")

    print("\n" + "=" * 80)
    print("DEDUPLICATION STRATEGY")
    print("=" * 80)
    print("\nThe system automatically handles duplicates:")
    print("  ✓ Companies: Matched by normalized name, metadata merged")
    print("  ✓ Jobs: UNIQUE constraint on job_url prevents duplicates")
    print("  ✓ Contacts: UNIQUE constraint on (company_id, name) prevents duplicates")
    print("\nNo manual intervention needed!")


if __name__ == "__main__":
    display_duplicate_report()
