#!/usr/bin/env python3
"""Filter jobs using Claude API and populate target_jobs table.

This script:
1. Queries unprocessed jobs (not in target_jobs)
2. Pre-filters with regex to reject obvious non-matches (fast & free)
3. Batches remaining jobs for efficient API calls
4. Uses Claude to evaluate relevance
5. Inserts relevant jobs into target_jobs table
"""

import sqlite3
import json
import os
import re
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.constants import STATUS_NOT_RELEVANT, STATUS_PENDING

# Load environment variables from .env file
load_dotenv()

DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"
BATCH_SIZE = 100

# Regex patterns for pre-filtering (case-insensitive)
REJECT_PATTERNS = {
    'seniority': re.compile(r'\b(senior|sr\.|staff|principal|lead|manager|director|vp|vice president|chief|head of|c-level)\b', re.IGNORECASE),
    'non_engineering': re.compile(r'\b(sales|marketing|account executive|customer success|support|recruiter|recruiting|talent|operations|program manager|product manager|analyst|business development|designer|content|copywriter|finance|accounting|legal|hr|people)\b', re.IGNORECASE),
    'internship': re.compile(r'\b(intern|internship|co-op|coop|part-time|part time)\b', re.IGNORECASE),
}


def get_unprocessed_jobs():
    """Get jobs that haven't been evaluated yet."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT j.id, j.job_title, c.name as company_name
        FROM jobs j
        JOIN companies c ON j.company_id = c.id
        WHERE j.evaluated = 0
        ORDER BY j.id
    """)

    jobs = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return jobs


def should_reject_with_regex(job_title):
    """
    Pre-filter jobs with regex to reject obvious non-matches.

    Returns: (should_reject: bool, reason: str)
    """
    # Check for seniority indicators
    if REJECT_PATTERNS['seniority'].search(job_title):
        match = REJECT_PATTERNS['seniority'].search(job_title)
        return True, f"Seniority indicator: {match.group()}"

    # Check for non-engineering roles
    if REJECT_PATTERNS['non_engineering'].search(job_title):
        match = REJECT_PATTERNS['non_engineering'].search(job_title)
        return True, f"Non-engineering role: {match.group()}"

    # Check for internships
    if REJECT_PATTERNS['internship'].search(job_title):
        match = REJECT_PATTERNS['internship'].search(job_title)
        return True, f"Internship/Co-op/Part-time: {match.group()}"

    return False, None


def batch_jobs(jobs, batch_size=BATCH_SIZE):
    """Split jobs into batches."""
    for i in range(0, len(jobs), batch_size):
        yield jobs[i:i + batch_size]


def evaluate_batch_with_claude(batch, client):
    """
    Evaluate a batch of jobs using Claude API.

    Returns list of dicts with job_id, relevant, score, reason.
    """
    # Prepare jobs for Claude
    jobs_for_claude = [
        {
            "job_id": job["id"],
            "title": job["job_title"],
            "company": job["company_name"]
        }
        for job in batch
    ]

    prompt = f"""You are filtering jobs for a new graduate software engineer seeking their first full-time role.

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
- Are non-engineering: Sales, Marketing, Support, Product Manager, Program Manager, Analyst
- Are internships, co-ops, or part-time
- Just say "Software Engineer" or "Engineer" without new grad qualifier (REJECT these - too ambiguous)

SCORING GUIDE:
- 1.0: Has "New Grad" or "New Graduate" in title + engineering role
- 0.9: Has "Junior" or "Entry Level" in title + engineering role
- 0.8: Has "Associate" in title + engineering role
- 0.0-0.2: Everything else (reject)

JOBS TO EVALUATE:
{json.dumps(jobs_for_claude, indent=2)}

For each job, evaluate if it matches the STRICT criteria.

Return a JSON array in EXACTLY this format (matching input order):
[
  {{"job_id": 1, "relevant": true, "score": 1.0, "reason": "New Grad Software Engineer role"}},
  {{"job_id": 2, "relevant": false, "score": 0.1, "reason": "No new grad qualifier in title"}},
  ...
]

IMPORTANT: Return ONLY the JSON array, no other text."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
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


def insert_target_jobs(all_jobs):
    """
    Insert ALL evaluated jobs into target_jobs table and mark as evaluated.

    Relevant jobs: status=1 (pending)
    Not relevant jobs: status=0 (rejected)
    """
    if not all_jobs:
        return {'inserted': 0, 'relevant': 0, 'rejected': 0}

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    stats = {'inserted': 0, 'relevant': 0, 'rejected': 0}
    job_ids_to_mark = []

    for job in all_jobs:
        try:
            is_relevant = job.get("relevant", False)
            status = STATUS_PENDING if is_relevant else STATUS_NOT_RELEVANT

            cursor.execute("""
                INSERT OR IGNORE INTO target_jobs (job_id, relevance_score, match_reason, status)
                VALUES (?, ?, ?, ?)
            """, (job["job_id"], job["score"], job["reason"], status))

            if cursor.rowcount > 0:
                stats['inserted'] += 1
                if is_relevant:
                    stats['relevant'] += 1
                else:
                    stats['rejected'] += 1

                job_ids_to_mark.append(job["job_id"])

        except Exception as e:
            print(f"    ⚠ Error inserting job {job['job_id']}: {e}")

    # Mark all processed jobs as evaluated
    if job_ids_to_mark:
        placeholders = ','.join('?' * len(job_ids_to_mark))
        cursor.execute(f"UPDATE jobs SET evaluated = 1 WHERE id IN ({placeholders})", job_ids_to_mark)

    conn.commit()
    conn.close()

    return stats


def filter_all_jobs():
    """Main function: process all unprocessed jobs with regex pre-filtering."""
    # Check for API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("⚠ ANTHROPIC_API_KEY not found in environment")
        print("Set it with: export ANTHROPIC_API_KEY='your-key-here'")
        return

    client = Anthropic(api_key=api_key)

    # Get unprocessed jobs
    jobs = get_unprocessed_jobs()

    if not jobs:
        print("✓ No unprocessed jobs found - all jobs have been evaluated!")
        return

    total_jobs = len(jobs)

    print("=" * 80)
    print(f"Pre-filtering {total_jobs} jobs with regex...")
    print("=" * 80)

    # Pre-filter with regex
    regex_rejected = []
    potentially_relevant = []

    for job in jobs:
        should_reject, reason = should_reject_with_regex(job['job_title'])
        if should_reject:
            regex_rejected.append({
                'job_id': job['id'],
                'relevant': False,
                'score': 0.0,
                'reason': f"Regex: {reason}"
            })
        else:
            potentially_relevant.append(job)

    print(f"\n✓ Regex pre-filtering complete:")
    print(f"  ✗ Rejected: {len(regex_rejected)} ({len(regex_rejected)/total_jobs*100:.1f}%)")
    print(f"  → Sending to Claude: {len(potentially_relevant)} ({len(potentially_relevant)/total_jobs*100:.1f}%)")

    # Insert regex-rejected jobs directly
    if regex_rejected:
        print(f"\nInserting {len(regex_rejected)} regex-rejected jobs...")
        stats = insert_target_jobs(regex_rejected)
        print(f"  ✓ Inserted {stats['inserted']} regex-rejected jobs")

    # Process remaining jobs with Claude API
    if not potentially_relevant:
        print("\n✓ All jobs rejected by regex - no API calls needed!")
        return

    batches = list(batch_jobs(potentially_relevant))
    num_batches = len(batches)

    print("\n" + "=" * 80)
    print(f"Evaluating {len(potentially_relevant)} jobs with Claude API")
    print(f"Batches: {num_batches} ({BATCH_SIZE} jobs per batch)")
    print("=" * 80)

    total_relevant = 0
    total_rejected = 0
    total_processed = 0

    for i, batch in enumerate(batches, 1):
        print(f"\nBatch {i}/{num_batches}: Evaluating {len(batch)} jobs...")

        results = evaluate_batch_with_claude(batch, client)

        if not results:
            print(f"  ✗ Batch failed - skipping")
            continue

        # Insert ALL jobs (relevant and rejected) into database
        stats = insert_target_jobs(results)

        total_relevant += stats['relevant']
        total_rejected += stats['rejected']
        total_processed += len(batch)

        print(f"  ✓ Evaluated {len(results)} jobs: {stats['relevant']} relevant, {stats['rejected']} rejected")
        print(f"  → Inserted {stats['inserted']} into target_jobs")

        # Show progress
        print(f"  Progress: {total_processed}/{len(potentially_relevant)} jobs processed, {total_relevant} relevant so far ({total_relevant/total_processed*100:.1f}%)")

    # Final summary
    print("\n" + "=" * 80)
    print("FILTERING COMPLETE")
    print("=" * 80)
    print(f"Total jobs: {total_jobs}")
    print(f"  Regex rejected: {len(regex_rejected)} ({len(regex_rejected)/total_jobs*100:.1f}%)")
    print(f"  Claude evaluated: {total_processed} ({total_processed/total_jobs*100:.1f}%)")
    print(f"    ✓ Relevant (pending): {total_relevant} ({total_relevant/total_processed*100:.1f}% of evaluated)")
    print(f"    ✗ Rejected: {total_rejected} ({total_rejected/total_processed*100:.1f}% of evaluated)")
    print("\nRun 'make targets' to see results")


if __name__ == "__main__":
    filter_all_jobs()
