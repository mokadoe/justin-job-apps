#!/usr/bin/env python3
"""Generate personalized outreach messages for companies with contacts.

This script:
1. Loads your profile information
2. Gets companies with priority contacts
3. Researches each company (from job descriptions)
4. Uses Claude API to generate personalized messages
5. Stores messages in database for review before sending
"""

import sqlite3
import json
import os
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
from tabulate import tabulate

load_dotenv()

DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT
            c.id,
            c.name,
            c.website,
            COUNT(DISTINCT co.id) as contact_count,
            COUNT(DISTINCT CASE WHEN co.is_priority = 1 THEN co.id END) as priority_count
        FROM companies c
        JOIN contacts co ON c.id = co.company_id
        WHERE co.is_priority = 1
        GROUP BY c.id
        ORDER BY priority_count DESC, contact_count DESC
    """)

    companies = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return companies


def get_company_context(company_id):
    """
    Get context about a company from job postings.

    Returns a summary of what the company does based on their job titles and descriptions.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get job titles for this company (especially the pending ones)
    cursor.execute("""
        SELECT j.job_title, j.job_description, t.match_reason
        FROM jobs j
        LEFT JOIN target_jobs t ON j.id = t.job_id
        WHERE j.company_id = ?
        AND (t.status = 1 OR t.status IS NULL)
        LIMIT 5
    """, (company_id,))

    jobs = [dict(row) for row in cursor.fetchall()]
    conn.close()

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
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO messages (company_id, message_text, company_research)
        VALUES (?, ?, ?)
    """, (company_id, message_text, company_research))

    conn.commit()
    conn.close()


def get_existing_messages():
    """Get count of existing messages."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM messages")
    count = cursor.fetchone()[0]

    conn.close()
    return count


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
        print("Run contact discovery first: python3 src/discovery/discover_contacts.py")
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
