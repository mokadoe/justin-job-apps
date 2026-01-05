#!/usr/bin/env python3
"""Filter jobs using Claude API with two-stage description-based analysis.

Two-stage filtering approach:
1. Pre-filter with regex (seniority, non-engineering roles)
2. STAGE 1 - Haiku (cheap): Analyze all jobs for obvious ACCEPT/REVIEW/REJECT
   - ACCEPT: Clear new grad matches (score >= 0.7)
   - REVIEW: Borderline cases that need deeper analysis (score 0.5-0.7)
   - REJECT: Not suitable (score < 0.5)
3. STAGE 2 - Sonnet 4.5 (smart but expensive): Batch REVIEW cases with profile context
   - Uses candidate profile to make final decisions on borderline jobs
   - Batched to minimize API costs
4. Track intern jobs with is_intern flag (don't reject them)
5. Prioritize US jobs (priority=1) over non-US (priority=3)
"""

import json
import os
import re
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
import sys
# Add src/ to path for imports (works for both direct run and agent import)
src_path = Path(__file__).parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
from utils.constants import STATUS_NOT_RELEVANT, STATUS_PENDING
from utils.jobs_db_conn import get_connection, is_remote

# Cost tracking (optional)
try:
    from utils.cost_tracker import track_api_call
except ImportError:
    # If cost_tracker doesn't exist, use a no-op function
    def track_api_call(*args, **kwargs):
        pass

# Load environment variables from .env file
load_dotenv()

PROFILE_PATH = Path(__file__).parent.parent.parent / "profile.json"


def _placeholder():
    """Return SQL placeholder for current database."""
    return "%s" if is_remote() else "?"


BATCH_SIZE = 50  # Smaller batches for description analysis
SONNET_BATCH_SIZE = 20  # Smaller batches for expensive Sonnet calls

# Regex patterns for pre-filtering (case-insensitive)
REJECT_PATTERNS = {
    'seniority': re.compile(r'\b(senior|sr\.?|staff|principal|lead|manager|director|vp|vice president|chief|head of|c-level)\b', re.IGNORECASE),
    'non_engineering': re.compile(r'\b(sales|marketing|account executive|customer success|support|recruiter|recruiting|talent|operations|program manager|product manager|analyst|business development|designer|content|copywriter|finance|accounting|legal|hr|people|accountant|counsel|attorney)\b', re.IGNORECASE),
    'non_us': re.compile(r'\b(UK|United Kingdom|London|England|Scotland|Wales|Ireland|Dublin|Germany|Berlin|France|Paris|Spain|Madrid|Italy|Rome|Netherlands|Amsterdam|Switzerland|Zurich|Sweden|Stockholm|Norway|Oslo|Denmark|Copenhagen|Finland|Helsinki|Belgium|Brussels|Austria|Vienna|Portugal|Lisbon|Israel|Tel Aviv|India|Bangalore|Mumbai|China|Beijing|Shanghai|Japan|Tokyo|Singapore|Australia|Sydney|Canada|Toronto|Vancouver|Montreal)\b', re.IGNORECASE),
}

# US location indicators (for positive matching)
# State abbreviations and full names
US_STATES = r'\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b'
US_CITIES = r'\b(San Francisco|SF|NYC|New York|Boston|Seattle|Austin|Denver|Chicago|Los Angeles|LA|Portland|Miami|Atlanta|Washington|Philadelphia|Phoenix|San Diego|San Jose|Dallas|Houston|Detroit|Minneapolis|Tampa|St\. Louis|Baltimore|Charlotte|Indianapolis|Columbus|Nashville|Memphis|Louisville|Milwaukee|Albuquerque|Tucson|Sacramento|Kansas City|Mesa|Virginia Beach|Omaha|Oakland|Raleigh|Colorado Springs|Long Beach|Virginia Beach|Huntington Beach|Foster City|Redwood City|Mountain View|Palo Alto|Menlo Park|Sunnyvale|Santa Clara|Cupertino|San Mateo|Burlingame|Berkeley|Fremont|Irvine|Pasadena|Glendale|Arlington|Cambridge|Somerville)\b'
US_REMOTE = r'Remote \(US\)|Remote \(USA\)|Remote - US|Remote - USA|Remote US|Remote USA|US Remote|USA Remote'
# Match "US" with word boundaries, but be careful not to match words like "use"
US_EXPLICIT = r'\bUS\b|\bUSA\b|United States'
US_INDICATORS = re.compile(f'({US_STATES}|{US_CITIES}|{US_REMOTE}|{US_EXPLICIT})', re.IGNORECASE)

# Intern detection pattern
INTERN_PATTERN = re.compile(r'\b(intern|internship|co-op|coop)\b', re.IGNORECASE)

# New grad qualifiers that indicate combined roles
NEW_GRAD_QUALIFIERS = re.compile(r'\b(new grad|new graduate|entry level|entry-level|early career|junior|jr\.|associate)\b', re.IGNORECASE)


def is_intern_only(job_title):
    """
    Detect if a job is ONLY for interns (not combined with new grad).

    Returns True if:
    - Title contains "intern/internship" AND
    - Does NOT contain "new grad/entry-level/junior/associate"
    """
    has_intern = INTERN_PATTERN.search(job_title) is not None
    has_new_grad = NEW_GRAD_QUALIFIERS.search(job_title) is not None

    # Intern-only if it has intern keyword but no new grad qualifiers
    return has_intern and not has_new_grad


def get_unprocessed_jobs():
    """Get jobs that haven't been evaluated yet, including descriptions."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT j.id, j.job_title, j.job_description, j.location, c.name as company_name
            FROM jobs j
            JOIN companies c ON j.company_id = c.id
            WHERE j.evaluated = 0
            ORDER BY j.id
        """)

        jobs = [dict(row) for row in cursor.fetchall()]

        return jobs


def is_non_us_location(location):
    """
    Check if location is outside the US.

    Logic:
    1. Check for US indicators FIRST (states, cities, "Remote (US)")
    2. Then check for non-US indicators
    3. If unclear, assume US (most jobs are US-based on Ashby)

    Returns: (is_non_us: bool, location_info: str or None)
    """
    if not location:
        return False, None

    location = location.strip()

    # FIRST: Check if it has US indicators (states, cities, "Remote (US)")
    # This catches "Remote (United States | Canada)" -> US takes precedence
    if US_INDICATORS.search(location):
        return False, None

    # SECOND: Check if it's explicitly non-US
    non_us_match = REJECT_PATTERNS['non_us'].search(location)
    if non_us_match:
        return True, non_us_match.group()

    # THIRD: If just "Remote" with no country, assume US
    location_lower = location.lower()
    if location_lower.startswith('remote') and not any(country in location_lower for country in ['canada', 'uk', 'europe', 'apac', 'emea']):
        return False, None

    # Handle "Hybrid", "In office" patterns - assume US
    if any(pattern in location_lower for pattern in ['hybrid', 'in office', 'onsite']):
        return False, None

    # FOURTH: If has specific location but no US/non-US indicators, likely international
    # This is rare on Ashby (most specify country)
    if location and len(location) > 2:
        return True, location

    return False, None


def should_reject_with_regex(job_title, location=None):
    """
    Pre-filter jobs with regex to reject obvious non-matches.

    Note: Non-US locations are NOT rejected if they're for new grads/juniors.
    They're flagged as low priority instead.

    Returns: (should_reject: bool, reason: str, is_non_us: bool)
    """
    # Check for seniority indicators
    if REJECT_PATTERNS['seniority'].search(job_title):
        match = REJECT_PATTERNS['seniority'].search(job_title)
        return True, f"Seniority indicator: {match.group()}", False

    # Check for non-engineering roles
    if REJECT_PATTERNS['non_engineering'].search(job_title):
        match = REJECT_PATTERNS['non_engineering'].search(job_title)
        return True, f"Non-engineering role: {match.group()}", False

    # Check if non-US (but don't reject yet - will be handled differently)
    is_non_us, location_info = is_non_us_location(location)

    return False, None, is_non_us


def batch_jobs(jobs, batch_size=BATCH_SIZE):
    """Split jobs into batches."""
    for i in range(0, len(jobs), batch_size):
        yield jobs[i:i + batch_size]


def evaluate_batch_with_haiku(batch, client):
    """
    STAGE 1: Evaluate a batch of jobs using Claude Haiku for obvious decisions.

    Returns list of dicts with job_id, decision (ACCEPT/REVIEW/REJECT),
    score, reason, experience info.

    Score thresholds:
    - >= 0.7 = ACCEPT (clear new grad match)
    - 0.5-0.7 = REVIEW (borderline, needs Sonnet)
    - < 0.5 = REJECT (not suitable)
    """
    # Prepare jobs for Claude - include descriptions
    jobs_for_claude = []
    for job in batch:
        # Truncate description to save tokens
        desc = job.get("job_description", "")
        if desc:
            desc = desc[:2000]  # First 2000 chars should be enough

        jobs_for_claude.append({
            "job_id": job["id"],
            "title": job["job_title"],
            "location": job.get("location", ""),
            "description": desc
        })

    prompt = f"""You are doing STAGE 1 filtering for a CS new grad (0-2 years experience) seeking software engineering roles.

Your job: Make obvious decisions. Send borderline cases to REVIEW for deeper analysis.

SCORING CRITERIA:

ACCEPT (score >= 0.7) - Clear new grad matches:
1. Explicitly says "New Grad", "Entry Level", "Junior", or "0-2 years experience" (score 0.9-1.0)
2. Engineering role (SWE, ML, Data, DevOps, Backend, Frontend, Fullstack) with NO experience mentioned (score 0.7-0.8)
3. Has "Associate Engineer" or similar entry-level titles (score 0.8)
4. Internships (score 0.7+)

REVIEW (score 0.5-0.7) - Borderline cases needing human-level judgment:
- Engineering role asking for "1-3 years" - possibly flexible (score 0.6)
- Engineering role with "3-5 years" - might accept strong candidates (score 0.5)
- Unclear experience requirements but reasonable tech stack (score 0.5-0.6)
- Ambiguous titles or descriptions

REJECT (score < 0.5) - Clearly not suitable:
- Explicitly requires "5+ years" (score 0.1)
- Contains seniority keywords: "Senior", "Staff", "Principal", "Lead" (score 0.0)
- Non-engineering role (Sales, Marketing, Product Manager, etc.) (score 0.0)
- Clearly NOT suitable for new grads

JOBS TO EVALUATE:
{json.dumps(jobs_for_claude, indent=2)}

Return JSON array with ACCEPT/REVIEW/REJECT decisions:

[
  {{
    "job_id": 123,
    "decision": "ACCEPT" | "REVIEW" | "REJECT",
    "score": 0.0-1.0,
    "min_years": 0-10 or null,
    "max_years": 0-10 or null,
    "is_engineering": true/false,
    "reasoning": "Brief explanation"
  }},
  ...
]

Return ONLY the JSON array."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8000,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        # Parse response
        response_text = response.content[0].text.strip()

        # Remove markdown code blocks if present
        if response_text.startswith('```'):
            # Remove opening ```json or ```
            response_text = response_text.split('\n', 1)[1] if '\n' in response_text else response_text[3:]
            # Remove closing ```
            if response_text.endswith('```'):
                response_text = response_text.rsplit('```', 1)[0]
            response_text = response_text.strip()

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


def review_batch_with_sonnet(batch, client, profile):
    """
    STAGE 2: Review borderline jobs with Sonnet 4.5 using candidate profile.

    Returns list of dicts with job_id, final_decision (ACCEPT/REJECT),
    score, reason.
    """
    # Prepare jobs for Sonnet
    jobs_for_sonnet = []
    for job in batch:
        # Include full description for Sonnet (worth the cost)
        desc = job.get("job_description", "")

        jobs_for_sonnet.append({
            "job_id": job["job_id"],
            "title": job["job_title"],
            "company": job["company_name"],
            "location": job.get("location", ""),
            "description": desc[:3000],  # More context for Sonnet
            "haiku_score": job.get("score", 0.5),
            "haiku_reasoning": job.get("reasoning", "")
        })

    prompt = f"""You are making final decisions on borderline job postings for this candidate:

CANDIDATE PROFILE:
{json.dumps(profile, indent=2)}

These jobs were flagged as REVIEW by the initial filter (scores 0.5-0.7). Your job: Decide if they're suitable matches.

DECISION CRITERIA:
- Does the role align with candidate's CS + Chemistry background?
- Could a strong new grad (graduating May 2026, 0-2 years exp) realistically get this job?
- Does the tech stack match candidate's skills (ML, full-stack, AI/LLMs)?
- Is the company/role interesting for someone seeking AI-powered startup work?

ACCEPT if:
- Engineering role that could accept strong new grads
- Aligns with candidate's interests (AI/ML, full-stack, automation)
- Tech stack is reasonable for new grad level
- "1-3 years preferred" (often flexible for strong candidates)

REJECT if:
- Truly requires 3+ years experience (not flexible)
- Tech stack too senior (distributed systems architect, etc.)
- Role doesn't match candidate interests
- Not actually an engineering role

JOBS TO REVIEW:
{json.dumps(jobs_for_sonnet, indent=2)}

Return JSON array with final decisions:

[
  {{
    "job_id": 123,
    "decision": "ACCEPT" | "REJECT",
    "score": 0.0-1.0,
    "reasoning": "Why this is/isn't a good match for the candidate"
  }},
  ...
]

Return ONLY the JSON array."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=8000,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        # Parse response
        response_text = response.content[0].text.strip()

        # Remove markdown code blocks if present
        if response_text.startswith('```'):
            response_text = response_text.split('\n', 1)[1] if '\n' in response_text else response_text[3:]
            if response_text.endswith('```'):
                response_text = response_text.rsplit('```', 1)[0]
            response_text = response_text.strip()

        # Extract JSON
        if response_text.startswith('['):
            json_end = response_text.rfind(']') + 1
            response_text = response_text[:json_end]

        results = json.loads(response_text)
        return results

    except json.JSONDecodeError as e:
        print(f"    ⚠ Sonnet JSON parse error: {e}")
        print(f"    Response: {response_text[:200]}...")
        return []
    except Exception as e:
        print(f"    ✗ Sonnet API error: {e}")
        return []


def insert_target_jobs(all_jobs):
    """
    Insert ACCEPTED jobs into target_jobs table and mark all as evaluated.

    - ACCEPT: Inserted into target_jobs with status=1 (pending)
    - REJECT: NOT inserted (already tracked in jobs.evaluated)
    - REVIEW: NOT inserted (will be handled by Sonnet stage)
    - Priority: 1=high (US), 3=low (non-US but relevant)
    - Also track is_intern flag
    """
    if not all_jobs:
        return {'inserted': 0, 'accepted': 0, 'rejected': 0}

    p = _placeholder()

    with get_connection() as conn:
        cursor = conn.cursor()

        stats = {'inserted': 0, 'accepted': 0, 'rejected': 0}
        job_ids_to_mark = []

        for job in all_jobs:
            try:
                decision = job.get("decision", "REJECT")

                # Track stats
                if decision == "ACCEPT":
                    stats['accepted'] += 1
                elif decision == "REJECT":
                    stats['rejected'] += 1
                    # Mark as evaluated but DON'T insert into target_jobs
                    job_ids_to_mark.append(job["job_id"])
                    continue
                else:
                    # REVIEW - skip for now
                    continue

                # Only insert ACCEPT jobs into target_jobs
                # Determine priority: non-US jobs are low priority
                priority = 3 if job.get("is_non_us", False) else 1

                # Build experience analysis JSON
                experience_info = {
                    "min_years": job.get("min_years"),
                    "max_years": job.get("max_years"),
                    "is_engineering": job.get("is_engineering"),
                    "decision": decision
                }

                if is_remote():
                    cursor.execute(f"""
                        INSERT INTO target_jobs
                        (job_id, relevance_score, match_reason, status, priority, is_intern, experience_analysis)
                        VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
                        ON CONFLICT (job_id) DO NOTHING
                    """, (
                        job["job_id"],
                        job["score"],
                        job["reasoning"],
                        STATUS_PENDING,
                        priority,
                        job.get("is_intern", False),
                        json.dumps(experience_info)
                    ))
                else:
                    cursor.execute(f"""
                        INSERT OR IGNORE INTO target_jobs
                        (job_id, relevance_score, match_reason, status, priority, is_intern, experience_analysis)
                        VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
                    """, (
                        job["job_id"],
                        job["score"],
                        job["reasoning"],
                        STATUS_PENDING,
                        priority,
                        job.get("is_intern", False),
                        json.dumps(experience_info)
                    ))

                if cursor.rowcount > 0:
                    stats['inserted'] += 1
                    job_ids_to_mark.append(job["job_id"])

            except Exception as e:
                print(f"    ⚠ Error inserting job {job['job_id']}: {e}")

        # Mark all processed jobs as evaluated in jobs table
        if job_ids_to_mark:
            placeholders = ','.join([p] * len(job_ids_to_mark))
            cursor.execute(f"UPDATE jobs SET evaluated = 1 WHERE id IN ({placeholders})", job_ids_to_mark)

        conn.commit()

        return stats


def filter_all_jobs():
    """Main function: process all unprocessed jobs with description-based filtering."""
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

    # Pre-filter with regex (reject obvious non-matches)
    regex_rejected = []
    potentially_relevant = []

    for job in jobs:
        # Detect intern-only jobs
        intern_only = is_intern_only(job['job_title'])

        # Check if should reject based on regex
        should_reject, reason, is_non_us = should_reject_with_regex(job['job_title'], job.get('location'))

        if should_reject:
            regex_rejected.append({
                'job_id': job['id'],
                'decision': 'REJECT',
                'score': 0.0,
                'reasoning': f"Regex: {reason}",
                'is_intern': intern_only,
                'is_non_us': is_non_us,
                'min_years': None,
                'max_years': None,
                'is_engineering': False
            })
        else:
            # Add intern flag and location info to job for later processing
            job['is_intern'] = intern_only
            job['is_non_us'] = is_non_us
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
    print(f"Evaluating {len(potentially_relevant)} jobs with Claude Haiku (description analysis)")
    print(f"Batches: {num_batches} ({BATCH_SIZE} jobs per batch)")
    print("=" * 80)

    # STAGE 1: Haiku filtering
    total_accepted = 0
    total_review = 0
    total_rejected = 0
    total_processed = 0
    review_jobs = []  # Collect REVIEW jobs for Stage 2

    for i, batch in enumerate(batches, 1):
        print(f"\nBatch {i}/{num_batches}: Evaluating {len(batch)} jobs...")

        results = evaluate_batch_with_haiku(batch, client)

        if not results:
            print(f"  ✗ Batch failed - skipping")
            continue

        # Add intern flags and location info from pre-processing
        for result in results:
            # Find corresponding job to get intern flag and location info
            job = next((j for j in batch if j['id'] == result['job_id']), None)
            if job:
                result['is_intern'] = job.get('is_intern', False)
                result['is_non_us'] = job.get('is_non_us', False)

                # For REVIEW jobs, store full job data for Stage 2
                if result.get('decision') == 'REVIEW':
                    review_jobs.append({
                        **job,  # Full job data
                        **result  # Haiku's evaluation
                    })

        # Insert ACCEPT/REJECT jobs into database (REVIEW jobs skipped)
        stats = insert_target_jobs(results)

        # Count REVIEW jobs
        review_count = sum(1 for r in results if r.get('decision') == 'REVIEW')

        total_accepted += stats['accepted']
        total_rejected += stats['rejected']
        total_review += review_count
        total_processed += len(batch)

        print(f"  ✓ Evaluated {len(results)} jobs:")
        print(f"    ✓ ACCEPT: {stats['accepted']}")
        print(f"    ⚠ REVIEW: {review_count} (will send to Sonnet)")
        print(f"    ✗ REJECT: {stats['rejected']}")
        print(f"  → Inserted {stats['inserted']} into target_jobs")

        # Show progress
        print(f"  Progress: {total_processed}/{len(potentially_relevant)} jobs processed")
        print(f"  Running totals: {total_accepted} accepted, {total_review} review, {total_rejected} rejected")

    print("\n" + "=" * 80)
    print(f"STAGE 1 COMPLETE (Haiku) - {total_review} jobs need Stage 2 review")
    print("=" * 80)

    # STAGE 2: Sonnet review of borderline jobs
    sonnet_accepted = 0
    sonnet_rejected = 0

    if review_jobs:
        print(f"\n{'='*80}")
        print(f"STAGE 2: Reviewing {len(review_jobs)} borderline jobs with Sonnet 4.5")
        print(f"Batches: {(len(review_jobs) + SONNET_BATCH_SIZE - 1) // SONNET_BATCH_SIZE} ({SONNET_BATCH_SIZE} jobs per batch)")
        print("=" * 80)

        # Load candidate profile
        with open(PROFILE_PATH, 'r') as f:
            profile = json.load(f)

        # Batch review jobs for Sonnet
        sonnet_batches = list(batch_jobs(review_jobs, SONNET_BATCH_SIZE))

        for i, batch in enumerate(sonnet_batches, 1):
            print(f"\nSonnet Batch {i}/{len(sonnet_batches)}: Reviewing {len(batch)} jobs...")

            sonnet_results = review_batch_with_sonnet(batch, client, profile)

            if not sonnet_results:
                print(f"  ✗ Batch failed - skipping")
                continue

            # Prepare results for insertion
            final_jobs = []
            for result in sonnet_results:
                # Find original job data
                job = next((j for j in batch if j['job_id'] == result['job_id']), None)
                if job:
                    final_jobs.append({
                        'job_id': result['job_id'],
                        'decision': result['decision'],
                        'score': result['score'],
                        'reasoning': f"Sonnet review: {result['reasoning']}",
                        'is_intern': job.get('is_intern', False),
                        'is_non_us': job.get('is_non_us', False),
                        'min_years': job.get('min_years'),
                        'max_years': job.get('max_years'),
                        'is_engineering': job.get('is_engineering', True)
                    })

            # Insert Sonnet decisions
            stats = insert_target_jobs(final_jobs)

            sonnet_accepted += stats['accepted']
            sonnet_rejected += stats['rejected']

            print(f"  ✓ Reviewed {len(sonnet_results)} jobs:")
            print(f"    ✓ ACCEPT: {stats['accepted']}")
            print(f"    ✗ REJECT: {stats['rejected']}")
            print(f"  → Inserted {stats['inserted']} into target_jobs")
            print(f"  Running totals: {sonnet_accepted} accepted, {sonnet_rejected} rejected")

        print(f"\n{'='*80}")
        print(f"STAGE 2 COMPLETE (Sonnet)")
        print(f"  ✓ Accepted: {sonnet_accepted}")
        print(f"  ✗ Rejected: {sonnet_rejected}")
        print("=" * 80)

        # Update totals
        total_accepted += sonnet_accepted
        total_rejected += sonnet_rejected

    # Final summary
    print("\n" + "=" * 80)
    print("FILTERING COMPLETE")
    print("=" * 80)
    print(f"Total jobs: {total_jobs}")
    print(f"  Regex rejected: {len(regex_rejected)} ({len(regex_rejected)/total_jobs*100:.1f}%)")
    print(f"  Haiku evaluated: {total_processed} ({total_processed/total_jobs*100:.1f}%)")

    print(f"\nStage 1 (Haiku) Results:")
    print(f"  ✓ Auto-accepted: {total_accepted - (sonnet_accepted if review_jobs else 0)}")
    print(f"  ⚠ Sent to review: {total_review}")
    print(f"  ✗ Auto-rejected: {total_rejected - (sonnet_rejected if review_jobs else 0)}")

    if review_jobs:
        print(f"\nStage 2 (Sonnet) Results:")
        print(f"  ✓ Accepted: {sonnet_accepted}")
        print(f"  ✗ Rejected: {sonnet_rejected}")

    print(f"\nFinal Totals:")
    print(f"  ✓ TOTAL ACCEPTED: {total_accepted}")
    print(f"  ✗ TOTAL REJECTED: {total_rejected + len(regex_rejected)}")
    print(f"\n  → Jobs pending (status=1): {total_accepted}")

    print("\nRun 'make targets' to see results")
    print("\nTo see accepted jobs by priority:")
    print("  High priority (US): sqlite3 data/jobs.db 'SELECT COUNT(*) FROM target_jobs WHERE status=1 AND priority=1'")
    print("  Low priority (non-US): sqlite3 data/jobs.db 'SELECT COUNT(*) FROM target_jobs WHERE status=1 AND priority=3'")


if __name__ == "__main__":
    filter_all_jobs()
