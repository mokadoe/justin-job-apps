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


def extract_title_from_snippet(snippet, company_name):
    """
    Extract job title from Google search snippet.

    Example snippet: "John Smith - CEO at OpenAI | LinkedIn"
    """
    # Common patterns in LinkedIn snippets
    # "Name - Title at Company"
    # "Title at Company - Name"

    # Remove "LinkedIn" and other noise
    snippet = snippet.replace(' | LinkedIn', '').replace('LinkedIn', '')

    # Look for title indicators
    title_patterns = [
        r'(?:CEO|CTO|Founder|Co-Founder|Co-founder|Chief|Head of|VP|Director|Lead|Manager)',
    ]

    for pattern in title_patterns:
        match = re.search(pattern, snippet, re.IGNORECASE)
        if match:
            # Try to extract the full title context
            # Usually appears as "- Title at Company" or "Title at Company -"
            title_match = re.search(r'-\s*([^-|]+(?:at|@)\s*' + re.escape(company_name) + r')', snippet, re.IGNORECASE)
            if title_match:
                return title_match.group(1).strip()

            # Fallback: just return the matched title word
            return match.group(0)

    return "Unknown"


def is_priority_role(title):
    """
    Determine if this is a priority contact (decision maker).

    Priority: Founder, CEO, CTO
    Non-priority: Other engineering leadership
    """
    title_lower = title.lower()

    priority_keywords = [
        'founder', 'co-founder', 'ceo', 'chief executive',
        'cto', 'chief technology officer'
    ]

    return any(keyword in title_lower for keyword in priority_keywords)


def discover_people_via_google(company_name):
    """
    Discover key people at a company using Google search for LinkedIn profiles.

    Focus on decision makers: Founders, CEOs, CTOs.
    Returns list of {name, title, linkedin_url, is_priority}.
    """
    people = []

    # Search for priority roles only (decision makers)
    role_searches = [
        ['founder', 'co-founder', 'CEO', 'Chief Executive'],
        ['CTO', 'Chief Technology Officer', 'VP Engineering'],
    ]

    print("  Searching for decision makers on LinkedIn...")

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
            title = extract_title_from_snippet(snippet, company_name)

            # Avoid duplicates
            if not any(p['name'] == name for p in people):
                people.append({
                    'name': name,
                    'title': title,
                    'linkedin_url': url,
                    'is_priority': is_priority_role(title)
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


def store_contact(company_id, name, title, linkedin_url, is_priority):
    """
    Store contact in database.

    Uses INSERT OR IGNORE to avoid duplicates (based on company_id + name).
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO contacts (company_id, name, title, linkedin_url, is_priority)
        VALUES (?, ?, ?, ?, ?)
    """, (company_id, name, title, linkedin_url, is_priority))

    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()

    return rows_affected > 0  # True if inserted, False if already existed


def discover_contacts_for_companies(companies):
    """
    Discover and store contact information for companies.

    Stores results in database:
    - company.website
    - contacts table (name, title, linkedin_url, is_priority)

    Returns list of dicts with discovery results.
    """
    results = []

    for i, company in enumerate(companies, 1):
        print(f"\n[{i}/{len(companies)}] {company['name']}")

        result = {
            'company_id': company['id'],
            'company_name': company['name'],
            'website': None,
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
        people = discover_people_via_google(company['name'])
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
                    person['is_priority']
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
    """Discover contacts for top companies with pending jobs."""
    print("=" * 80)
    print("CONTACT DISCOVERY VIA GOOGLE + LINKEDIN")
    print("=" * 80)

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

    # Get companies with pending jobs (start with top 10)
    print("\nGetting companies with pending jobs...")
    companies = get_companies_with_pending_jobs(limit=10)

    if not companies:
        print("No companies with pending jobs found.")
        return

    print(f"Found {len(companies)} companies to process")
    print(f"\n⚠ Free tier limit: 100 searches/day")
    print(f"This will use ~{len(companies) * 3} searches (3 per company)\n")

    # Discover contacts
    print("\n" + "=" * 80)
    print("DISCOVERING CONTACT INFORMATION")
    print("=" * 80)

    results = discover_contacts_for_companies(companies)

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

        headers = ["Company", "Website", "New Contacts", "Total Contacts"]
        rows = []
        for r in results:
            website_domain = r['website'].replace('https://', '').replace('http://', '') if r['website'] else "Not found"
            new_contacts = str(r['new_contacts'])
            total_contacts = str(len(r['people']))
            rows.append([r['company_name'][:30], website_domain[:30], new_contacts, total_contacts])

        print(tabulate(rows, headers=headers, tablefmt="grid"))

        # Show priority contacts (decision makers)
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
            print("PRIORITY CONTACTS (Decision Makers) ⭐")
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
            print(f"\n✓ {len(priority_contacts)} priority contacts (Founders/CEOs/CTOs) stored in database")

    print("\n" + "=" * 80)
    print("DATABASE UPDATED")
    print("=" * 80)
    print("\nContacts stored in 'contacts' table")
    print("View contacts: SELECT * FROM contacts WHERE is_priority = 1;")
    print("Next step: Generate personalized outreach messages")


if __name__ == "__main__":
    main()
