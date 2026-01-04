"""
Jobs command - manage jobs database.

Usage:
    /jobs stats    - Show database statistics
    /jobs pending  - Show pending target jobs
"""

from . import register


@register(
    "jobs",
    description="Manage jobs database",
    usage="/jobs stats | /jobs pending"
)
async def handle_jobs(args: str):
    """Handle /jobs command."""
    parts = args.split()
    action = parts[0].lower() if parts else ""

    if not action:
        yield {"type": "error", "text": "Usage: /jobs stats | /jobs pending"}
        return

    if action == "stats":
        async for event in jobs_stats():
            yield event
    elif action == "pending":
        async for event in jobs_pending():
            yield event
    else:
        yield {"type": "error", "text": f"Unknown action: {action}. Use 'stats' or 'pending'"}


async def jobs_stats():
    """Show database statistics."""
    try:
        import jobs_db

        await jobs_db.init_jobs_db()
        stats = await jobs_db.get_stats()

        # Calculate filtering status
        total_jobs = stats['jobs']
        evaluated = stats.get('evaluated_jobs', 0)
        unevaluated = total_jobs - evaluated

        lines = [
            "Database Statistics:",
            f"  Companies: {stats['companies']}",
            f"  Total Jobs: {total_jobs}",
            "",
            "Filtering Status:",
            f"  Evaluated: {evaluated} ({evaluated/total_jobs*100:.1f}%)" if total_jobs > 0 else "  Evaluated: 0",
            f"  Unevaluated: {unevaluated} ({unevaluated/total_jobs*100:.1f}%)" if total_jobs > 0 else "  Unevaluated: 0",
            "",
            "Target Jobs (passed filter):",
            f"  Total: {stats['target_jobs']}",
            f"  Pending: {stats['pending_jobs']}",
            "",
            f"Contacts: {stats['contacts']}",
        ]

        yield {"type": "done", "text": "\n".join(lines)}

    except Exception as e:
        yield {"type": "error", "text": f"Failed to get stats: {e}"}


async def jobs_pending():
    """Show pending target jobs."""
    try:
        import jobs_db

        pending = await jobs_db.get_pending_target_jobs()

        if not pending:
            yield {"type": "done", "text": "No pending target jobs"}
            return

        lines = [f"Pending Target Jobs ({len(pending)}):"]
        for job in pending[:20]:  # Show first 20
            priority_marker = "!" if job["priority"] == 1 else " "
            lines.append(f"  {priority_marker} [{job['company']}] {job['job_title']}")
            lines.append(f"      Score: {job['relevance_score']:.2f} | {job['location'] or 'No location'}")

        if len(pending) > 20:
            lines.append(f"  ... and {len(pending) - 20} more")

        yield {"type": "done", "text": "\n".join(lines)}

    except Exception as e:
        yield {"type": "error", "text": f"Failed to get pending jobs: {e}"}
