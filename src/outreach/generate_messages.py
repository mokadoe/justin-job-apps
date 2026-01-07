#!/usr/bin/env python3
"""Generate personalized outreach messages for companies with contacts.

This script:
1. Loads your profile information
2. Gets companies with priority contacts
3. Researches each company (from job descriptions)
4. Uses Claude API to generate personalized messages
5. Stores messages in database for review before sending
"""

import json
import os
import sys
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
from tabulate import tabulate

load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.jobs_db_conn import get_connection, is_remote

# Cost tracking (optional)
try:
    from utils.cost_tracker import track_api_call
except ImportError:
    def track_api_call(*args, **kwargs):
        pass


def _placeholder():
    """Return SQL placeholder for current database."""
    return "%s" if is_remote() else "?"


PROFILE_PATH = Path(__file__).parent.parent.parent / "profile.json"

# Initialize Claude API
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def load_profile():
    """Load user profile information."""
    if not PROFILE_PATH.exists():
        raise FileNotFoundError(f"Profile not found at {PROFILE_PATH}. Please create profile.json with your info.")

    with open(PROFILE_PATH, 'r') as f:
        return json.load(f)


def get_companies_with_contacts():
    """Get companies that have priority contacts."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                c.id,
                c.name,
                c.website,
                COUNT(DISTINCT co.id) as contact_count,
                COUNT(DISTINCT CASE WHEN co.is_priority = 1 THEN co.id END) as priority_count
            FROM companies c
            JOIN contacts co ON c.id = co.company_id
            WHERE co.is_priority = 1
            GROUP BY c.id, c.name, c.website
            ORDER BY priority_count DESC, contact_count DESC
        """)

        rows = cursor.fetchall()
        if is_remote():
            companies = [dict(row) for row in rows]
        else:
            companies = [dict(row) for row in rows]

        return companies


def get_company_context(company_id):
    """
    Get context about a company from job postings.

    Returns a summary of what the company does based on their job titles and descriptions.
    """
    p = _placeholder()
    with get_connection() as conn:
        cursor = conn.cursor()

        # Get job titles for this company (especially the pending ones)
        cursor.execute(f"""
            SELECT j.job_title, j.job_description, t.match_reason
            FROM jobs j
            LEFT JOIN target_jobs t ON j.id = t.job_id
            WHERE j.company_id = {p}
            AND (t.status = 1 OR t.status IS NULL)
            LIMIT 5
        """, (company_id,))

        rows = cursor.fetchall()
        if is_remote():
            jobs = [dict(row) for row in rows]
        else:
            jobs = [dict(row) for row in rows]

    if not jobs:
        return "No job information available."

    # Create context from job titles
    job_titles = [j['job_title'] for j in jobs]
    context = f"Job openings: {', '.join(job_titles[:3])}"

    if jobs[0].get('match_reason'):
        context += f"\n\nRole match: {jobs[0]['match_reason']}"

    return context


def generate_message(profile, company_name, company_context, company_website):
    """
    Generate personalized outreach message using Claude API.

    Message structure:
    1. Brief about yourself
    2. What excites you about the company
    3. How you built this automation (with GitHub link)
    """
    prompt = f"""Generate a concise, personalized LinkedIn/email outreach message for a new grad software engineer.

CANDIDATE INFO:
Name: {profile['name']}
Background: {profile['background']}
Interests: {profile['interests']}
Looking for: {profile['looking_for']}

COMPANY INFO:
Name: {company_name}
Website: {company_website or 'Not available'}
Context: {company_context}

AUTOMATION PROJECT:
Description: {profile['project_description']}
GitHub: {profile['github_repo']}

MESSAGE REQUIREMENTS:
1. Start with a brief (1-2 sentence) intro about yourself
2. Express genuine interest in the company (1-2 sentences) - be specific based on company context
3. Mention that you built this outreach automation and include GitHub link (1 sentence)
4. Keep it conversational and authentic, not salesy
5. Total length: 4-6 sentences max
6. DO NOT include subject line or greeting/signature
7. Write in first person

Generate the message body only:"""

    try:
        response = client.messages.create(
            model="claude-opus-4-5-20251101",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        message = response.content[0].text.strip()
        return message

    except Exception as e:
        print(f"    ✗ Error generating message: {e}")
        return None


def store_message(company_id, message_text, company_research):
    """
    Store generated message in database.

    Uses INSERT OR REPLACE to update if message already exists.
    """
    p = _placeholder()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        cursor = conn.cursor()

        if is_remote():
            cursor.execute(f"""
                INSERT INTO messages (company_id, message_text, company_research, generated_date)
                VALUES ({p}, {p}, {p}, {p})
                ON CONFLICT (company_id) DO UPDATE SET
                    message_text = EXCLUDED.message_text,
                    company_research = EXCLUDED.company_research,
                    generated_date = EXCLUDED.generated_date
            """, (company_id, message_text, company_research, now))
        else:
            cursor.execute(f"""
                INSERT OR REPLACE INTO messages (company_id, message_text, company_research, generated_date)
                VALUES ({p}, {p}, {p}, {p})
            """, (company_id, message_text, company_research, now))

        conn.commit()


def get_existing_messages():
    """Get count of existing messages."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as cnt FROM messages")
        row = cursor.fetchone()
        count = row['cnt'] if is_remote() else row[0]

        return count


def get_message_for_company(company_id):
    """Get existing message for a company, if any."""
    p = _placeholder()
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(f"SELECT message_text FROM messages WHERE company_id = {p}", (company_id,))
        row = cursor.fetchone()

        if row:
            return row['message_text'] if is_remote() else row[0]
        return None


def get_company_by_name(company_name):
    """Get company by name (case-insensitive)."""
    p = _placeholder()
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(f"""
            SELECT id, name, website
            FROM companies
            WHERE LOWER(name) = LOWER({p})
        """, (company_name,))

        row = cursor.fetchone()
        if row:
            return dict(row)
        return None


def generate_for_company(company_name, profile=None, force=False):
    """
    Generate message for a specific company by name.

    Args:
        company_name: Name of the company (case-insensitive)
        profile: User profile dict (loaded if not provided)
        force: If True, regenerate even if message exists

    Returns:
        Dict with results: {company, message, created}
    """
    if profile is None:
        profile = load_profile()

    company = get_company_by_name(company_name)
    if not company:
        print(f"Company not found: {company_name}")
        return None

    print(f"Company: {company['name']}")

    # Check existing
    if not force:
        existing = get_message_for_company(company['id'])
        if existing:
            print("Message already exists (use force=True to regenerate)")
            return {'company': company['name'], 'message': existing, 'created': False}

    # Get context and generate
    context = get_company_context(company['id'])
    print(f"Context: {context[:80]}...")

    print("Generating with Claude API...")
    message = generate_message(profile, company['name'], context, company.get('website'))

    if message:
        store_message(company['id'], message, context)
        print("✓ Message generated and stored")
        return {'company': company['name'], 'message': message, 'created': True}
    else:
        print("✗ Failed to generate message")
        return None


def generate_all(profile=None, limit=None, skip_existing=True):
    """
    Generate messages for all companies with priority contacts.

    Args:
        profile: User profile dict (loaded if not provided)
        limit: Max companies to process (None for all)
        skip_existing: Skip companies that already have messages

    Returns:
        Dict with stats: {generated, skipped, failed}
    """
    if profile is None:
        profile = load_profile()
        print(f"Loaded profile for: {profile['name']}")

    companies = get_companies_with_contacts()

    if not companies:
        print("No companies with priority contacts found.")
        return {'generated': 0, 'skipped': 0, 'failed': 0}

    if limit:
        companies = companies[:limit]

    print(f"Found {len(companies)} companies with priority contacts")
    print("=" * 50)

    stats = {'generated': 0, 'skipped': 0, 'failed': 0}

    for i, company in enumerate(companies, 1):
        print(f"\n[{i}/{len(companies)}] {company['name']}")

        # Check existing
        if skip_existing:
            existing = get_message_for_company(company['id'])
            if existing:
                print("  Skipping - message already exists")
                stats['skipped'] += 1
                continue

        # Generate
        context = get_company_context(company['id'])
        print(f"  Context: {context[:60]}...")

        print("  Generating with Claude API...")
        message = generate_message(profile, company['name'], context, company.get('website'))

        if message:
            store_message(company['id'], message, context)
            print("  ✓ Message generated and stored")
            stats['generated'] += 1
        else:
            print("  ✗ Failed to generate message")
            stats['failed'] += 1

    return stats


def main():
    """Generate personalized messages for all companies with contacts."""
    print("=" * 80)
    print("PERSONALIZED MESSAGE GENERATION")
    print("=" * 80)

    # Load profile
    try:
        profile = load_profile()
        print(f"\n✓ Loaded profile for: {profile['name']}")
    except FileNotFoundError as e:
        print(f"\n✗ {e}")
        print("\nPlease edit profile.json with your information:")
        print("  - background: Brief description of your experience")
        print("  - interests: What you're passionate about")
        print("  - looking_for: What kind of role you want")
        print("  - github_repo: Link to this project's GitHub repo")
        return

    # Check for existing messages
    existing_count = get_existing_messages()
    if existing_count > 0:
        print(f"\n⚠ Found {existing_count} existing messages in database")
        response = input("Regenerate all messages? (yes/no): ")
        if response.lower() != 'yes':
            print("Cancelled. Existing messages preserved.")
            return

    # Get companies with contacts
    companies = get_companies_with_contacts()

    if not companies:
        print("\n✗ No companies with priority contacts found.")
        return

    print(f"\n✓ Found {len(companies)} companies with priority contacts")
    print(f"\nGenerating personalized messages using Claude API...")

    # Generate messages
    print("\n" + "=" * 80)
    print("GENERATING MESSAGES")
    print("=" * 80)

    results = []

    for i, company in enumerate(companies, 1):
        print(f"\n[{i}/{len(companies)}] {company['name']}")

        # Get company context
        context = get_company_context(company['id'])
        print(f"  Context: {context[:100]}...")

        # Generate message
        print("  Generating with Claude API...")
        message = generate_message(
            profile,
            company['name'],
            context,
            company['website']
        )

        if message:
            # Store in database
            store_message(company['id'], message, context)
            print(f"  ✓ Message generated and stored")

            results.append({
                'company': company['name'],
                'priority_contacts': company['priority_count'],
                'message_preview': message[:80] + "..." if len(message) > 80 else message
            })
        else:
            print(f"  ✗ Failed to generate message")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    print(f"\nMessages generated: {len(results)}/{len(companies)}")

    if results:
        print("\n" + "=" * 80)
        print("GENERATED MESSAGES PREVIEW")
        print("=" * 80)

        headers = ["Company", "Priority Contacts", "Message Preview"]
        rows = []
        for r in results:
            rows.append([
                r['company'][:20],
                r['priority_contacts'],
                r['message_preview'][:60]
            ])

        print(tabulate(rows, headers=headers, tablefmt="grid"))

        print("\n" + "=" * 80)
        print("NEXT STEPS")
        print("=" * 80)
        print("\n1. Review messages:")
        print("   SELECT c.name, m.message_text FROM messages m")
        print("   JOIN companies c ON m.company_id = c.id;")
        print("\n2. View a specific message:")
        print(f"   python3 -c \"import sqlite3; conn = sqlite3.connect('data/jobs.db');")
        print(f"   cursor = conn.cursor(); cursor.execute('SELECT message_text FROM messages WHERE company_id = 1');")
        print(f"   print(cursor.fetchone()[0])\"")
        print("\n3. Ready to send? Match messages with contacts:")
        print("   SELECT c.name as company, co.name, co.title, m.message_text")
        print("   FROM messages m")
        print("   JOIN companies c ON m.company_id = c.id")
        print("   JOIN contacts co ON c.id = co.company_id")
        print("   WHERE co.is_priority = 1;")


if __name__ == "__main__":
    main()
