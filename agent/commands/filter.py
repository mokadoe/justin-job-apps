"""
Filter command - AI-powered job filtering for new grad relevance.

Usage:
    /filter              - Filter all unevaluated jobs
    /filter 100          - Filter up to 100 jobs (for testing)
    /filter reset        - Reset evaluated flag on all jobs (re-filter)

Two-stage filtering:
    Stage 0: Regex pre-filter (fast, free)
    Stage 1: Haiku batch evaluation (cheap, parallel)
    Stage 2: Sonnet review for borderline cases (expensive, parallel with profile context)
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Callable, Any

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

# Concurrency limits (respect API rate limits)
MAX_HAIKU_CONCURRENT = 5   # Haiku is fast/cheap, can run more
MAX_SONNET_CONCURRENT = 5  # Sonnet is slow/expensive, be conservative


async def run_parallel_batches(
    batches: list,
    process_fn: Callable,
    max_concurrent: int,
    client: Anthropic,
    *args
):
    """
    Run batches in parallel with semaphore-controlled concurrency.

    Yields (batch_num, batch, result, error) tuples as each batch completes.
    Results may arrive out of order due to parallel execution.
    """
    sem = asyncio.Semaphore(max_concurrent)

    async def process_one(batch_num: int, batch: list):
        async with sem:
            try:
                result = await asyncio.to_thread(process_fn, batch, client, *args)
                return batch_num, batch, result, None
            except Exception as e:
                return batch_num, batch, None, e

    # Create all tasks
    tasks = [
        asyncio.create_task(process_one(i, batch))
        for i, batch in enumerate(batches)
    ]

    # Yield results as they complete (may be out of order)
    for coro in asyncio.as_completed(tasks):
        yield await coro


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

    # Check for pending review jobs from previous crashed run (status=0)
    pending_reviews = await jobs_db.get_pending_review_jobs()
    if pending_reviews:
        yield {"type": "progress", "text": f"Found {len(pending_reviews)} pending review jobs from previous run"}
        yield {"type": "progress", "text": "  → Will skip directly to Stage 2 (Sonnet) for these"}

    # Get unevaluated jobs
    yield {"type": "progress", "text": "Fetching unevaluated jobs..."}
    jobs = await jobs_db.get_unevaluated_jobs(limit=limit)

    if not jobs and not pending_reviews:
        yield {"type": "done", "text": "✓ No unevaluated jobs found - all jobs have been evaluated"}
        return

    total_jobs = len(jobs) if jobs else 0
    if total_jobs > 0:
        yield {"type": "progress", "text": f"Found {total_jobs} new jobs to filter"}

    # Initialize counters
    regex_rejected = []
    total_accepted = 0
    total_review = 0
    total_rejected = 0
    review_jobs = list(pending_reviews)  # Start with pending reviews from DB

    # Create Anthropic client (needed for both stages)
    client = Anthropic(api_key=api_key)

    # Only run Stage 0/1 if there are new unevaluated jobs
    if jobs:
        # Stage 0: Regex pre-filter
        yield {"type": "progress", "text": f"\n{'='*60}"}
        yield {"type": "progress", "text": "STAGE 0: Pre-filtering with regex..."}
        yield {"type": "progress", "text": f"{'='*60}"}

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

        # Stage 1: Haiku evaluation (if any passed regex)
        if potentially_relevant:
            yield {"type": "progress", "text": f"\n{'='*60}"}
            yield {"type": "progress", "text": f"STAGE 1: Evaluating {len(potentially_relevant)} jobs with Haiku"}
            yield {"type": "progress", "text": f"  (parallel: {MAX_HAIKU_CONCURRENT} concurrent batches)"}
            yield {"type": "progress", "text": f"{'='*60}"}

            batches = list(batch_jobs(potentially_relevant, BATCH_SIZE))
            num_batches = len(batches)
            completed_batches = 0

            haiku_start = time.time()

            async for batch_num, batch, results, error in run_parallel_batches(
                batches, evaluate_batch_with_haiku, MAX_HAIKU_CONCURRENT, client
            ):
                completed_batches += 1

                if error:
                    yield {"type": "progress", "text": f"  ✗ Batch {batch_num+1}/{num_batches} failed: {error}"}
                    continue

                if not results:
                    yield {"type": "progress", "text": f"  ✗ Batch {batch_num+1}/{num_batches} returned no results"}
                    continue

                # Process results
                batch_accepted = 0
                batch_review = 0
                batch_rejected = 0
                evaluated_job_ids = []

                for result in results:
                    job_id = result.get('job_id')
                    decision = result.get('decision', 'REJECT')

                    # Find original job data
                    job = next((j for j in batch if j['id'] == job_id), None)
                    if job:
                        result['is_intern'] = job.get('is_intern', False)
                        result['is_non_us'] = job.get('is_non_us', False)

                    priority = 3 if result.get('is_non_us') else 1
                    experience_info = {
                        "min_years": result.get("min_years"),
                        "max_years": result.get("max_years"),
                        "is_engineering": result.get("is_engineering"),
                    }

                    if decision == 'ACCEPT':
                        batch_accepted += 1
                        evaluated_job_ids.append(job_id)
                        # Insert into target_jobs with status=1 (pending)
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
                        evaluated_job_ids.append(job_id)  # Mark as evaluated NOW
                        # Insert into target_jobs with status=0 (pending review)
                        await jobs_db.insert_review_job(
                            job_id=job_id,
                            relevance_score=result.get('score', 0.5),
                            match_reason=result.get('reasoning', ''),
                            priority=priority,
                            is_intern=result.get('is_intern', False),
                            experience_analysis=experience_info
                        )
                        # Add to review_jobs for Stage 2 in this run
                        if job:
                            review_jobs.append({
                                **job,
                                **result,
                                'job_id': job_id,
                            })

                    else:  # REJECT
                        batch_rejected += 1
                        evaluated_job_ids.append(job_id)

                # Mark all processed jobs as evaluated
                await jobs_db.mark_jobs_evaluated(evaluated_job_ids)

                total_accepted += batch_accepted
                total_review += batch_review
                total_rejected += batch_rejected

                yield {"type": "progress", "text": f"  ✓ [{completed_batches}/{num_batches}] Batch {batch_num+1}: ACCEPT: {batch_accepted}, REVIEW: {batch_review}, REJECT: {batch_rejected}"}

            haiku_elapsed = time.time() - haiku_start
            yield {"type": "progress", "text": f"\nStage 1 complete in {haiku_elapsed:.1f}s: {total_accepted} accepted, {total_review} review, {total_rejected} rejected"}

    # Stage 2: Sonnet review (if needed, parallel)
    sonnet_accepted = 0
    sonnet_rejected = 0

    if review_jobs:
        yield {"type": "progress", "text": f"\n{'='*60}"}
        yield {"type": "progress", "text": f"STAGE 2: Reviewing {len(review_jobs)} borderline jobs with Sonnet"}
        yield {"type": "progress", "text": f"  (parallel: {MAX_SONNET_CONCURRENT} concurrent batches)"}
        yield {"type": "progress", "text": f"{'='*60}"}

        # Load profile
        try:
            with open(PROFILE_PATH, 'r') as f:
                profile = json.load(f)
        except FileNotFoundError:
            yield {"type": "error", "text": f"Profile not found at {PROFILE_PATH}"}
            return

        sonnet_batches = list(batch_jobs(review_jobs, SONNET_BATCH_SIZE))
        num_sonnet_batches = len(sonnet_batches)
        completed_sonnet = 0

        sonnet_start = time.time()

        async for batch_num, batch, results, error in run_parallel_batches(
            sonnet_batches, review_batch_with_sonnet, MAX_SONNET_CONCURRENT, client, profile
        ):
            completed_sonnet += 1

            if error:
                yield {"type": "progress", "text": f"  ✗ Batch {batch_num+1}/{num_sonnet_batches} failed: {error}"}
                continue

            if not results:
                yield {"type": "progress", "text": f"  ✗ Batch {batch_num+1}/{num_sonnet_batches} returned no results"}
                continue

            batch_accepted = 0
            batch_rejected = 0

            for result in results:
                job_id = result.get('job_id')
                decision = result.get('decision', 'REJECT')

                if decision == 'ACCEPT':
                    batch_accepted += 1
                    # Update status from 0 (pending_review) to 1 (pending)
                    await jobs_db.finalize_review_job(
                        job_id=job_id,
                        accept=True,
                        new_score=result.get('score', 0.6),
                        new_reason=f"Sonnet: {result.get('reasoning', '')}"
                    )
                else:
                    batch_rejected += 1
                    # Delete from target_jobs (rejected)
                    await jobs_db.finalize_review_job(job_id=job_id, accept=False)

            sonnet_accepted += batch_accepted
            sonnet_rejected += batch_rejected

            yield {"type": "progress", "text": f"  ✓ [{completed_sonnet}/{num_sonnet_batches}] Batch {batch_num+1}: ACCEPT: {batch_accepted}, REJECT: {batch_rejected}"}

        sonnet_elapsed = time.time() - sonnet_start
        yield {"type": "progress", "text": f"\nStage 2 complete in {sonnet_elapsed:.1f}s: {sonnet_accepted} accepted, {sonnet_rejected} rejected"}

    # Final summary
    final_accepted = total_accepted + sonnet_accepted
    final_rejected = len(regex_rejected) + total_rejected + sonnet_rejected

    yield {"type": "progress", "text": f"\n{'='*60}"}
    yield {"type": "progress", "text": "FILTERING COMPLETE"}
    yield {"type": "progress", "text": f"{'='*60}"}
    yield {"type": "progress", "text": f"Total new jobs processed: {total_jobs}"}
    yield {"type": "progress", "text": f"  Regex rejected: {len(regex_rejected)}"}
    yield {"type": "progress", "text": f"  Haiku accepted: {total_accepted}"}
    if pending_reviews:
        yield {"type": "progress", "text": f"  Pending reviews (from crash): {len(pending_reviews)}"}
    yield {"type": "progress", "text": f"  Sonnet accepted: {sonnet_accepted}"}
    yield {"type": "progress", "text": f"  Total rejected: {final_rejected}"}

    # Get updated stats
    stats = await jobs_db.get_stats()
    yield {"type": "done", "text": f"\n✓ {final_accepted} jobs added to target_jobs ({stats['pending_jobs']} pending total)"}


async def handle_reset():
    """Handle /filter reset command - clean slate for re-filtering."""
    import jobs_db

    await jobs_db.init_jobs_db()

    yield {"type": "progress", "text": "Clearing target_jobs table..."}
    targets_cleared = await jobs_db.clear_target_jobs()

    yield {"type": "progress", "text": "Resetting evaluated flag on all jobs..."}
    jobs_reset = await jobs_db.reset_evaluated()

    yield {"type": "done", "text": f"✓ Reset complete: {jobs_reset} jobs unevaluated, {targets_cleared} target_jobs cleared"}
