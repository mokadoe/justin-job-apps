#!/usr/bin/env python3
"""Push outreach messages to Gmail as drafts.

This script:
1. Gets message for a job ID (highest confidence contact)
2. Generates email addresses
3. Generates catchy subject line
4. Converts message to HTML
5. Creates Gmail draft (or previews)

Usage:
    python3 src/outreach/push_email.py <job_id> [--preview]
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.jobs_db_conn import get_connection, is_remote

from outreach.email_utils import (
    extract_domain,
    generate_email_candidates,
    generate_generic_emails,
    build_email_body,
    text_to_html,
    extract_first_name
)
from outreach.subject_generator import generate_subject


def _placeholder():
    """Return SQL placeholder for current database."""
    return "%s" if is_remote() else "?"


def get_message_for_job(job_id):
    """
    Get message for a job with highest confidence contact.

    Returns the message with contact and company info, prioritizing:
    1. High confidence contacts
    2. Priority contacts

    Args:
        job_id: ID of the job

    Returns:
        Dict with message, contact, and company info, or None if not found
    """
    p = _placeholder()
    # PostgreSQL uses TRUE, SQLite uses 1
    priority_val = "TRUE" if is_remote() else "1"

    with get_connection() as conn:
        cursor = conn.cursor()

        # Query message with contact and company info
        # Order by contact confidence and priority
        cursor.execute(f"""
            SELECT
                m.id as message_id,
                m.message_text,
                m.contact_id,
                m.company_id,
                m.draft_created_at,
                c.name as contact_name,
                c.title as contact_title,
                c.match_confidence,
                co.name as company_name,
                co.website,
                j.job_title,
                j.job_description
            FROM messages m
            JOIN companies co ON m.company_id = co.id
            JOIN jobs j ON m.job_id = j.id
            LEFT JOIN contacts c ON m.contact_id = c.id
            WHERE m.job_id = {p}
            ORDER BY
                CASE WHEN c.match_confidence = 'high' THEN 0 ELSE 1 END,
                CASE WHEN c.is_priority = {priority_val} THEN 0 ELSE 1 END
            LIMIT 1
        """, (job_id,))

        row = cursor.fetchone()

        if not row:
            return None

        return dict(row)


def update_draft_created(message_id):
    """Mark message as having draft created."""
    p = _placeholder()
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            UPDATE messages SET draft_created_at = {p} WHERE id = {p}
        """, (now, message_id))
        conn.commit()


def push_email_draft(job_id, preview=False):
    """
    Push message for a job to Gmail as draft.

    Args:
        job_id: ID of the job
        preview: If True, show preview without creating draft

    Returns:
        Dict with result info:
        - success: bool
        - error: str (if failed)
        - preview: dict with email details (if preview mode)
        - draft: dict with draft info (if created)
    """
    print(f"Looking up message for job ID {job_id}...")

    # Get message
    message = get_message_for_job(job_id)

    if not message:
        return {
            'success': False,
            'error': f"No message found for job ID {job_id}. Run '/generate job {job_id}' first."
        }

    # Check if draft already created
    if message.get('draft_created_at') and not preview:
        return {
            'success': False,
            'error': f"Draft already created for this message on {message['draft_created_at']}"
        }

    print(f"Found message for {message['company_name']} - {message['job_title']}")

    # Extract domain
    domain = extract_domain(message.get('website'))
    if not domain:
        # Fallback: use company name
        company_clean = message['company_name'].lower().replace(' ', '').replace(',', '')
        domain = f"{company_clean}.com"
        print(f"  Warning: No website found, guessing domain: {domain}")

    # Generate email addresses
    contact_name = message.get('contact_name')
    if contact_name:
        email_candidates = generate_email_candidates(contact_name, domain)
        print(f"  Contact: {contact_name} ({message.get('contact_title')})")
    else:
        email_candidates = generate_generic_emails(domain)
        print("  No contact - using generic emails")

    to_addresses = [c['email'] for c in email_candidates]
    print(f"  To: {', '.join(to_addresses)}")

    # Generate subject
    print("  Generating subject line...")
    subject = generate_subject(
        message['company_name'],
        message['job_title'],
        message.get('job_description')
    )
    print(f"  Subject: {subject}")

    # Build HTML body
    html_body = build_email_body(message['message_text'], contact_name)
    plain_text = message['message_text']

    # Add greeting to plain text for display
    if contact_name:
        first_name = extract_first_name(contact_name)
        greeting = f"Hi {first_name}," if first_name else "Hi there,"
        plain_text_with_greeting = f"{greeting}\n\n{plain_text}"
    else:
        plain_text_with_greeting = f"Hi there,\n\n{plain_text}"

    if preview:
        # Return preview info
        return {
            'success': True,
            'preview': {
                'to': to_addresses,
                'subject': subject,
                'html_body': html_body,
                'plain_text': plain_text_with_greeting,
                'company': message['company_name'],
                'job_title': message['job_title'],
                'contact': contact_name,
                'contact_title': message.get('contact_title'),
            }
        }

    # Create Gmail draft
    print("  Creating Gmail draft...")
    try:
        from outreach.gmail_auth import get_gmail_service, create_draft

        service = get_gmail_service()
        draft = create_draft(service, to_addresses, subject, html_body)

        # Update database
        update_draft_created(message['message_id'])

        print(f"  Draft created: {draft['link']}")

        return {
            'success': True,
            'draft': {
                'id': draft['id'],
                'link': draft['link'],
                'to': to_addresses,
                'subject': subject,
                'company': message['company_name'],
                'job_title': message['job_title']
            }
        }

    except FileNotFoundError as e:
        return {
            'success': False,
            'error': str(e)
        }
    except Exception as e:
        return {
            'success': False,
            'error': f"Failed to create draft: {e}"
        }


def format_preview(result):
    """Format preview result for display."""
    if not result.get('success'):
        return f"Error: {result.get('error')}"

    preview = result['preview']
    lines = [
        "=" * 60,
        "EMAIL PREVIEW",
        "=" * 60,
        f"Company: {preview['company']}",
        f"Job: {preview['job_title']}",
        f"Contact: {preview.get('contact') or 'Generic'} ({preview.get('contact_title') or 'N/A'})",
        "",
        f"To: {', '.join(preview['to'])}",
        f"Subject: {preview['subject']}",
        "",
        "-" * 60,
        "MESSAGE (Plain Text)",
        "-" * 60,
        preview['plain_text'],
        "",
        "-" * 60,
        "MESSAGE (HTML)",
        "-" * 60,
        preview['html_body'],
        "",
        "=" * 60,
        "Run without --preview to create Gmail draft.",
        "=" * 60,
    ]
    return '\n'.join(lines)


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Push message to Gmail draft')
    parser.add_argument('job_id', type=int, help='Job ID to push')
    parser.add_argument('--preview', action='store_true', help='Preview without creating draft')

    args = parser.parse_args()

    result = push_email_draft(args.job_id, preview=args.preview)

    if args.preview:
        print(format_preview(result))
    elif result['success']:
        print(f"\nDraft created successfully!")
        print(f"Open in Gmail: {result['draft']['link']}")
    else:
        print(f"\nError: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
