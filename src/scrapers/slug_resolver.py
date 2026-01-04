#!/usr/bin/env python3
"""
Ashby slug resolver using Claude Haiku.

When a company slug fails (404), this module uses Claude Haiku (cheap model)
to suggest possible slug variations and tries them automatically.
"""

import os
import sys
import requests
from anthropic import Anthropic
from typing import List, Optional
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Cost tracking (optional)
try:
    from utils.cost_tracker import track_api_call
except ImportError:
    # If cost_tracker doesn't exist, use a no-op function
    def track_api_call(*args, **kwargs):
        pass


def suggest_slugs_batch(company_names: List[str], max_suggestions_per_company: int = 5) -> dict:
    """
    Use Claude Haiku to suggest possible Ashby slugs for multiple companies in one API call.

    Args:
        company_names: List of company names that failed
        max_suggestions_per_company: Maximum number of slug suggestions per company

    Returns:
        Dictionary mapping company name to list of suggested slugs
        Example: {"A Thinking Ape": ["a-thinking-ape", "athinkingape"], ...}
    """
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        print("⚠ Warning: ANTHROPIC_API_KEY not found, skipping slug suggestions")
        return {name: [] for name in company_names}

    client = Anthropic(api_key=api_key)

    # Build batch prompt
    companies_list = "\n".join([f"{i+1}. {name}" for i, name in enumerate(company_names)])

    prompt = f"""Given these company names, suggest {max_suggestions_per_company} possible URL slugs for each that might be used in Ashby's job board API.

Companies:
{companies_list}

Common slug patterns:
- Lowercase, hyphens for spaces: "A Thinking Ape" → "a-thinking-ape"
- Remove special characters: "1Password" → "1password" or "onepassword"
- Common abbreviations: "International Business Machines" → "ibm"
- Brand names: "Hims & Hers" → "hims-and-hers" or "himsandhers"
- Domain names without TLD: "stripe.com" → "stripe"

Respond with ONLY a JSON object mapping company names to arrays of {max_suggestions_per_company} slug suggestions (most likely first).
Example format:
{{
  "Company Name 1": ["slug1", "slug2", "slug3"],
  "Company Name 2": ["slug1", "slug2", "slug3"]
}}

Do not include explanations, just the JSON object."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",  # Latest Haiku model
            max_tokens=500 + (len(company_names) * 50),  # Scale with batch size
            messages=[{"role": "user", "content": prompt}]
        )

        # Extract suggestions from response
        content = response.content[0].text.strip()

        # Try to parse as JSON
        import json
        try:
            suggestions = json.loads(content)
            if isinstance(suggestions, dict):
                # Ensure all requested companies have entries
                return {name: suggestions.get(name, []) for name in company_names}
        except json.JSONDecodeError:
            pass

        # Fallback: return empty lists
        print(f"⚠ Could not parse Claude response as JSON")
        return {name: [] for name in company_names}

    except Exception as e:
        print(f"⚠ Error getting batch slug suggestions: {e}")
        return {name: [] for name in company_names}


def suggest_slugs(company_name: str, max_suggestions: int = 5) -> List[str]:
    """
    Use Claude Haiku to suggest possible Ashby slugs for a single company.
    (Wrapper around batch function for backward compatibility)

    Args:
        company_name: The company name that failed
        max_suggestions: Maximum number of slug suggestions to return

    Returns:
        List of suggested slugs to try
    """
    batch_result = suggest_slugs_batch([company_name], max_suggestions)
    return batch_result.get(company_name, [])


def try_slug_variations(company_name: str, base_url: str = "https://api.ashbyhq.com/posting-api/job-board") -> Optional[str]:
    """
    Try multiple slug variations for a company name.

    First tries simple transformations, then uses Claude Haiku for suggestions.

    Args:
        company_name: The company name (e.g., "A Thinking Ape")
        base_url: The Ashby API base URL

    Returns:
        The working slug if found, None otherwise
    """
    # Simple transformations to try first (free)
    simple_variations = [
        company_name.lower().replace(' ', '-'),  # "A Thinking Ape" → "a-thinking-ape"
        company_name.lower().replace(' ', ''),   # "A Thinking Ape" → "athinkingape"
        company_name.lower().replace(' ', '-').replace('&', 'and'),  # Handle ampersands
        company_name.lower().replace(' ', '').replace('&', 'and'),
        company_name.lower().replace(' ', '-').replace('.', ''),  # Remove dots
    ]

    # Remove duplicates while preserving order
    seen = set()
    unique_variations = []
    for slug in simple_variations:
        if slug not in seen and slug:
            seen.add(slug)
            unique_variations.append(slug)

    print(f"  → Trying {len(unique_variations)} simple variations...")

    # Try simple variations first
    for slug in unique_variations:
        try:
            url = f"{base_url}/{slug}"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                print(f"  ✓ Found working slug: {slug}")
                return slug
        except:
            continue

    # If simple variations failed, use Claude Haiku
    print(f"  → Simple variations failed, asking Claude Haiku for suggestions...")

    ai_suggestions = suggest_slugs(company_name)

    if not ai_suggestions:
        print(f"  ✗ No AI suggestions available")
        return None

    print(f"  → Claude Haiku suggested: {', '.join(ai_suggestions)}")

    # Try AI suggestions
    for slug in ai_suggestions:
        # Skip if we already tried this in simple variations
        if slug in seen:
            continue

        try:
            url = f"{base_url}/{slug}"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                print(f"  ✓ Found working slug: {slug}")
                return slug
        except:
            continue

    print(f"  ✗ All variations failed for {company_name}")
    return None


# Test if run directly
if __name__ == "__main__":
    # Test with some tricky company names
    test_companies = [
        "1Password",
        "A Thinking Ape",
        "Hims & Hers",
        "7shifts",
        "Warner Bros.",
    ]

    print("Testing Slug Resolver")
    print("=" * 60)

    for company in test_companies:
        print(f"\n{company}:")
        slug = try_slug_variations(company)
        if slug:
            print(f"  ✅ SUCCESS: {slug}")
        else:
            print(f"  ❌ FAILED: Could not find working slug")
