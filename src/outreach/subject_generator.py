#!/usr/bin/env python3
"""Generate catchy email subject lines using Claude API.

This module is intentionally separate for easy prompt tweaking.
Edit the SUBJECT_PROMPT below to adjust subject line generation.
"""

import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


# ============================================================================
# SUBJECT LINE PROMPT - Edit this to tweak subject generation
# ============================================================================

SUBJECT_PROMPT = """Generate a short, catchy email subject line for a job outreach email.

CONTEXT:
Company: {company_name}
Job Title: {job_title}
Job Description (first 500 chars): {job_description}

REQUIREMENTS:
1. Make it intriguing - they should WANT to open this email
2. Reference something specific about the company or role
3. Hint that this isn't a generic mass email
4. Keep it 5-10 words max
5. Don't be clickbait or spammy
6. Don't use ALL CAPS or excessive punctuation
7. Be creative but professional
8. Can be slightly playful/witty if appropriate for the company

EXAMPLES OF GOOD SUBJECTS:
- "Michigan CS grad who automated finding you"
- "Your AI infra role + my job-hunting bot"
- "Built an LLM pipeline to find roles like yours"
- "CS/Chem student who codes and does chemistry"
- "New grad who built a bot to find {company_name}"

EXAMPLES OF BAD SUBJECTS:
- "Job Application" (too generic)
- "AMAZING OPPORTUNITY!!!" (spammy)
- "Please read this" (desperate)
- "New Grad Software Engineer Application" (boring)

Generate ONLY the subject line, nothing else:"""

# ============================================================================


def generate_subject(company_name, job_title, job_description=None):
    """
    Generate a catchy email subject line using Claude.

    Args:
        company_name: Name of the company
        job_title: Title of the job
        job_description: Full job description (will be truncated)

    Returns:
        Subject line string
    """
    # Truncate job description
    job_desc_truncated = ""
    if job_description:
        job_desc_truncated = job_description[:500]

    prompt = SUBJECT_PROMPT.format(
        company_name=company_name,
        job_title=job_title,
        job_description=job_desc_truncated or "Not available"
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=50,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        subject = response.content[0].text.strip()

        # Remove quotes if Claude wrapped it
        if subject.startswith('"') and subject.endswith('"'):
            subject = subject[1:-1]
        if subject.startswith("'") and subject.endswith("'"):
            subject = subject[1:-1]

        return subject

    except Exception as e:
        # Fallback to simple subject
        return f"New grad interested in {job_title} at {company_name}"
