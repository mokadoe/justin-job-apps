#!/usr/bin/env python3
"""Generate personalized outreach messages for target jobs.

This script:
1. Loads your profile information
2. Gets pending target jobs
3. For each job, generates messages for each priority contact (or one generic if none)
4. Stores messages in database for review before sending

Messages are unique per (company_id, job_id, contact_id) combination.
contact_id can be NULL if no priority contacts exist for the company.
"""

import json
import os
import sys
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.jobs_db_conn import get_connection, is_remote


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


def get_pending_target_jobs(limit=None):
    """
    Get all pending target jobs.

    Returns jobs with company info, ordered by priority.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        query = """
            SELECT
                j.id as job_id,
                j.job_title,
                j.job_description,
                j.location,
                c.id as company_id,
                c.name as company_name,
                c.website,
                t.match_reason,
                t.priority
            FROM target_jobs t
            JOIN jobs j ON t.job_id = j.id
            JOIN companies c ON j.company_id = c.id
            WHERE t.status = 1
            ORDER BY t.priority ASC, c.name
        """

        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query)
        return [dict(row) for row in cursor.fetchall()]


def get_priority_contacts_for_company(company_id):
    """Get priority contacts for a company."""
    p = _placeholder()
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(f"""
            SELECT id, name, title, linkedin_url
            FROM contacts
            WHERE company_id = {p} AND is_priority = 1
        """, (company_id,))

        return [dict(row) for row in cursor.fetchall()]


def get_job_by_id(job_id):
    """Get job details by ID."""
    p = _placeholder()
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(f"""
            SELECT j.id as job_id, j.job_title, j.job_description, j.location,
                   j.company_id, c.name as company_name, c.website,
                   t.match_reason, t.priority
            FROM jobs j
            JOIN companies c ON j.company_id = c.id
            LEFT JOIN target_jobs t ON j.id = t.job_id
            WHERE j.id = {p}
        """, (job_id,))

        row = cursor.fetchone()
        if row:
            return dict(row)
        return None


def get_existing_message(company_id, job_id, contact_id):
    """Check if a message already exists for this (company, job, contact) combination."""
    p = _placeholder()
    with get_connection() as conn:
        cursor = conn.cursor()

        if contact_id is None:
            cursor.execute(f"""
                SELECT message_text FROM messages
                WHERE company_id = {p} AND job_id = {p} AND contact_id IS NULL
            """, (company_id, job_id))
        else:
            cursor.execute(f"""
                SELECT message_text FROM messages
                WHERE company_id = {p} AND job_id = {p} AND contact_id = {p}
            """, (company_id, job_id, contact_id))

        row = cursor.fetchone()
        if row:
            return row['message_text'] if is_remote() else row[0]
        return None


def store_message(company_id, job_id, contact_id, message_text, context):
    """
    Store generated message in database.

    Uses INSERT OR IGNORE to skip if message already exists.
    contact_id can be None.
    """
    p = _placeholder()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        cursor = conn.cursor()

        if is_remote():
            cursor.execute(f"""
                INSERT INTO messages (company_id, job_id, contact_id, message_text, company_research, generated_date)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p})
                ON CONFLICT (company_id, job_id, contact_id) DO NOTHING
            """, (company_id, job_id, contact_id, message_text, context, now))
        else:
            cursor.execute(f"""
                INSERT OR IGNORE INTO messages (company_id, job_id, contact_id, message_text, company_research, generated_date)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p})
            """, (company_id, job_id, contact_id, message_text, context, now))

        conn.commit()
        return cursor.rowcount > 0


def generate_message(profile, company_name, company_website, job_title, job_description, match_reason, contact_name=None, contact_title=None):
    """
    Generate personalized outreach message using Claude API.

    Message is tailored to the specific job and optionally to a contact.
    """
    # Truncate job description if too long
    job_desc_truncated = job_description[:1000] if job_description else "Not available"

    # Build contact section
    if contact_name and contact_title:
        contact_section = f"""
CONTACT INFO:
Name: {contact_name}
Title: {contact_title}
"""
        contact_instruction = "1. Address the contact by name if appropriate for their role"
    else:
        contact_section = ""
        contact_instruction = "1. Write a general outreach message (no specific contact)"

    prompt = f"""Generate a concise, personalized LinkedIn/email outreach message for a new grad software engineer.

CANDIDATE INFO:
Name: {profile['name']}
Background: {profile['background']}
Interests: {profile['interests']}
Looking for: {profile['looking_for']}

COMPANY INFO:
Name: {company_name}
Website: {company_website or 'Not available'}

JOB INFO:
Title: {job_title}
Description: {job_desc_truncated}
Why it's a match: {match_reason or 'Relevant new grad role'}
{contact_section}
AUTOMATION PROJECT:
Description: {profile['project_description']}
GitHub: {profile['github_repo']}

MESSAGE REQUIREMENTS:
{contact_instruction}
2. Start with a brief (1-2 sentence) intro about yourself
3. Express genuine interest in the specific role and company (1-2 sentences)
4. Mention that you built this outreach automation and include GitHub link (1 sentence)
5. Keep it conversational and authentic, not salesy
6. Total length: 4-6 sentences max
7. DO NOT include subject line or greeting/signature
8. Write in first person

Generate the message body only:"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
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


def generate_for_job(job_id, profile=None):
    """
    Generate messages for a specific job.

    If priority contacts exist, generates one message per contact.
    If no priority contacts, generates one generic message (contact_id = NULL).

    Args:
        job_id: ID of the job
        profile: User profile dict (loaded if not provided)

    Returns:
        Dict with stats: {job_title, company, generated, skipped, failed}
    """
    if profile is None:
        profile = load_profile()

    job = get_job_by_id(job_id)
    if not job:
        print(f"Job not found: {job_id}")
        return None

    print(f"Job: {job['job_title']}")
    print(f"Company: {job['company_name']}")

    # Get priority contacts
    contacts = get_priority_contacts_for_company(job['company_id'])

    stats = {'job_title': job['job_title'], 'company': job['company_name'], 'generated': 0, 'skipped': 0, 'failed': 0}

    if not contacts:
        # No contacts - generate one generic message
        print("  No priority contacts - generating generic message")

        existing = get_existing_message(job['company_id'], job['job_id'], None)
        if existing:
            print("    → Generic message already exists - skipped")
            stats['skipped'] = 1
            return stats

        context = f"Job: {job['job_title']}\nContact: None"
        message = generate_message(
            profile,
            job['company_name'],
            job.get('website'),
            job['job_title'],
            job.get('job_description'),
            job.get('match_reason'),
            None, None
        )

        if message:
            store_message(job['company_id'], job['job_id'], None, message, context)
            stats['generated'] = 1
            print("    ✓ Generic message generated")
        else:
            stats['failed'] = 1
            print("    ✗ Failed to generate message")

        return stats

    # Has contacts - generate one per contact
    print(f"  Found {len(contacts)} priority contacts")

    for contact in contacts:
        existing = get_existing_message(job['company_id'], job['job_id'], contact['id'])
        if existing:
            print(f"    → {contact['name']} - skipped (exists)")
            stats['skipped'] += 1
            continue

        context = f"Job: {job['job_title']}\nContact: {contact['name']} ({contact['title']})"
        message = generate_message(
            profile,
            job['company_name'],
            job.get('website'),
            job['job_title'],
            job.get('job_description'),
            job.get('match_reason'),
            contact['name'],
            contact['title']
        )

        if message:
            store_message(job['company_id'], job['job_id'], contact['id'], message, context)
            stats['generated'] += 1
            print(f"    ✓ {contact['name']} ({contact['title']})")
        else:
            stats['failed'] += 1
            print(f"    ✗ {contact['name']} - failed")

    return stats


def generate_all(profile=None, limit=None):
    """
    Generate messages for all pending target jobs.

    For each job:
    - If priority contacts exist: one message per contact
    - If no priority contacts: one generic message (contact_id = NULL)

    Args:
        profile: User profile dict (loaded if not provided)
        limit: Max messages to generate (None for all)

    Returns:
        Dict with stats: {generated, skipped, failed}
    """
    if profile is None:
        profile = load_profile()
        print(f"Loaded profile for: {profile['name']}")

    jobs = get_pending_target_jobs()

    if not jobs:
        print("No pending target jobs found.")
        return {'generated': 0, 'skipped': 0, 'failed': 0}

    print(f"Found {len(jobs)} pending target jobs")
    print("=" * 50)

    total_stats = {'generated': 0, 'skipped': 0, 'failed': 0}

    for i, job in enumerate(jobs, 1):
        if limit is not None and total_stats['generated'] >= limit:
            print(f"\nLimit reached ({limit} messages)")
            break

        print(f"\n[{i}/{len(jobs)}] {job['company_name']}: {job['job_title'][:40]}")

        contacts = get_priority_contacts_for_company(job['company_id'])

        if not contacts:
            # No contacts - generate generic message
            existing = get_existing_message(job['company_id'], job['job_id'], None)
            if existing:
                print("  → Skipped (generic message exists)")
                total_stats['skipped'] += 1
                continue

            context = f"Job: {job['job_title']}\nContact: None"
            message = generate_message(
                profile,
                job['company_name'],
                job.get('website'),
                job['job_title'],
                job.get('job_description'),
                job.get('match_reason'),
                None, None
            )

            if message:
                store_message(job['company_id'], job['job_id'], None, message, context)
                total_stats['generated'] += 1
                print("  ✓ Generic message generated")
            else:
                total_stats['failed'] += 1
                print("  ✗ Failed")
        else:
            # Has contacts - generate per contact
            print(f"  {len(contacts)} priority contacts")
            for contact in contacts:
                if limit is not None and total_stats['generated'] >= limit:
                    break

                existing = get_existing_message(job['company_id'], job['job_id'], contact['id'])
                if existing:
                    total_stats['skipped'] += 1
                    continue

                context = f"Job: {job['job_title']}\nContact: {contact['name']} ({contact['title']})"
                message = generate_message(
                    profile,
                    job['company_name'],
                    job.get('website'),
                    job['job_title'],
                    job.get('job_description'),
                    job.get('match_reason'),
                    contact['name'],
                    contact['title']
                )

                if message:
                    store_message(job['company_id'], job['job_id'], contact['id'], message, context)
                    total_stats['generated'] += 1
                    print(f"    ✓ {contact['name']}")
                else:
                    total_stats['failed'] += 1
                    print(f"    ✗ {contact['name']} - failed")

    return total_stats


def get_existing_messages():
    """Get count of existing messages."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM messages")
        row = cursor.fetchone()
        return row['cnt'] if is_remote() else row[0]


def main():
    """Generate personalized messages for all pending target jobs."""
    print("=" * 80)
    print("PERSONALIZED MESSAGE GENERATION")
    print("=" * 80)

    try:
        profile = load_profile()
        print(f"\n✓ Loaded profile for: {profile['name']}")
    except FileNotFoundError as e:
        print(f"\n✗ {e}")
        return

    existing_count = get_existing_messages()
    print(f"  Existing messages in database: {existing_count}")

    print("\n" + "=" * 80)
    print("GENERATING MESSAGES")
    print("=" * 80)

    stats = generate_all(profile=profile)

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"\n  Generated: {stats['generated']}")
    print(f"  Skipped (already exist): {stats['skipped']}")
    print(f"  Failed: {stats['failed']}")


if __name__ == "__main__":
    main()
