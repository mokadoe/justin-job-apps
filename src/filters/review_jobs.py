#!/usr/bin/env python3
"""Interactive review of jobs marked as REVIEW.

Displays jobs that need human judgment and allows accepting or rejecting them.
"""

import sqlite3
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.constants import STATUS_NOT_RELEVANT, STATUS_PENDING

DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"


def get_review_jobs():
    """Get all jobs marked as REVIEW that need human judgment."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            t.id as target_id,
            j.id as job_id,
            j.job_title,
            j.job_description,
            j.location,
            j.posted_date,
            c.name as company_name,
            c.website,
            t.relevance_score,
            t.match_reason,
            t.is_intern,
            t.experience_analysis
        FROM target_jobs t
        JOIN jobs j ON t.job_id = j.id
        JOIN companies c ON j.company_id = c.id
        WHERE t.status = ?
          AND (t.match_reason LIKE '%REVIEW%' OR LOWER(t.match_reason) LIKE '%review%')
        ORDER BY t.relevance_score DESC
    """, (STATUS_PENDING,))

    jobs = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return jobs


def display_job(job, index, total):
    """Display job details for review."""
    print("\n" + "=" * 80)
    print(f"JOB {index}/{total}")
    print("=" * 80)
    print(f"Company:   {job['company_name']}")
    print(f"Title:     {job['job_title']}")
    print(f"Location:  {job['location']}")
    print(f"Posted:    {job['posted_date'] or 'Unknown'}")
    print(f"Website:   {job['website'] or 'Not found'}")
    print(f"Score:     {job['relevance_score']}")
    print(f"Intern:    {'Yes' if job['is_intern'] else 'No'}")
    print()
    print(f"Reason:    {job['match_reason']}")

    # Parse and display experience analysis if available
    if job['experience_analysis']:
        try:
            exp_data = json.loads(job['experience_analysis'])
            print(f"Experience: {exp_data.get('min_years', '?')}-{exp_data.get('max_years', '?')} years")
            print(f"Engineering: {'Yes' if exp_data.get('is_engineering') else 'No'}")
        except:
            pass

    print()
    print("Description preview:")
    print("-" * 80)
    desc = job['job_description'] or "No description available"
    print(desc[:500])
    if len(desc) > 500:
        print("\n... (truncated)")
    print("-" * 80)


def get_user_decision():
    """Prompt user for decision on current job."""
    while True:
        print()
        choice = input("Decision? [a]ccept / [r]eject / [s]kip / [q]uit: ").lower().strip()

        if choice in ['a', 'accept']:
            return 'ACCEPT'
        elif choice in ['r', 'reject']:
            return 'REJECT'
        elif choice in ['s', 'skip']:
            return 'SKIP'
        elif choice in ['q', 'quit']:
            return 'QUIT'
        else:
            print("Invalid choice. Please enter a, r, s, or q.")


def update_job_status(target_id, decision):
    """Update job status based on user decision."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if decision == 'ACCEPT':
        # Keep as pending (status=1) but update match_reason to remove REVIEW tag
        cursor.execute("""
            UPDATE target_jobs
            SET match_reason = REPLACE(match_reason, 'REVIEW: ', 'ACCEPTED: ')
            WHERE id = ?
        """, (target_id,))
    elif decision == 'REJECT':
        # Mark as not relevant (status=0)
        cursor.execute("""
            UPDATE target_jobs
            SET status = ?, match_reason = 'REJECTED: ' || match_reason
            WHERE id = ?
        """, (STATUS_NOT_RELEVANT, target_id))

    conn.commit()
    conn.close()


def review_all_jobs():
    """Main review loop."""
    jobs = get_review_jobs()

    if not jobs:
        print("✓ No jobs pending review!")
        print("\nAll REVIEW jobs have been processed.")
        return

    total = len(jobs)
    print(f"\n{'='*80}")
    print(f"REVIEW QUEUE: {total} jobs need your decision")
    print(f"{'='*80}")
    print("\nYou can:")
    print("  [a]ccept - Mark as relevant (keep in pending)")
    print("  [r]eject - Mark as not relevant (remove from pending)")
    print("  [s]kip   - Leave for later")
    print("  [q]uit   - Exit review session")

    stats = {'accepted': 0, 'rejected': 0, 'skipped': 0}

    for i, job in enumerate(jobs, 1):
        display_job(job, i, total)
        decision = get_user_decision()

        if decision == 'QUIT':
            print("\nExiting review session...")
            break
        elif decision == 'SKIP':
            print("Skipped.")
            stats['skipped'] += 1
        else:
            update_job_status(job['target_id'], decision)
            print(f"✓ Marked as {decision}")
            if decision == 'ACCEPT':
                stats['accepted'] += 1
            else:
                stats['rejected'] += 1

    # Summary
    print("\n" + "=" * 80)
    print("REVIEW SESSION SUMMARY")
    print("=" * 80)
    print(f"Total reviewed: {stats['accepted'] + stats['rejected']}")
    print(f"  ✓ Accepted: {stats['accepted']}")
    print(f"  ✗ Rejected: {stats['rejected']}")
    print(f"  ⊙ Skipped:  {stats['skipped']}")

    remaining = total - (stats['accepted'] + stats['rejected'])
    if remaining > 0:
        print(f"\n{remaining} jobs still need review. Run 'make review' again to continue.")
    else:
        print("\n✓ All jobs reviewed!")


if __name__ == "__main__":
    try:
        review_all_jobs()
    except KeyboardInterrupt:
        print("\n\nReview interrupted. Your progress has been saved.")
        print("Run 'make review' again to continue.")
