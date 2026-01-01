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

import sqlite3
import json
import os
import random
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"
PROFILE_PATH = Path(__file__).parent.parent.parent / "profile.json"

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def load_profile():
    """Load user profile information."""
    with open(PROFILE_PATH, 'r') as f:
        return json.load(f)


def get_random_company_with_contact():
    """
    Get a random company that has priority contacts.

    Returns company info + a random priority contact.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all companies with priority contacts
    cursor.execute("""
        SELECT DISTINCT c.id, c.name, c.website
        FROM companies c
        JOIN contacts co ON c.id = co.company_id
        WHERE co.is_priority = 1
    """)

    companies = [dict(row) for row in cursor.fetchall()]

    if not companies:
        conn.close()
        return None, None

    # Pick random company
    company = random.choice(companies)

    # Get a random priority contact from this company
    cursor.execute("""
        SELECT id, name, title, linkedin_url
        FROM contacts
        WHERE company_id = ? AND is_priority = 1
        ORDER BY RANDOM()
        LIMIT 1
    """, (company['id'],))

    contact = dict(cursor.fetchone())
    conn.close()

    return company, contact


def get_company_context(company_id):
    """Get context about a company from job postings."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT j.job_title, t.match_reason
        FROM jobs j
        LEFT JOIN target_jobs t ON j.id = t.job_id
        WHERE j.company_id = ? AND t.status = 1
        LIMIT 3
    """, (company_id,))

    jobs = [dict(row) for row in cursor.fetchall()]
    conn.close()

    if not jobs:
        return "Hiring for engineering roles"

    job_titles = [j['job_title'] for j in jobs]
    context = f"Currently hiring: {', '.join(job_titles)}"

    if jobs[0].get('match_reason'):
        context += f". {jobs[0]['match_reason']}"

    return context


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


def generate_message(profile, company_name, company_context, company_website, contact_name, contact_title):
    """Generate personalized outreach message using Claude API."""
    prompt = f"""Generate a concise, personalized LinkedIn/email outreach message for a new grad software engineer reaching out to a startup decision maker.

CANDIDATE INFO:
Name: {profile['name']}
Background: {profile['background']}
Interests: {profile['interests']}
Looking for: {profile['looking_for']}

RECIPIENT INFO:
Contact: {contact_name}
Title: {contact_title}
Company: {company_name}
Website: {company_website or 'Not available'}
Context: {company_context}

AUTOMATION PROJECT:
{profile['project_description']}
GitHub: {profile['github_repo']}

MESSAGE REQUIREMENTS:
1. Keep it conversational and genuine (not salesy or robotic)
2. Brief intro about yourself (1-2 sentences)
3. Express specific interest in their company based on context (1-2 sentences)
4. Mention you built this outreach automation as a side project and include GitHub link (1 sentence)
5. Keep total length to 5-7 sentences max
6. DO NOT include subject line, greeting, or signature
7. Write in first person
8. Be authentic - this is a real person reaching out to another real person

Generate only the message body:"""

    try:
        response = client.messages.create(
            model="claude-3-opus-20240229",
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
        print("Run contact discovery first: python3 src/discovery/discover_contacts.py")
        return

    print(f"\n✓ Selected company: {company['name']}")
    print(f"✓ Selected contact: {contact['name']} ({contact['title']})")

    # Get company context
    context = get_company_context(company['id'])

    # Generate message
    print("\nGenerating personalized message with Claude API...")
    message = generate_message(
        profile,
        company['name'],
        context,
        company['website'],
        contact['name'],
        contact['title']
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
    print(f"   {context}")

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
