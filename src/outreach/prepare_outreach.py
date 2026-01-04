#!/usr/bin/env python3
"""Prepare a complete outreach package for a random company.

This script:
1. Picks a random company with priority contacts
2. Picks a random priority contact (founder/CEO/CTO)
3. Generates a personalized message
4. Generates multiple email address candidates
5. Shows everything for review (does NOT send)

Run this when you're ready to prepare outreach for one company.
"""

import json
import os
import sys
import random
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.db import get_connection, is_remote


def _placeholder():
    """Return SQL placeholder for current database."""
    return "%s" if is_remote() else "?"


PROFILE_PATH = Path(__file__).parent.parent.parent / "profile.json"

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def load_profile():
    """Load user profile information."""
    with open(PROFILE_PATH, 'r') as f:
        return json.load(f)


def is_valid_contact_name(name):
    """
    Filter out invalid/unusual contact names that are likely parsing errors.

    Returns False for:
    - Names with too many words (likely scraped garbage)
    - Names with special characters or numbers
    - Names that look like company names or titles
    """
    if not name:
        return False

    # Too short or too long
    words = name.split()
    if len(words) < 2 or len(words) > 4:
        return False

    # Contains numbers or special URL-encoded characters
    if any(char.isdigit() for char in name):
        return False
    if '%' in name or '@' in name:
        return False

    # Common false positive patterns
    bad_patterns = [
        'inc', 'llc', 'corp', 'the', 'company', 'group',
        'usa', 'sur', 'intermove', 'unknown'
    ]
    name_lower = name.lower()
    if any(pattern in name_lower for pattern in bad_patterns):
        return False

    return True


def get_random_company_with_contact():
    """
    Get a random company that has priority contacts with valid names.

    Returns company info + a random priority contact.
    Filters out contacts with invalid/unusual names.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # Get all priority contacts, ordered by title priority and confidence
        # Title priority: recruiter/hiring > hiring manager > CTO > CEO
        cursor.execute("""
            SELECT c.id as company_id, c.name as company_name, c.website,
                   co.id as contact_id, co.name as contact_name, co.title, co.linkedin_url,
                   co.match_confidence
            FROM companies c
            JOIN contacts co ON c.id = co.company_id
            WHERE co.is_priority = 1
            ORDER BY
                CASE
                    WHEN LOWER(co.title) LIKE '%recruit%' OR LOWER(co.title) LIKE '%talent%' OR LOWER(co.title) LIKE '%hiring%' THEN 0
                    WHEN LOWER(co.title) LIKE '%hiring manager%' OR LOWER(co.title) LIKE '%engineering manager%' OR LOWER(co.title) LIKE '%eng manager%' THEN 1
                    WHEN LOWER(co.title) LIKE '%cto%' OR LOWER(co.title) LIKE '%chief technology%' OR LOWER(co.title) LIKE '%vp engineer%' OR LOWER(co.title) LIKE '%vp of engineer%' THEN 2
                    WHEN LOWER(co.title) LIKE '%ceo%' OR LOWER(co.title) LIKE '%chief executive%' OR LOWER(co.title) LIKE '%founder%' THEN 3
                    ELSE 4
                END,
                CASE co.match_confidence WHEN 'high' THEN 0 ELSE 1 END,
                RANDOM()
        """)

        rows = cursor.fetchall()

    if not rows:
        return None, None

    # Filter for valid contact names
    valid_contacts = [
        dict(row) for row in rows
        if is_valid_contact_name(row['contact_name'])
    ]

    if not valid_contacts:
        return None, None

    # Pick random from valid contacts (already sorted by confidence)
    selected = random.choice(valid_contacts[:20])  # Pick from top 20

    company = {
        'id': selected['company_id'],
        'name': selected['company_name'],
        'website': selected['website']
    }
    contact = {
        'id': selected['contact_id'],
        'name': selected['contact_name'],
        'title': selected['title'],
        'linkedin_url': selected['linkedin_url']
    }

    return company, contact


def get_company_context(company_id):
    """
    Get context about a company from job postings.

    Returns dict with:
    - job_titles: list of relevant job titles
    - match_reason: why the job is relevant
    - job_description: full description of the primary job (for personalization)
    - summary: brief text summary
    """
    p = _placeholder()
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(f"""
            SELECT j.job_title, j.job_description, t.match_reason
            FROM jobs j
            LEFT JOIN target_jobs t ON j.id = t.job_id
            WHERE j.company_id = {p} AND t.status = 1
            LIMIT 3
        """, (company_id,))

        jobs = [dict(row) for row in cursor.fetchall()]

    if not jobs:
        return {
            'job_titles': [],
            'match_reason': None,
            'job_description': None,
            'summary': "Hiring for engineering roles"
        }

    job_titles = [j['job_title'] for j in jobs]
    match_reason = jobs[0].get('match_reason')
    job_description = jobs[0].get('job_description')

    # Truncate job description to first 1500 chars (enough for context)
    if job_description and len(job_description) > 1500:
        job_description = job_description[:1500] + "..."

    summary = f"Currently hiring: {', '.join(job_titles)}"
    if match_reason:
        summary += f". {match_reason}"

    return {
        'job_titles': job_titles,
        'match_reason': match_reason,
        'job_description': job_description,
        'summary': summary
    }


def get_stored_person_context(contact_id):
    """Get stored person context from database."""
    p = _placeholder()
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            f"SELECT person_context, context_source FROM contacts WHERE id = {p}",
            (contact_id,)
        )
        row = cursor.fetchone()

    if row:
        person_context = row['person_context'] if is_remote() else row[0]
        context_source = row['context_source'] if is_remote() else row[1]
        if person_context:
            return {
                'context': person_context,
                'source': context_source,
                'confidence': 'high'  # Stored = already validated
            }
    return None


def store_person_context(contact_id, context, source):
    """Store person context in database."""
    p = _placeholder()
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(f"""
            UPDATE contacts
            SET person_context = {p}, context_source = {p}
            WHERE id = {p}
        """, (context, source, contact_id))

        conn.commit()


def fetch_linkedin_context(linkedin_url):
    """
    Fetch LinkedIn profile page and extract context about the person.

    Returns a summary of their headline/about if found.
    """
    import requests
    import re

    if not linkedin_url:
        return None

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(linkedin_url, headers=headers, timeout=10)

        if response.status_code != 200:
            return None

        html = response.text

        # Look for headline in meta description or og:description
        # LinkedIn pages have: <meta name="description" content="...headline and summary...">
        desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if not desc_match:
            desc_match = re.search(r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)

        if desc_match:
            description = desc_match.group(1)
            # Clean up common LinkedIn boilerplate
            description = re.sub(r'View .+?\'s profile on LinkedIn', '', description)
            description = re.sub(r'the world\'s largest professional community\.?', '', description)
            description = description.strip(' .,·')
            if len(description) > 30:  # Only return if meaningful
                return description[:300]

        return None

    except Exception:
        return None


def search_person_context(name, company_name, linkedin_url=None, contact_id=None):
    """
    Search for context about the person we're emailing.

    Strategy:
    1. Check if context is already stored in database
    2. Try fetching their LinkedIn profile (no API cost)
    3. If no LinkedIn context, search Google (1 API call)

    Args:
        name: Person's full name
        company_name: Company they work at
        linkedin_url: Their LinkedIn URL
        contact_id: Database ID to check/store context

    Returns:
        Dict with 'context' (str), 'confidence' (high/medium/none), 'source' (str)
    """
    # Check if we already have stored context
    if contact_id:
        stored = get_stored_person_context(contact_id)
        if stored:
            return stored

    # Try LinkedIn first (no API cost)
    if linkedin_url:
        linkedin_context = fetch_linkedin_context(linkedin_url)
        if linkedin_context:
            result = {
                'context': linkedin_context,
                'confidence': 'high',
                'source': 'linkedin.com'
            }
            # Store for future use
            if contact_id:
                store_person_context(contact_id, result['context'], result['source'])
            return result

    import requests

    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
    GOOGLE_CSE_ID = os.environ.get("GOOGLE_CSE_ID")

    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        return {'context': None, 'confidence': 'none'}

    # Search for person + company
    query = f'"{name}" "{company_name}"'

    try:
        params = {
            'key': GOOGLE_API_KEY,
            'cx': GOOGLE_CSE_ID,
            'q': query,
            'num': 5
        }

        response = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params=params,
            timeout=10
        )

        if response.status_code != 200:
            return {'context': None, 'confidence': 'none'}

        data = response.json()
        items = data.get('items', [])

        if not items:
            return {'context': None, 'confidence': 'none'}

        # Look for useful context in results
        context_snippets = []
        confidence = 'none'

        for item in items:
            url = item.get('link', '')
            snippet = item.get('snippet', '')

            # Skip LinkedIn (we already have that)
            if 'linkedin.com' in url:
                # But use it to validate we have the right person
                if linkedin_url and name.split()[0].lower() in url.lower():
                    confidence = 'high'
                continue

            # Look for interesting sources
            interesting_sources = [
                'twitter.com', 'x.com',  # Social
                'github.com',  # Technical
                'medium.com', 'substack.com', 'blog',  # Writing
                'youtube.com',  # Talks
                'techcrunch.com', 'forbes.com', 'bloomberg.com',  # Press
                'crunchbase.com',  # Company info
            ]

            is_interesting = any(src in url.lower() for src in interesting_sources)

            # Check if snippet mentions both name and company
            snippet_lower = snippet.lower()
            name_parts = name.lower().split()
            has_name = any(part in snippet_lower for part in name_parts[:2])
            has_company = company_name.lower() in snippet_lower

            if has_name and (has_company or is_interesting):
                # Extract source domain
                try:
                    source = url.split('/')[2].replace('www.', '')
                except:
                    source = url[:30]

                context_snippets.append({
                    'source': source,
                    'snippet': snippet[:200],
                    'url': url
                })
                if has_company:
                    confidence = 'high'
                elif confidence == 'none':
                    confidence = 'medium'

        if not context_snippets:
            return {'context': None, 'confidence': 'none'}

        # Return the best context
        best = context_snippets[0]
        result = {
            'context': best['snippet'],
            'confidence': confidence,
            'source': best['source'],
            'url': best['url']
        }

        # Store in database for future use
        if contact_id and result['context']:
            store_person_context(contact_id, result['context'], result['source'])

        return result

    except Exception as e:
        print(f"    ✗ Person search error: {e}")
        return {'context': None, 'confidence': 'none'}


def generate_email_candidates(name, domain, company_name=None):
    """
    Generate multiple email address candidates based on common patterns.

    Args:
        name: Full name (e.g., "John Smith")
        domain: Company domain (e.g., "openai.com")
        company_name: Company name to use if domain not available

    Returns:
        List of email candidates with pattern descriptions
    """
    if not domain:
        # Use company name to construct domain if available
        if company_name:
            # Clean company name and make it lowercase
            clean_name = company_name.lower().replace(' ', '').replace(',', '').replace('.', '')
            domain = f"{clean_name}.com"
        else:
            domain = "company.com"
    else:
        # Remove https:// and trailing slashes
        domain = domain.replace('https://', '').replace('http://', '').strip('/')

    # Parse name
    name_parts = name.lower().split()

    # Handle edge cases
    if len(name_parts) < 2:
        # Single name or incomplete name
        first = name_parts[0] if name_parts else "firstname"
        last = "lastname"
    else:
        first = name_parts[0]
        last = name_parts[-1]

    # Remove common suffixes and artifacts
    first = first.replace(',', '').replace('.', '')
    last = last.replace(',', '').replace('.', '')

    # Filter out common artifacts from LinkedIn parsing
    artifacts = ['md', 'pe', 'phd', 'jr', 'sr', 'ii', 'iii', 'iv']
    if last.lower() in artifacts:
        last = name_parts[-2] if len(name_parts) > 2 else last

    candidates = [
        {
            'email': f"{first}@{domain}",
            'pattern': 'first@domain',
            'confidence': 'medium'
        },
        {
            'email': f"{first}.{last}@{domain}",
            'pattern': 'first.last@domain',
            'confidence': 'high'
        },
        {
            'email': f"{first[0]}{last}@{domain}",
            'pattern': 'flast@domain',
            'confidence': 'medium'
        },
        {
            'email': f"{first}{last}@{domain}",
            'pattern': 'firstlast@domain',
            'confidence': 'low'
        },
        {
            'email': f"{first}.{last[0]}@{domain}",
            'pattern': 'first.l@domain',
            'confidence': 'low'
        }
    ]

    return candidates


def generate_message(profile, company_name, company_context, company_website, contact_name, contact_title, person_context=None):
    """Generate personalized outreach message using Claude API."""

    # Build person context section if available
    # Skip obvious/redundant context (e.g., "recruiter with recruiting skills")
    person_section = ""
    if person_context and person_context.get('context'):
        person_section = f"""
ABOUT THE RECIPIENT (use ONLY if interesting/non-obvious):
{person_context['context']}
(Source: {person_context.get('source', 'web')})
NOTE: Only reference this if it's genuinely interesting. Skip if it's obvious/generic
(e.g., don't mention a recruiter "has recruiting experience" or a CTO "leads technology").
"""

    # Parse company context dict
    job_titles = company_context.get('job_titles', [])
    match_reason = company_context.get('match_reason', '')
    job_description = company_context.get('job_description', '')
    context_summary = company_context.get('summary', '')

    # Build company section with job description
    company_section = f"""Company: {company_name}
Website: {company_website or 'Not available'}
Currently hiring for: {', '.join(job_titles) if job_titles else 'engineering roles'}
Why this is a good fit: {match_reason or 'Relevant engineering role'}"""

    if job_description:
        company_section += f"""

JOB DESCRIPTION (use to tailor your message):
{job_description}"""

    prompt = f"""Generate a concise, personalized LinkedIn/email outreach message for a new grad software engineer reaching out to a startup decision maker.

CANDIDATE INFO:
Name: {profile['name']}
Background: {profile['background']}
Education: Computer Science and Chemistry dual major (important - always mention both!)
Interests: {profile['interests']}
Looking for: {profile['looking_for']}

RECIPIENT INFO:
Contact: {contact_name}
Title: {contact_title}
{company_section}
{person_section}
AUTOMATION PROJECT:
{profile['project_description']}
GitHub: {profile['github_repo']}

MESSAGE REQUIREMENTS:
1. START with a hook like: "I'm Justin, a CS/Chem double major graduating from Michigan in May. You're getting this because my AI pipeline powered by Claude Code decided you were worth emailing about [job title] at [company]. Here's why I might be worth a reply:" - adapt this naturally but keep the core elements (CS/Chem, graduating May, AI pipeline powered by Claude Code found them, job title, company name)
2. Keep it conversational and genuine (not salesy or robotic)
3. Include the GitHub link to the automation project naturally
4. Express specific interest in their company based on the job description and your skills (1-2 sentences). Be specific if possible but don't lie.
5. If person context is provided AND it's interesting/non-obvious, reference it (shows research). Skip generic/obvious context.
6. Keep total length to 5-7 sentences max
7. Use bullet points for key info to make it quick to skim
8. DO NOT include subject line, greeting, or signature
9. Write in first person
10. Be authentic - this is a real person reaching out to another real person

Generate only the message body:"""

    try:
        response = client.messages.create(
            model="claude-opus-4-5-20251101",
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        return response.content[0].text.strip()

    except Exception as e:
        return f"Error generating message: {e}"


def main():
    """Prepare complete outreach package for one random company."""
    print("=" * 80)
    print("OUTREACH PACKAGE PREPARATION")
    print("=" * 80)

    # Load profile
    profile = load_profile()
    print(f"\n✓ Loaded profile for: {profile['name']}")

    # Get random company + contact
    print("\nSelecting random company with priority contact...")
    company, contact = get_random_company_with_contact()

    if not company or not contact:
        print("\n✗ No companies with priority contacts found.")
        return

    print(f"\n✓ Selected company: {company['name']}")
    print(f"✓ Selected contact: {contact['name']} ({contact['title']})")

    # Get company context
    context = get_company_context(company['id'])

    # Search for person context (checks DB first, then 1 API call if needed)
    print("\nSearching for context about this person...")
    person_context = search_person_context(
        contact['name'],
        company['name'],
        contact.get('linkedin_url'),
        contact_id=contact['id']
    )

    if person_context.get('context'):
        stored = " (from database)" if person_context.get('confidence') == 'high' else " (newly found)"
        print(f"✓ Found context from {person_context.get('source', 'web')}{stored}")
    else:
        print("✗ No additional context found (will use company context only)")

    # Generate message
    print("\nGenerating personalized message with Claude API...")
    message = generate_message(
        profile,
        company['name'],
        context,
        company['website'],
        contact['name'],
        contact['title'],
        person_context
    )

    # Generate email candidates
    print("\nGenerating email address candidates...")
    email_candidates = generate_email_candidates(contact['name'], company['website'], company['name'])

    # Display complete outreach package
    print("\n" + "=" * 80)
    print("OUTREACH PACKAGE")
    print("=" * 80)

    print(f"\n📍 COMPANY: {company['name']}")
    print(f"🌐 Website: {company['website'] or 'Not found'}")
    print(f"\n👤 CONTACT: {contact['name']}")
    print(f"💼 Title: {contact['title']}")
    print(f"🔗 LinkedIn: {contact['linkedin_url']}")

    print(f"\n📧 EMAIL CANDIDATES (sorted by confidence):")
    print("-" * 80)
    # Sort by confidence
    confidence_order = {'high': 0, 'medium': 1, 'low': 2}
    sorted_emails = sorted(email_candidates, key=lambda x: confidence_order[x['confidence']])

    for i, candidate in enumerate(sorted_emails, 1):
        confidence_emoji = "✅" if candidate['confidence'] == 'high' else "⚠️" if candidate['confidence'] == 'medium' else "❓"
        print(f"{i}. {candidate['email']:<40} {confidence_emoji} {candidate['confidence'].upper():<6} ({candidate['pattern']})")

    print(f"\n✉️  MESSAGE:")
    print("-" * 80)
    print(message)
    print("-" * 80)

    print(f"\n📊 CONTEXT USED:")
    print(f"   Company: {context.get('summary', 'N/A')}")
    if context.get('job_description'):
        print(f"   Job desc: {context['job_description'][:100]}...")
    if person_context.get('context'):
        print(f"   Person: {person_context['context'][:150]}...")
        print(f"   Source: {person_context.get('source', 'N/A')}")

    print("\n" + "=" * 80)
    print("READY TO SEND?")
    print("=" * 80)
    print("\nThis package is ready for manual outreach. To send:")
    print("1. Choose the most likely email from candidates above")
    print("2. Copy the message")
    print("3. Add appropriate greeting (Hi [name],) and signature")
    print("4. Send via LinkedIn or email")
    print("\n⚠️  Note: This script does NOT send anything automatically")
    print("    Manual review and sending ensures quality and personal touch")


if __name__ == "__main__":
    main()
