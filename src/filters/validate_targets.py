#!/usr/bin/env python3
"""Re-validate pending target jobs with strict new grad criteria.

This script re-evaluates all jobs currently marked as pending (status=1)
to ensure they meet the strict "new grad" requirement.
"""

import sqlite3
import json
import os
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.constants import STATUS_NOT_RELEVANT, STATUS_PENDING

# Load environment variables
load_dotenv()

DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"
BATCH_SIZE = 100


def get_pending_jobs():
    """Get all jobs currently marked as pending (status=1)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT t.id as target_id, j.id as job_id, j.job_title, c.name as company_name
        FROM target_jobs t
        JOIN jobs j ON t.job_id = j.id
        JOIN companies c ON j.company_id = c.id
        WHERE t.status = 1
        ORDER BY t.id
    """)

    jobs = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return jobs


def validate_batch_with_claude(batch, client):
    """
    Validate a batch of jobs using Claude API with STRICT new grad criteria.

    Returns list of dicts with job_id, relevant, score, reason.
    """
    # Prepare jobs for Claude
    jobs_for_claude = [
        {
            "job_id": job["job_id"],
            "title": job["job_title"],
            "company": job["company_name"]
        }
        for job in batch
    ]

    prompt = f"""You are RE-VALIDATING jobs that were previously marked as relevant for a new graduate.

STRICT REQUIREMENT - ONLY ACCEPT if:
The job title EXPLICITLY contains one of these phrases:
- "New Grad" or "New Graduate"
- "Junior"
- "Entry Level" or "Entry-Level"
- "Associate" (as in "Associate Engineer")

AND the role is an engineering position (Software Engineer, Backend/Frontend/Fullstack, ML Engineer, Data Engineer, DevOps, Platform Engineer, Infrastructure Engineer, Security Engineer, QA Engineer, Mobile Engineer)

REJECT ALL jobs that:
- Do NOT explicitly mention new grad/junior/entry-level/associate in the title
- Have seniority indicators: Senior, Staff, Principal, Lead, Manager, Director, VP, C-level, Head of
- Are non-engineering: Sales, Marketing, Support, Product Manager, Program Manager, Analyst, Operations
- Are internships, co-ops, or part-time
- Just say "Software Engineer" or "Engineer" without new grad qualifier (REJECT these - too ambiguous)

EXAMPLES:
- "Software Engineer, New Grad" → ACCEPT (score: 1.0)
- "Junior Backend Engineer" → ACCEPT (score: 0.9)
- "Associate Software Engineer" → ACCEPT (score: 0.8)
- "Software Engineer" → REJECT (no qualifier, score: 0.1)
- "Backend Engineer" → REJECT (no qualifier, score: 0.1)
- "ML Engineer" → REJECT (no qualifier, score: 0.1)

JOBS TO RE-VALIDATE:
{json.dumps(jobs_for_claude, indent=2)}

For each job, evaluate if it meets the STRICT new grad criteria.

Return a JSON array in EXACTLY this format (matching input order):
[
  {{"job_id": 1, "relevant": true, "score": 1.0, "reason": "Explicitly says New Grad"}},
  {{"job_id": 2, "relevant": false, "score": 0.1, "reason": "No new grad qualifier in title"}},
  ...
]

IMPORTANT: Return ONLY the JSON array, no other text."""

    try:
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        # Parse response
        response_text = response.content[0].text.strip()

        # Try to extract JSON if there's extra text
        if response_text.startswith('['):
            json_end = response_text.rfind(']') + 1
            response_text = response_text[:json_end]

        results = json.loads(response_text)

        return results

    except json.JSONDecodeError as e:
        print(f"    ⚠ JSON parse error: {e}")
        print(f"    Response: {response_text[:200]}...")
        return []
    except Exception as e:
        print(f"    ✗ API error: {e}")
        return []


def update_target_jobs(results):
    """
    Update target_jobs based on validation results.

    Jobs that fail validation are moved from status=1 (pending) to status=0 (not relevant).
    """
    if not results:
        return {'kept': 0, 'rejected': 0}

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    stats = {'kept': 0, 'rejected': 0}

    for job in results:
        is_relevant = job.get("relevant", False)
        job_id = job["job_id"]

        if not is_relevant:
            # Update to rejected status
            cursor.execute("""
                UPDATE target_jobs
                SET status = ?, relevance_score = ?, match_reason = ?
                WHERE job_id = ?
            """, (STATUS_NOT_RELEVANT, job["score"], job["reason"], job_id))

            if cursor.rowcount > 0:
                stats['rejected'] += 1
        else:
            # Keep as pending, but update score and reason with validation result
            cursor.execute("""
                UPDATE target_jobs
                SET relevance_score = ?, match_reason = ?
                WHERE job_id = ? AND status = 1
            """, (job["score"], job["reason"], job_id))

            if cursor.rowcount > 0:
                stats['kept'] += 1

    conn.commit()
    conn.close()

    return stats


def batch_jobs(jobs, batch_size=BATCH_SIZE):
    """Split jobs into batches."""
    for i in range(0, len(jobs), batch_size):
        yield jobs[i:i + batch_size]


def validate_all_pending():
    """Main function: re-validate all pending jobs."""
    # Check for API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("⚠ ANTHROPIC_API_KEY not found in environment")
        print("Set it with: export ANTHROPIC_API_KEY='your-key-here'")
        return

    client = Anthropic(api_key=api_key)

    # Get pending jobs
    jobs = get_pending_jobs()

    if not jobs:
        print("✓ No pending jobs to validate!")
        return

    total_jobs = len(jobs)
    batches = list(batch_jobs(jobs))
    num_batches = len(batches)

    print("=" * 80)
    print(f"RE-VALIDATING {total_jobs} PENDING JOBS")
    print(f"Batches: {num_batches} ({BATCH_SIZE} jobs per batch)")
    print("=" * 80)

    total_kept = 0
    total_rejected = 0

    for i, batch in enumerate(batches, 1):
        print(f"\nBatch {i}/{num_batches}: Validating {len(batch)} jobs...")

        results = validate_batch_with_claude(batch, client)

        if not results:
            print(f"  ✗ Batch failed - skipping")
            continue

        # Update database
        stats = update_target_jobs(results)

        total_kept += stats['kept']
        total_rejected += stats['rejected']

        print(f"  ✓ Validated {len(results)} jobs: {stats['kept']} kept, {stats['rejected']} rejected")
        print(f"  Progress: {i * len(batch)}/{total_jobs} jobs validated")

    # Final summary
    print("\n" + "=" * 80)
    print("VALIDATION COMPLETE")
    print("=" * 80)
    print(f"Total jobs validated: {total_jobs}")
    print(f"  ✓ Still relevant (kept as pending): {total_kept}")
    print(f"  ✗ No longer relevant (moved to rejected): {total_rejected}")

    if total_kept > 0:
        print(f"\nYou now have {total_kept} strictly verified new grad jobs!")
        print("Run 'make targets' to see updated statistics")
    else:
        print("\n⚠ No jobs passed strict validation. Consider expanding your search criteria.")


if __name__ == "__main__":
    validate_all_pending()
