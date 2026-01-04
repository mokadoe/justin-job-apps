#!/usr/bin/env python3
"""Discover and store key contacts at companies with pending jobs.

This script:
1. Gets companies with pending jobs
2. Uses Google Custom Search API to find LinkedIn profiles
3. Extracts names and titles of key decision makers:
   - Founders, Co-founders
   - CEOs
   - CTOs, VP Engineering
4. Stores contacts in database for later outreach

Setup required:
1. Create Custom Search Engine at: https://programmablesearchengine.google.com/
   - Search entire web
   - Copy the Search Engine ID
2. Get API key from: https://console.cloud.google.com/apis/credentials
   - Enable Custom Search API
3. Add to .env file:
   GOOGLE_API_KEY=your_key_here
   GOOGLE_CSE_ID=your_search_engine_id_here
"""

import sqlite3
import requests
import re
import os
from pathlib import Path
from urllib.parse import urljoin, urlparse
from time import sleep
from tabulate import tabulate
from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"

# Google Custom Search API
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.environ.get("GOOGLE_CSE_ID")
GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"

# Common URL patterns for contact/team pages
PAGE_PATTERNS = [
    '/about',
    '/about-us',
    '/team',
    '/contact',
    '/contact-us',
    '/people',
    '/leadership',
    '/careers/team',
    '/company',
    '/company/team',
    '/company/about',
]

# Import company size configuration from constants
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.constants import (
    SIZE_SMALL, SIZE_MEDIUM, SIZE_LARGE,
    USE_LINKEDIN_FOR_COMPANY_SIZE,
    CONTACT_TARGETING, PRIORITY_ROLE_KEYWORDS,
    get_company_size_from_employees, get_company_size_from_jobs
)


def search_linkedin_company_url(company_name):
    """
    Search Google for a company's LinkedIn page URL.

    Returns the LinkedIn company page URL if found, None otherwise.
    """
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        return None

    query = f'site:linkedin.com/company "{company_name}"'

    try:
        params = {
            'key': GOOGLE_API_KEY,
            'cx': GOOGLE_CSE_ID,
            'q': query,
            'num': 3
        }

        response = requests.get(GOOGLE_SEARCH_URL, params=params, timeout=10)

        if response.status_code != 200:
            print(f"    ✗ Google API error: {response.status_code}")
            return None

        data = response.json()
        items = data.get('items', [])

        # Return first LinkedIn company page URL
        for item in items:
            url = item.get('link', '')
            if 'linkedin.com/company/' in url:
                return url

        return None

    except Exception as e:
        print(f"    ✗ Company page search error: {e}")
        return None


def fetch_linkedin_employee_count(linkedin_url):
    """
    Fetch LinkedIn company page and extract employee count from structured data.

    LinkedIn pages embed JSON-LD structured data with numberOfEmployees field:
    "numberOfEmployees": {"value": 6975, "@type": "QuantitativeValue"}

    Returns integer employee count, or None if not found.
    """
    if not linkedin_url:
        return None

    try:
        # Fetch the LinkedIn page
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(linkedin_url, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"    ✗ LinkedIn page fetch error: {response.status_code}")
            return None

        html = response.text

        # Look for numberOfEmployees in JSON-LD structured data
        # Pattern: "numberOfEmployees":{"value":6975,...}
        match = re.search(r'"numberOfEmployees"\s*:\s*\{\s*"value"\s*:\s*(\d+)', html)
        if match:
            return int(match.group(1))

        # Fallback: look for employee count patterns in page text
        # Pattern: "1,234 employees" or "201-500 employees"
        exact_match = re.search(r'([\d,]+)\s+employees', html, re.IGNORECASE)
        if exact_match:
            count_str = exact_match.group(1).replace(',', '')
            return int(count_str)

        # Range pattern: "201-500 employees"
        range_match = re.search(r'(\d+)\s*[-–]\s*(\d+)\s+employees', html, re.IGNORECASE)
        if range_match:
            low = int(range_match.group(1))
            high = int(range_match.group(2))
            return (low + high) // 2

        return None

    except Exception as e:
        print(f"    ✗ LinkedIn fetch error: {e}")
        return None


def search_linkedin_company_page(company_name):
    """
    Search Google for a company's LinkedIn page URL.
    DEPRECATED: Use search_linkedin_company_url instead.
    Kept for backwards compatibility.
    """
    return search_linkedin_company_url(company_name)


def extract_employee_count(search_result):
    """
    Extract employee count from LinkedIn search result snippet.
    DEPRECATED: Use fetch_linkedin_employee_count instead.

    LinkedIn snippets often contain patterns like:
    - "1,234 employees"
    - "501-1000 employees"
    - "11-50 employees"

    Returns integer count (midpoint for ranges), or None if not found.
    """
    if not search_result:
        return None

    snippet = search_result.get('snippet', '')
    title = search_result.get('title', '')
    text = f"{title} {snippet}"

    # Pattern 1: Exact count "1,234 employees" or "1234 employees"
    exact_match = re.search(r'([\d,]+)\s+employees', text, re.IGNORECASE)
    if exact_match:
        count_str = exact_match.group(1).replace(',', '')
        try:
            return int(count_str)
        except ValueError:
            pass

    # Pattern 2: Range "501-1000 employees" or "11-50 employees"
    range_match = re.search(r'(\d+)\s*[-–]\s*(\d+)\s+employees', text, re.IGNORECASE)
    if range_match:
        try:
            low = int(range_match.group(1))
            high = int(range_match.group(2))
            return (low + high) // 2  # Return midpoint
        except ValueError:
            pass

    # Pattern 3: "10K+ employees" or "1K employees"
    k_match = re.search(r'([\d.]+)\s*K\+?\s+employees', text, re.IGNORECASE)
    if k_match:
        try:
            return int(float(k_match.group(1)) * 1000)
        except ValueError:
            pass

    return None


def get_employee_count(company_id, company_name, auto_lookup=True):
    """
    Get employee count for a company.

    1. Check if already stored in database
    2. If not and auto_lookup=True, search LinkedIn via Google
    3. Store result for future use

    Args:
        company_id: Database ID of company
        company_name: Name of company for searching
        auto_lookup: If False, skip Google lookup (for manual entry mode)

    Returns:
        Tuple of (employee_count, source) where source is 'linkedin', 'manual', 'job_proxy', or None
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if we already have it
    cursor.execute(
        "SELECT employee_count, employee_count_source FROM companies WHERE id = ?",
        (company_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if row and row[0] is not None:
        return (row[0], row[1])

    # If auto_lookup disabled, return None
    if not auto_lookup:
        return (None, None)

    # Step 1: Search Google for LinkedIn company page URL
    print(f"    Searching for LinkedIn company page...")
    linkedin_url = search_linkedin_company_url(company_name)

    if not linkedin_url:
        print(f"    ✗ No LinkedIn company page found")
        return (None, None)

    print(f"    ✓ Found: {linkedin_url}")

    # Step 2: Fetch LinkedIn page and extract employee count from structured data
    print(f"    Fetching employee count from page...")
    employee_count = fetch_linkedin_employee_count(linkedin_url)

    if employee_count:
        store_employee_count(company_id, employee_count, 'linkedin')
        print(f"    ✓ Found: {employee_count} employees")
        return (employee_count, 'linkedin')
    else:
        print(f"    ✗ Could not extract employee count from page")

    return (None, None)


def store_employee_count(company_id, count, source):
    """Store employee count in database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE companies
        SET employee_count = ?, employee_count_source = ?
        WHERE id = ?
    """, (count, source, company_id))

    conn.commit()
    conn.close()


def get_company_size(company_id, company_name, use_linkedin=None):
    """
    Determine company size category (small/medium/large).

    Two workflows (configured in constants.py via USE_LINKEDIN_FOR_COMPANY_SIZE):

    Workflow 1 - LinkedIn Method (use_linkedin=True):
        - Search Google for LinkedIn company page
        - Extract employee count from search results
        - Use EMPLOYEE_COUNT_THRESHOLDS to categorize
        - Falls back to job count if LinkedIn lookup fails

    Workflow 2 - Job Count Proxy (use_linkedin=False):
        - Count job postings for the company in database
        - Use JOB_COUNT_THRESHOLDS to categorize
        - No API calls, instant

    Args:
        company_id: Database ID of the company
        company_name: Name of the company (for LinkedIn search)
        use_linkedin: Override for USE_LINKEDIN_FOR_COMPANY_SIZE config.
                     If None, uses the value from constants.py

    Returns:
        Tuple of (size_category: str, count: int, source: str)
        - size_category: SIZE_SMALL, SIZE_MEDIUM, or SIZE_LARGE
        - count: employee count or job count depending on method
        - source: 'linkedin', 'manual', or 'job_count'
    """
    # Use config default if not explicitly specified
    if use_linkedin is None:
        use_linkedin = USE_LINKEDIN_FOR_COMPANY_SIZE

    if use_linkedin:
        # WORKFLOW 1: LinkedIn employee count method
        # First check if we already have employee count in DB
        count, source = get_employee_count(company_id, company_name, auto_lookup=True)

        if count is not None:
            size_category = get_company_size_from_employees(count)
            return (size_category, count, source)

        # LinkedIn lookup failed, fall back to job count
        print(f"    → LinkedIn lookup failed, falling back to job count")

    # WORKFLOW 2: Job count proxy method
    job_count = get_job_count_for_company(company_id)
    size_category = get_company_size_from_jobs(job_count)

    return (size_category, job_count, 'job_count')


def get_job_count_for_company(company_id):
    """Get the number of jobs for a company."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) FROM jobs WHERE company_id = ?",
        (company_id,)
    )
    job_count = cursor.fetchone()[0]
    conn.close()

    return job_count


def get_companies_with_pending_jobs(limit=None):
    """Get companies that have pending jobs."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT DISTINCT c.id, c.name, c.ats_url
        FROM companies c
        JOIN jobs j ON c.id = j.company_id
        JOIN target_jobs t ON j.id = t.job_id
        WHERE t.status = 1
        ORDER BY (
            SELECT COUNT(*)
            FROM target_jobs t2
            JOIN jobs j2 ON t2.job_id = j2.id
            WHERE j2.company_id = c.id AND t2.status = 1
        ) DESC
    """

    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query)
    companies = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return companies


def extract_domain_from_ats_url(ats_url):
    """
    Extract likely company domain from ATS URL.

    Example: https://jobs.ashbyhq.com/openai -> openai.com
    """
    if not ats_url:
        return None

    parsed = urlparse(ats_url)
    path_parts = parsed.path.strip('/').split('/')

    if path_parts and path_parts[0]:
        company_slug = path_parts[0]
        # Try common TLDs
        return f"{company_slug}.com"

    return None


def try_find_company_website(company_name, ats_url):
    """
    Try to find company website.

    Strategy:
    1. Extract from ATS URL (e.g., jobs.ashbyhq.com/openai -> openai.com)
    2. Try common pattern: {company_name}.com
    """
    # Try extracting from ATS URL first
    domain = extract_domain_from_ats_url(ats_url)
    if domain:
        try:
            response = requests.head(f"https://{domain}", timeout=5, allow_redirects=True)
            if response.status_code < 400:
                return f"https://{domain}"
        except:
            pass

    # Try simple pattern: company-name.com
    simple_domain = company_name.lower().replace(' ', '').replace('-', '') + '.com'
    try:
        response = requests.head(f"https://{simple_domain}", timeout=5, allow_redirects=True)
        if response.status_code < 400:
            return f"https://{simple_domain}"
    except:
        pass

    return None


def discover_pages(base_url):
    """
    Discover about/team/contact pages for a company.

    Returns dict of {page_type: url} for pages that exist.
    """
    discovered = {}

    for pattern in PAGE_PATTERNS:
        url = urljoin(base_url, pattern)

        try:
            response = requests.head(url, timeout=5, allow_redirects=True)
            if response.status_code == 200:
                # Determine page type from pattern
                if 'about' in pattern:
                    page_type = 'about'
                elif 'team' in pattern or 'people' in pattern or 'leadership' in pattern:
                    page_type = 'team'
                elif 'contact' in pattern:
                    page_type = 'contact'
                else:
                    page_type = 'other'

                discovered[page_type] = url
        except:
            pass

        # Be respectful with requests
        sleep(0.2)

    return discovered


def search_linkedin_profiles(company_name, title_keywords=None):
    """
    Search Google for LinkedIn profiles of people at a company.

    Args:
        company_name: Name of the company
        title_keywords: Optional list of title keywords (e.g., ['founder', 'CTO'])

    Returns:
        List of search results with LinkedIn URLs
    """
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        return []

    # Build search query
    if title_keywords:
        title_query = " OR ".join(title_keywords)
        query = f'site:linkedin.com/in "{company_name}" ({title_query})'
    else:
        query = f'site:linkedin.com/in "{company_name}"'

    try:
        params = {
            'key': GOOGLE_API_KEY,
            'cx': GOOGLE_CSE_ID,
            'q': query,
            'num': 10  # Get top 10 results
        }

        response = requests.get(GOOGLE_SEARCH_URL, params=params, timeout=10)

        if response.status_code != 200:
            print(f"    ✗ Google API error: {response.status_code}")
            return []

        data = response.json()
        items = data.get('items', [])

        return items

    except Exception as e:
        print(f"    ✗ Search error: {e}")
        return []


def extract_name_from_linkedin_url(url):
    """
    Extract person's name from LinkedIn profile URL.

    Example: https://www.linkedin.com/in/john-smith-123/ → John Smith
    """
    # Pattern: linkedin.com/in/{name-slug}/
    match = re.search(r'linkedin\.com/in/([^/]+)', url)
    if not match:
        return None

    slug = match.group(1)

    # Remove trailing numbers/IDs (e.g., "john-smith-123" → "john-smith")
    # Keep only the name part before numbers
    name_part = re.sub(r'-\d+.*$', '', slug)

    # Convert slug to proper name (john-smith → John Smith)
    name_parts = name_part.split('-')
    name = ' '.join(word.capitalize() for word in name_parts if word)

    return name


def extract_title_from_snippet(snippet, title_text=""):
    """
    Extract job title from Google search snippet and title.

    LinkedIn snippets have various formats:
    - "John Smith - CEO at Company | LinkedIn"
    - "John Smith - Co-Founder & CTO | LinkedIn"
    - "View John Smith's profile... CEO · Company · Location"
    - "Chief Technology Officer at Company - LinkedIn"

    Args:
        snippet: Google search result snippet
        title_text: Google search result title (often contains cleaner title info)

    Returns:
        Extracted title or "Unknown" if not found
    """
    # Combine title and snippet for more context
    full_text = f"{title_text} {snippet}"

    # Clean up LinkedIn noise
    full_text = re.sub(r'\s*\|\s*LinkedIn', '', full_text)
    full_text = re.sub(r'\s*-\s*LinkedIn', '', full_text)
    full_text = full_text.replace('View profile', '').replace("'s profile", '')

    # Pattern 1: "Name - Title at Company" or "Name - Title | ..."
    # The dash before title is common in LinkedIn titles
    dash_pattern = re.search(
        r'-\s*([^-|]+?(?:founder|ceo|cto|chief|vp|director|head of|manager|lead|recruiter|recruiting|hiring|engineer)[^-|]*)',
        full_text,
        re.IGNORECASE
    )
    if dash_pattern:
        title = dash_pattern.group(1).strip()
        # Clean up trailing "at Company" or "· Company"
        title = re.sub(r'\s+(?:at|@|·|•)\s+.*$', '', title, flags=re.IGNORECASE)
        if title and len(title) < 80:  # Sanity check
            return title.strip()

    # Pattern 2: "Title at Company" (standalone)
    at_pattern = re.search(
        r'((?:co-?)?(?:founder|ceo|cto|chief\s+\w+\s+officer|vp\s+\w+|director\s+of\s+\w+|head\s+of\s+\w+|'
        r'engineering\s+manager|technical\s+recruiter|recruiter|recruiting\s+\w+)[^·•|]*?)'
        r'\s+(?:at|@)\s+',
        full_text,
        re.IGNORECASE
    )
    if at_pattern:
        title = at_pattern.group(1).strip()
        if title and len(title) < 80:
            return title.strip()

    # Pattern 3: Look for title keywords with context
    # e.g., "Co-Founder & CEO", "VP of Engineering", "Head of Recruiting"
    keyword_patterns = [
        r'((?:co-?)?founder(?:\s*[&,]\s*(?:ceo|cto))?)',
        r'(ceo|chief\s+executive\s+officer)',
        r'(cto|chief\s+technology\s+officer)',
        r'(chief\s+\w+\s+officer)',
        r'(vp\s+(?:of\s+)?(?:engineering|product|technology|people))',
        r'(director\s+of\s+engineering)',
        r'(head\s+of\s+(?:engineering|product|recruiting|talent|hiring))',
        r'(engineering\s+manager)',
        r'((?:technical\s+)?recruiter)',
        r'(recruiting\s+(?:manager|lead|coordinator))',
        r'(talent\s+acquisition(?:\s+\w+)?)',
        r'(hiring\s+(?:manager|lead))',
    ]

    for pattern in keyword_patterns:
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return "Unknown"


def validate_company_match(snippet, title_text, company_name, person_name=None):
    """
    Validate that a search result actually belongs to the target company.

    For small companies with common names (e.g., "Finch"), we need to verify
    the person actually works at that company, not a different company with
    a similar name (e.g., "Finch Therapeutics" vs "Finch").

    Args:
        snippet: Google search result snippet
        title_text: Google search result title
        company_name: Target company name to validate
        person_name: Name of the person (to exclude from matching)

    Returns:
        Tuple of (is_match: bool, confidence: str)
        confidence: 'high' (exact match), 'medium' (likely match), 'low' (possible match)
    """
    full_text = f"{title_text} {snippet}".lower()
    company_lower = company_name.lower()

    # Normalize company name (remove common suffixes for matching)
    company_normalized = re.sub(r'\s*(inc\.?|llc|corp\.?|co\.?|ltd\.?)\s*$', '', company_lower, flags=re.IGNORECASE)

    # If the company name appears in the person's name, this is likely a false positive
    # e.g., searching for "Anon" company but finding "Auston Anon" (person's last name)
    if person_name:
        person_name_lower = person_name.lower()
        if company_normalized in person_name_lower:
            # Company name is in the person's name - need stronger evidence
            # Must have explicit "at Company" pattern to be valid
            strict_at_pattern = rf'\bat\s+{re.escape(company_normalized)}\b'
            if re.search(strict_at_pattern, full_text, re.IGNORECASE):
                return (True, 'medium')
            return (False, 'low')

    # Check for exact company name match with word boundaries
    # Pattern: "at Company" or "@ Company" or "· Company" or "• Company"
    exact_patterns = [
        rf'\bat\s+{re.escape(company_normalized)}\b',
        rf'@\s*{re.escape(company_normalized)}\b',
        rf'[·•]\s*{re.escape(company_normalized)}\b',
    ]

    for pattern in exact_patterns:
        if re.search(pattern, full_text, re.IGNORECASE):
            return (True, 'high')

    # Check for company name appearing as a word (not part of another company)
    # Avoid "Finch" matching "Finch Therapeutics" by checking word boundaries
    if len(company_normalized) >= 4:  # Only for reasonably long names
        word_boundary = rf'\b{re.escape(company_normalized)}\b'
        if re.search(word_boundary, full_text, re.IGNORECASE):
            # Check it's not part of a longer company name
            # e.g., "Finch Therapeutics" should not match "Finch"
            extended_match = re.search(
                rf'\b{re.escape(company_normalized)}\s+(?:therapeutics|health|bio|medical|capital|partners|group|holdings|technologies|solutions|labs|ai|software|systems|energy|cloud)',
                full_text,
                re.IGNORECASE
            )
            if not extended_match:
                return (True, 'medium')

    # For very short names (< 4 chars), require more context
    if len(company_normalized) < 4:
        # Must have "at X" or similar direct association
        strict_patterns = [
            rf'\bat\s+{re.escape(company_normalized)}(?:\s|$|[,.])',
            rf'working\s+(?:at|for)\s+{re.escape(company_normalized)}',
        ]
        for pattern in strict_patterns:
            if re.search(pattern, full_text, re.IGNORECASE):
                return (True, 'medium')
        return (False, 'low')

    # If company name appears but without clear context, low confidence
    if company_normalized in full_text:
        return (True, 'low')

    return (False, 'low')


def is_priority_role(title):
    """
    Determine if this is a priority contact.

    Uses PRIORITY_ROLE_KEYWORDS from constants.py.
    Priority roles include decision makers, engineering leadership, and recruiters.
    """
    title_lower = title.lower()
    return any(keyword in title_lower for keyword in PRIORITY_ROLE_KEYWORDS)


def discover_people_via_google(company_name, company_id=None, use_linkedin_for_size=None):
    """
    Discover key people at a company using Google search for LinkedIn profiles.

    Targeting based on company size (configured in constants.py):
    - Small: Target founders, CTOs
    - Medium: Target engineering leadership
    - Large: Target recruiters

    Args:
        company_name: Name of the company
        company_id: Database ID (needed for size lookup)
        use_linkedin_for_size: If True, use LinkedIn for size. If False, use job count.
                              If None, uses USE_LINKEDIN_FOR_COMPANY_SIZE from constants.

    Returns list of {name, title, linkedin_url, is_priority}.
    """
    people = []

    # Determine company size and targeting strategy
    if company_id:
        size_category, count, size_source = get_company_size(
            company_id, company_name, use_linkedin=use_linkedin_for_size
        )
        if size_source == 'job_count':
            print(f"  Company size: {count} jobs ({size_source}) → {size_category}")
        else:
            print(f"  Company size: {count} employees ({size_source}) → {size_category}")
    else:
        # Default to small company behavior if no company_id
        size_category = SIZE_SMALL
        print("  Company size: unknown → defaulting to small company targeting")

    # Get targeting strategy from constants
    role_searches = CONTACT_TARGETING.get(size_category, CONTACT_TARGETING[SIZE_SMALL])

    # Print what we're searching for
    target_desc = {
        SIZE_SMALL: "decision makers (founders/CTOs)",
        SIZE_MEDIUM: "engineering leadership",
        SIZE_LARGE: "recruiters"
    }
    print(f"  Searching for {target_desc.get(size_category, 'contacts')} on LinkedIn...")

    for roles in role_searches:
        results = search_linkedin_profiles(company_name, roles)

        for item in results:
            url = item.get('link', '')
            if 'linkedin.com/in/' not in url:
                continue

            name = extract_name_from_linkedin_url(url)
            if not name or len(name.split()) < 2:
                continue

            snippet = item.get('snippet', '')
            title_text = item.get('title', '')

            # Validate this person actually works at the target company
            # (avoids false positives like "Finch" matching "Finch Therapeutics"
            #  or "Anon" matching people with "Anon" in their name)
            is_match, confidence = validate_company_match(snippet, title_text, company_name, person_name=name)

            if not is_match or confidence == 'low':
                # Skip low-confidence matches to reduce false positives
                continue

            # Extract title using improved parsing
            title = extract_title_from_snippet(snippet, title_text)

            # Avoid duplicates
            if not any(p['name'] == name for p in people):
                people.append({
                    'name': name,
                    'title': title,
                    'linkedin_url': url,
                    'is_priority': is_priority_role(title),
                    'match_confidence': confidence
                })

        # Be respectful with API rate limits
        sleep(0.5)

    # Sort by priority (decision makers first)
    people.sort(key=lambda p: (not p['is_priority'], p['name']))

    return people


def extract_people_from_page(url):
    """
    Extract people names and titles from a page.

    Looks for patterns like:
    - "John Smith, CEO"
    - "Jane Doe - CTO"
    - "Co-founder: Alice Johnson"

    Returns list of dicts with {name, title}.
    """
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return []

        text = response.text
        people = []

        # Target titles we care about (founders, engineering leadership)
        target_titles = [
            'founder', 'co-founder', 'ceo', 'cto', 'chief technology officer',
            'head of engineering', 'vp engineering', 'engineering manager',
            'technical lead', 'lead engineer', 'director of engineering'
        ]

        # Pattern: Look for title words near potential names
        # Common patterns:
        # - "John Smith, CEO"
        # - "CEO: John Smith"
        # - "John Smith - Founder"
        # - "Co-founder & CTO - Jane Doe"

        # Split into lines to process more easily
        lines = text.split('\n')

        for line in lines:
            line_lower = line.lower()

            # Check if line contains a target title
            found_title = None
            for title in target_titles:
                if title in line_lower:
                    found_title = title
                    break

            if not found_title:
                continue

            # Look for name pattern (capitalized words)
            # Names are typically: "FirstName LastName" or "FirstName MiddleName LastName"
            name_pattern = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b')
            matches = name_pattern.findall(line)

            for match in matches:
                # Filter out common false positives
                skip_words = ['The', 'Our', 'About', 'Team', 'Join', 'Contact', 'Privacy', 'Terms',
                             'Policy', 'More', 'View', 'Click', 'Learn', 'Read', 'See', 'Get',
                             'Company', 'Inc', 'Corp', 'Ltd', 'New', 'York', 'San', 'Francisco']

                if match.split()[0] not in skip_words and len(match.split()) >= 2:
                    people.append({
                        'name': match,
                        'title': found_title.title()
                    })

        # Remove duplicates (same name)
        seen_names = set()
        unique_people = []
        for person in people:
            if person['name'] not in seen_names:
                seen_names.add(person['name'])
                unique_people.append(person)

        return unique_people[:10]  # Limit to top 10 to avoid noise

    except Exception as e:
        return []


def store_website(company_id, website):
    """Update company record with discovered website."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE companies
        SET website = ?
        WHERE id = ?
    """, (website, company_id))

    conn.commit()
    conn.close()


def store_contact(company_id, name, title, linkedin_url, is_priority, match_confidence='medium'):
    """
    Store contact in database.

    Uses INSERT OR IGNORE to avoid duplicates (based on company_id + name).

    Args:
        company_id: Database ID of the company
        name: Contact's full name
        title: Job title
        linkedin_url: LinkedIn profile URL
        is_priority: True if this is a priority contact (decision maker, etc.)
        match_confidence: 'high' or 'medium' - how confident we are they work at this company

    Returns:
        True if inserted, False if already existed
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO contacts (company_id, name, title, linkedin_url, is_priority, match_confidence)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (company_id, name, title, linkedin_url, is_priority, match_confidence))

    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()

    return rows_affected > 0  # True if inserted, False if already existed


def discover_contacts_for_companies(companies, use_linkedin_for_size=None):
    """
    Discover and store contact information for companies.

    Stores results in database:
    - company.website
    - company.employee_count (if using LinkedIn method)
    - contacts table (name, title, linkedin_url, is_priority)

    Args:
        companies: List of company dicts with id, name, ats_url
        use_linkedin_for_size: If True, use LinkedIn for company size (uses API quota).
                              If False, use job count proxy (no API calls).
                              If None, uses USE_LINKEDIN_FOR_COMPANY_SIZE from constants.

    Returns list of dicts with discovery results.
    """
    results = []

    for i, company in enumerate(companies, 1):
        print(f"\n[{i}/{len(companies)}] {company['name']}")

        result = {
            'company_id': company['id'],
            'company_name': company['name'],
            'website': None,
            'size_category': None,
            'size_count': None,
            'size_source': None,
            'people': [],
            'new_contacts': 0
        }

        # Find website
        print("  Finding website...")
        website = try_find_company_website(company['name'], company['ats_url'])

        if website:
            result['website'] = website
            store_website(company['id'], website)
            print(f"    ✓ Found: {website}")
        else:
            print("    ✗ Could not find website")

        # Discover people via Google search for LinkedIn profiles
        # This also determines company size using configured method
        people = discover_people_via_google(
            company['name'],
            company_id=company['id'],
            use_linkedin_for_size=use_linkedin_for_size
        )

        # Get the size info that was determined
        size_category, count, source = get_company_size(
            company['id'], company['name'], use_linkedin=False  # Don't re-lookup
        )
        result['size_category'] = size_category
        result['size_count'] = count
        result['size_source'] = source
        result['people'] = people

        # Store contacts in database
        if people:
            print(f"  ✓ Found {len(people)} contacts:")
            for person in people:
                is_new = store_contact(
                    company['id'],
                    person['name'],
                    person['title'],
                    person['linkedin_url'],
                    person['is_priority'],
                    person.get('match_confidence', 'medium')
                )

                if is_new:
                    result['new_contacts'] += 1

                # Show priority contacts with marker
                priority_marker = " ⭐" if person['is_priority'] else ""
                status = "new" if is_new else "exists"
                print(f"    - {person['name']} ({person['title']}){priority_marker} [{status}]")

            print(f"  → Stored {result['new_contacts']} new contacts in database")
        else:
            print("    ✗ No people found")

        results.append(result)

        # Be respectful with requests
        sleep(1)

    return results


def main():
    """Discover contacts for top companies with pending jobs.

    Usage:
        python discover_contacts.py                  # Use config default from constants.py
        python discover_contacts.py --use-linkedin   # Force LinkedIn method for company size
        python discover_contacts.py --use-job-count  # Force job count method (saves API quota)
        python discover_contacts.py --limit 5        # Process only 5 companies
    """
    import argparse

    parser = argparse.ArgumentParser(description='Discover contacts at companies with pending jobs')
    size_group = parser.add_mutually_exclusive_group()
    size_group.add_argument('--use-linkedin', action='store_true',
                           help='Use LinkedIn for company size (overrides config)')
    size_group.add_argument('--use-job-count', action='store_true',
                           help='Use job count proxy for company size (overrides config, saves API quota)')
    parser.add_argument('--limit', type=int, default=10,
                       help='Max companies to process (default: 10)')
    args = parser.parse_args()

    # Determine which method to use: CLI override > config default
    if args.use_linkedin:
        use_linkedin = True
        method_source = "CLI override"
    elif args.use_job_count:
        use_linkedin = False
        method_source = "CLI override"
    else:
        use_linkedin = USE_LINKEDIN_FOR_COMPANY_SIZE
        method_source = "constants.py"

    print("=" * 80)
    print("CONTACT DISCOVERY VIA GOOGLE + LINKEDIN")
    print("=" * 80)

    if use_linkedin:
        print(f"\n📊 Size method: LINKEDIN (employee count) [{method_source}]")
        print("   Thresholds: small <50, medium 50-500, large 500+")
    else:
        print(f"\n📊 Size method: JOB COUNT (proxy) [{method_source}]")
        print("   Thresholds: small <5 jobs, medium 5-20, large 20+")

    # Check for API credentials
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        print("\n⚠ Missing Google API credentials!")
        print("\nSetup required:")
        print("1. Create Custom Search Engine: https://programmablesearchengine.google.com/")
        print("2. Get API key: https://console.cloud.google.com/apis/credentials")
        print("3. Add to .env file:")
        print("   GOOGLE_API_KEY=your_key_here")
        print("   GOOGLE_CSE_ID=your_search_engine_id_here")
        return

    # Get companies with pending jobs
    print("\nGetting companies with pending jobs...")
    companies = get_companies_with_pending_jobs(limit=args.limit)

    if not companies:
        print("No companies with pending jobs found.")
        return

    print(f"Found {len(companies)} companies to process")

    # Estimate API usage
    # Per company: 2 contact searches + 1 size lookup (if LinkedIn) = 2-3 searches
    searches_per_company = 3 if use_linkedin else 2
    estimated_searches = len(companies) * searches_per_company
    print(f"\n⚠ Free tier limit: 100 searches/day")
    print(f"This will use ~{estimated_searches} searches ({searches_per_company} per company)")
    if use_linkedin:
        print("  (Use --use-job-count to skip LinkedIn size lookup and save quota)\n")

    # Discover contacts
    print("\n" + "=" * 80)
    print("DISCOVERING CONTACT INFORMATION")
    print("=" * 80)

    results = discover_contacts_for_companies(companies, use_linkedin_for_size=use_linkedin)

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    websites_found = sum(1 for r in results if r['website'])
    people_found = sum(1 for r in results if r['people'])
    total_people = sum(len(r['people']) for r in results)
    total_new_contacts = sum(r['new_contacts'] for r in results)

    print(f"\nCompanies processed: {len(results)}")
    print(f"  Websites found: {websites_found}/{len(results)} ({websites_found/len(results)*100:.0f}%)")
    print(f"  Companies with contacts: {people_found}/{len(results)} ({people_found/len(results)*100:.0f}%)")
    print(f"  Total contacts discovered: {total_people}")
    print(f"  New contacts stored: {total_new_contacts}")

    if total_people > 0:
        print(f"  Average contacts per company: {total_people/people_found:.1f}")

    # Show detailed results
    if results:
        print("\n" + "=" * 80)
        print("STORED CONTACTS BY COMPANY")
        print("=" * 80)

        headers = ["Company", "Size", "Count", "Source", "Target", "Contacts"]
        rows = []
        for r in results:
            size_category = r.get('size_category', '?')
            size_count = r.get('size_count')
            size_source = r.get('size_source', '')

            # Format size info
            count_str = str(size_count) if size_count else '?'
            source_str = size_source[:8] if size_source else ''

            # Target based on size category
            target_map = {
                SIZE_SMALL: "CTO",
                SIZE_MEDIUM: "Eng Lead",
                SIZE_LARGE: "Recruiter"
            }
            target_str = target_map.get(size_category, "?")

            contacts_str = f"{r['new_contacts']} new / {len(r['people'])} total"
            rows.append([r['company_name'][:20], size_category[:6], count_str, source_str, target_str, contacts_str])

        print(tabulate(rows, headers=headers, tablefmt="grid"))

        # Show priority contacts
        priority_contacts = []
        for r in results:
            for person in r['people']:
                if person.get('is_priority'):
                    priority_contacts.append({
                        'company': r['company_name'],
                        'name': person['name'],
                        'title': person['title'],
                        'linkedin': person.get('linkedin_url', '')
                    })

        if priority_contacts:
            print("\n" + "=" * 80)
            print("PRIORITY CONTACTS ⭐")
            print("=" * 80)

            headers = ["Company", "Name", "Title", "LinkedIn"]
            rows = []
            for contact in priority_contacts:
                linkedin_short = contact['linkedin'].replace('https://www.linkedin.com/in/', 'in/')[:30] if contact['linkedin'] else 'N/A'
                rows.append([
                    contact['company'][:20],
                    contact['name'],
                    contact['title'][:30],
                    linkedin_short
                ])

            print(tabulate(rows, headers=headers, tablefmt="grid"))
            print(f"\n✓ {len(priority_contacts)} priority contacts stored in database")

    print("\n" + "=" * 80)
    print("DATABASE UPDATED")
    print("=" * 80)
    print("\nContacts stored in 'contacts' table")
    print("View contacts: SELECT * FROM contacts WHERE is_priority = 1;")
    print("Next step: Generate personalized outreach messages")


if __name__ == "__main__":
    main()
