"""
Filter command - AI-powered job filtering for new grad relevance.

Usage:
    /filter              - Filter all unevaluated jobs
    /filter 100          - Filter up to 100 jobs (for testing)
    /filter reset        - Reset evaluated flag on all jobs (re-filter)

Two-stage filtering:
    Stage 0: Regex pre-filter (fast, free)
    Stage 1: Haiku batch evaluation (cheap)
    Stage 2: Sonnet review for borderline cases (expensive, with profile context)
"""

import asyncio
import json
import os
from pathlib import Path

from anthropic import Anthropic

from . import register

# Import filter logic from src/filters via sys.path (set up in __init__.py)
from filters.filter_jobs import (
    should_reject_with_regex,
    is_intern_only,
    batch_jobs,
    evaluate_batch_with_haiku,
    review_batch_with_sonnet,
    BATCH_SIZE,
    SONNET_BATCH_SIZE,
)

PROFILE_PATH = Path(__file__).parent.parent.parent / "profile.json"


@register(
    "filter",
    description="AI filter jobs for new grad relevance",
    usage="/filter [limit] | /filter reset"
)
async def handle_filter(args: str):
    """Handle /filter command with streaming progress."""
    import jobs_db

    # Parse args
    args = args.strip().lower()

    if args == "reset":
        async for event in handle_reset():
            yield event
        return

    limit = int(args) if args.isdigit() else None

    # Check for API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        yield {"type": "error", "text": "ANTHROPIC_API_KEY not found in environment"}
        return

    # Initialize database
    await jobs_db.init_jobs_db()

    # Get unevaluated jobs
    yield {"type": "progress", "text": "Fetching unevaluated jobs..."}
    jobs = await jobs_db.get_unevaluated_jobs(limit=limit)

    if not jobs:
        yield {"type": "done", "text": "✓ No unevaluated jobs found - all jobs have been evaluated"}
        return

    total_jobs = len(jobs)
    yield {"type": "progress", "text": f"Found {total_jobs} jobs to filter"}

    # Stage 0: Regex pre-filter
    yield {"type": "progress", "text": f"\n{'='*60}"}
    yield {"type": "progress", "text": "STAGE 0: Pre-filtering with regex..."}
    yield {"type": "progress", "text": f"{'='*60}"}

    regex_rejected = []
    potentially_relevant = []

    for job in jobs:
        # Detect intern-only jobs
        intern_only = is_intern_only(job['job_title'])

        # Check if should reject based on regex
        should_reject, reason, is_non_us = should_reject_with_regex(
            job['job_title'], job.get('location')
        )

        if should_reject:
            regex_rejected.append({
                'job_id': job['id'],
                'decision': 'REJECT',
                'score': 0.0,
                'reasoning': f"Regex: {reason}",
                'is_intern': intern_only,
                'is_non_us': is_non_us,
            })
        else:
            # Add flags for later processing
            job['is_intern'] = intern_only
            job['is_non_us'] = is_non_us
            potentially_relevant.append(job)

    yield {"type": "progress", "text": f"✓ Regex pre-filter complete:"}
    yield {"type": "progress", "text": f"  ✗ Rejected: {len(regex_rejected)} ({len(regex_rejected)/total_jobs*100:.1f}%)"}
    yield {"type": "progress", "text": f"  → Sending to Claude: {len(potentially_relevant)} ({len(potentially_relevant)/total_jobs*100:.1f}%)"}

    # Mark regex-rejected jobs as evaluated
    if regex_rejected:
        rejected_ids = [r['job_id'] for r in regex_rejected]
        await jobs_db.mark_jobs_evaluated(rejected_ids)

    # If all rejected by regex, we're done
    if not potentially_relevant:
        yield {"type": "done", "text": f"✓ All {total_jobs} jobs rejected by regex - no API calls needed"}
        return

    # Create Anthropic client
    client = Anthropic(api_key=api_key)

    # Stage 1: Haiku evaluation
    yield {"type": "progress", "text": f"\n{'='*60}"}
    yield {"type": "progress", "text": f"STAGE 1: Evaluating {len(potentially_relevant)} jobs with Haiku"}
    yield {"type": "progress", "text": f"{'='*60}"}

    batches = list(batch_jobs(potentially_relevant, BATCH_SIZE))
    num_batches = len(batches)

    total_accepted = 0
    total_review = 0
    total_rejected = 0
    review_jobs = []

    for i, batch in enumerate(batches, 1):
        yield {"type": "progress", "text": f"\nBatch {i}/{num_batches}: Evaluating {len(batch)} jobs..."}

        # Run Haiku evaluation in thread to avoid blocking
        try:
            results = await asyncio.to_thread(evaluate_batch_with_haiku, batch, client)
        except Exception as e:
            yield {"type": "progress", "text": f"  ✗ Batch failed: {e}"}
            continue

        if not results:
            yield {"type": "progress", "text": f"  ✗ Batch returned no results"}
            continue

        # Process results
        batch_accepted = 0
        batch_review = 0
        batch_rejected = 0
        batch_job_ids = []

        for result in results:
            job_id = result.get('job_id')
            decision = result.get('decision', 'REJECT')
            batch_job_ids.append(job_id)

            # Find original job data
            job = next((j for j in batch if j['id'] == job_id), None)
            if job:
                result['is_intern'] = job.get('is_intern', False)
                result['is_non_us'] = job.get('is_non_us', False)

            if decision == 'ACCEPT':
                batch_accepted += 1
                # Insert into target_jobs
                priority = 3 if result.get('is_non_us') else 1
                experience_info = {
                    "min_years": result.get("min_years"),
                    "max_years": result.get("max_years"),
                    "is_engineering": result.get("is_engineering"),
                }
                await jobs_db.insert_target_job(
                    job_id=job_id,
                    relevance_score=result.get('score', 0.7),
                    match_reason=result.get('reasoning', ''),
                    priority=priority,
                    is_intern=result.get('is_intern', False),
                    experience_analysis=experience_info
                )

            elif decision == 'REVIEW':
                batch_review += 1
                # Store for Stage 2
                if job:
                    review_jobs.append({
                        **job,
                        **result,
                        'job_id': job_id,  # Ensure job_id is set
                    })

            else:  # REJECT
                batch_rejected += 1

        # Mark batch as evaluated
        await jobs_db.mark_jobs_evaluated(batch_job_ids)

        total_accepted += batch_accepted
        total_review += batch_review
        total_rejected += batch_rejected

        yield {"type": "progress", "text": f"  ✓ ACCEPT: {batch_accepted}, REVIEW: {batch_review}, REJECT: {batch_rejected}"}

    yield {"type": "progress", "text": f"\nStage 1 complete: {total_accepted} accepted, {total_review} review, {total_rejected} rejected"}

    # Stage 2: Sonnet review (if needed)
    sonnet_accepted = 0
    sonnet_rejected = 0

    if review_jobs:
        yield {"type": "progress", "text": f"\n{'='*60}"}
        yield {"type": "progress", "text": f"STAGE 2: Reviewing {len(review_jobs)} borderline jobs with Sonnet"}
        yield {"type": "progress", "text": f"{'='*60}"}

        # Load profile
        try:
            with open(PROFILE_PATH, 'r') as f:
                profile = json.load(f)
        except FileNotFoundError:
            yield {"type": "error", "text": f"Profile not found at {PROFILE_PATH}"}
            return

        sonnet_batches = list(batch_jobs(review_jobs, SONNET_BATCH_SIZE))

        for i, batch in enumerate(sonnet_batches, 1):
            yield {"type": "progress", "text": f"\nSonnet batch {i}/{len(sonnet_batches)}: Reviewing {len(batch)} jobs..."}

            try:
                results = await asyncio.to_thread(
                    review_batch_with_sonnet, batch, client, profile
                )
            except Exception as e:
                yield {"type": "progress", "text": f"  ✗ Batch failed: {e}"}
                continue

            if not results:
                yield {"type": "progress", "text": f"  ✗ Batch returned no results"}
                continue

            batch_accepted = 0
            batch_rejected = 0

            for result in results:
                job_id = result.get('job_id')
                decision = result.get('decision', 'REJECT')

                # Find original job data
                job = next((j for j in batch if j.get('job_id') == job_id), None)

                if decision == 'ACCEPT':
                    batch_accepted += 1
                    priority = 3 if (job and job.get('is_non_us')) else 1
                    experience_info = {
                        "min_years": job.get("min_years") if job else None,
                        "max_years": job.get("max_years") if job else None,
                        "is_engineering": job.get("is_engineering", True) if job else True,
                    }
                    await jobs_db.insert_target_job(
                        job_id=job_id,
                        relevance_score=result.get('score', 0.6),
                        match_reason=f"Sonnet: {result.get('reasoning', '')}",
                        priority=priority,
                        is_intern=job.get('is_intern', False) if job else False,
                        experience_analysis=experience_info
                    )
                else:
                    batch_rejected += 1

            sonnet_accepted += batch_accepted
            sonnet_rejected += batch_rejected

            yield {"type": "progress", "text": f"  ✓ ACCEPT: {batch_accepted}, REJECT: {batch_rejected}"}

        yield {"type": "progress", "text": f"\nStage 2 complete: {sonnet_accepted} accepted, {sonnet_rejected} rejected"}

    # Final summary
    final_accepted = total_accepted + sonnet_accepted
    final_rejected = len(regex_rejected) + total_rejected + sonnet_rejected

    yield {"type": "progress", "text": f"\n{'='*60}"}
    yield {"type": "progress", "text": "FILTERING COMPLETE"}
    yield {"type": "progress", "text": f"{'='*60}"}
    yield {"type": "progress", "text": f"Total jobs processed: {total_jobs}"}
    yield {"type": "progress", "text": f"  Regex rejected: {len(regex_rejected)}"}
    yield {"type": "progress", "text": f"  Haiku accepted: {total_accepted}"}
    yield {"type": "progress", "text": f"  Sonnet accepted: {sonnet_accepted}"}
    yield {"type": "progress", "text": f"  Total rejected: {final_rejected}"}

    # Get updated stats
    stats = await jobs_db.get_stats()
    yield {"type": "done", "text": f"\n✓ {final_accepted} jobs added to target_jobs ({stats['pending_jobs']} pending total)"}


async def handle_reset():
    """Handle /filter reset command."""
    import jobs_db

    yield {"type": "progress", "text": "Resetting evaluated flag on all jobs..."}

    await jobs_db.init_jobs_db()
    count = await jobs_db.reset_evaluated()

    yield {"type": "done", "text": f"✓ Reset {count} jobs to unevaluated state"}
