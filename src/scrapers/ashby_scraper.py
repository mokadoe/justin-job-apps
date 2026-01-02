import requests
from typing import List, Dict, Optional
import time

# Handle both relative and absolute imports
try:
    from .slug_resolver import suggest_slugs_batch
except ImportError:
    from slug_resolver import suggest_slugs_batch


def _try_simple_variations(company_name: str) -> List[str]:
    """Generate simple slug variations without AI."""
    variations = [
        company_name.lower().replace(' ', '-'),
        company_name.lower().replace(' ', ''),
        company_name.lower().replace(' ', '-').replace('&', 'and'),
        company_name.lower().replace(' ', '').replace('&', 'and'),
        company_name.lower().replace(' ', '-').replace('.', ''),
    ]
    # Remove duplicates while preserving order
    seen = set()
    unique = []
    for slug in variations:
        if slug and slug not in seen:
            seen.add(slug)
            unique.append(slug)
    return unique


def _fetch_single_company(company_slug: str, base_url: str, params: dict) -> dict:
    """Try fetching jobs for a single company slug."""
    try:
        url = f"{base_url}/{company_slug}"
        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            return {
                'success': True,
                'data': data,
                'job_count': len(data.get('jobs', [])) if isinstance(data, dict) else 0,
                'slug_used': company_slug
            }
        else:
            return {
                'success': False,
                'error': f"HTTP {response.status_code}",
                'status_code': response.status_code
            }
    except requests.exceptions.Timeout:
        return {'success': False, 'error': 'Timeout', 'status_code': 408}
    except requests.exceptions.RequestException as e:
        return {'success': False, 'error': str(e), 'status_code': None}


def fetch_ashby_jobs(company_names: List[str], include_compensation: bool = True, auto_resolve_slugs: bool = True) -> Dict[str, any]:
    """
    Fetch job postings from Ashby ATS for a list of companies.

    Uses batched slug resolution: tries all simple variations first, then makes
    a single Claude Haiku API call for all remaining failures.

    Args:
        company_names: List of company slugs/names
        include_compensation: Whether to include compensation data
        auto_resolve_slugs: If True, use batched AI slug resolution for 404 errors

    Returns:
        Dictionary mapping company names to their job posting data
    """
    results = {}
    base_url = "https://api.ashbyhq.com/posting-api/job-board"
    params = {'includeCompensation': 'true'} if include_compensation else {}

    print(f"Fetching jobs for {len(company_names)} companies...")
    print("="*60)

    # PASS 1: Try original slugs
    print("\n[Pass 1] Trying original company slugs...")
    failed_companies = []

    for company in company_names:
        result = _fetch_single_company(company, base_url, params)

        if result['success']:
            results[company] = result
            print(f"✓ {company}: {result['job_count']} jobs")
        else:
            if result.get('status_code') == 404:
                failed_companies.append(company)
                print(f"✗ {company}: HTTP 404")
            else:
                results[company] = result
                print(f"✗ {company}: {result['error']}")

        time.sleep(0.5)

    if not failed_companies or not auto_resolve_slugs:
        print(f"\n✓ Completed: {len(results)} companies processed")
        return results

    # PASS 2: Try simple variations for failed companies
    print(f"\n[Pass 2] Trying simple variations for {len(failed_companies)} failed companies...")
    still_failed = []

    for company in failed_companies:
        variations = _try_simple_variations(company)
        found = False

        for slug in variations:
            result = _fetch_single_company(slug, base_url, params)

            if result['success']:
                result['slug_resolved'] = True
                result['resolution_method'] = 'simple_variation'
                results[company] = result
                print(f"✓ {company}: {result['job_count']} jobs (resolved to '{slug}')")
                found = True
                break

            time.sleep(0.3)

        if not found:
            still_failed.append(company)

    if not still_failed:
        print(f"\n✓ Completed: All companies resolved with simple variations")
        return results

    # PASS 3: Batch AI resolution for remaining failures
    print(f"\n[Pass 3] Using Claude Haiku for {len(still_failed)} remaining failures...")
    print(f"  → Making single batched API call...")

    ai_suggestions = suggest_slugs_batch(still_failed, max_suggestions_per_company=5)

    for company in still_failed:
        suggestions = ai_suggestions.get(company, [])

        if not suggestions:
            results[company] = {
                'success': False,
                'error': 'HTTP 404 - No AI suggestions available',
                'job_count': 0
            }
            print(f"✗ {company}: No AI suggestions")
            continue

        print(f"  → {company}: trying {len(suggestions)} AI suggestions...")
        found = False

        for slug in suggestions:
            result = _fetch_single_company(slug, base_url, params)

            if result['success']:
                result['slug_resolved'] = True
                result['resolution_method'] = 'ai_batch'
                results[company] = result
                print(f"  ✓ {company}: {result['job_count']} jobs (AI resolved to '{slug}')")
                found = True
                break

            time.sleep(0.3)

        if not found:
            results[company] = {
                'success': False,
                'error': f'HTTP 404 - Tried {len(suggestions)} AI suggestions, none worked',
                'job_count': 0,
                'ai_suggestions_tried': suggestions
            }
            print(f"  ✗ {company}: All AI suggestions failed")

    print(f"\n{'='*60}")
    print(f"✓ Completed: {sum(1 for r in results.values() if r.get('success'))} successful")
    print(f"✗ Failed: {sum(1 for r in results.values() if not r.get('success'))}")

    resolved_count = sum(1 for r in results.values() if r.get('slug_resolved'))
    if resolved_count > 0:
        print(f"🔄 Slug resolutions: {resolved_count}")

    return results


def get_job_summary(results: Dict[str, any]) -> Dict[str, int]:
    """Generate summary statistics from fetch results."""
    total_companies = len(results)
    successful = sum(1 for r in results.values() if r.get('success'))
    failed = total_companies - successful
    total_jobs = sum(r.get('job_count', 0) for r in results.values())

    return {
        'total_companies': total_companies,
        'successful': successful,
        'failed': failed,
        'total_jobs': total_jobs,
        'avg_jobs_per_company': round(total_jobs / successful, 1) if successful > 0 else 0,
        'resolved': sum(1 for r in results.values() if r.get('slug_resolved'))
    }


# Example usage
if __name__ == "__main__":
    # Test with companies that might need slug resolution
    test_companies = [
        'openai',           # Should work
        '1Password',        # Needs simple variation
        'Hims & Hers',      # Needs simple variation
        'A Thinking Ape',   # Might need AI
        'fake-company-xyz'  # Should fail completely
    ]

    print("Testing Batched Ashby Scraper")
    print("="*60)

    results = fetch_ashby_jobs(test_companies, auto_resolve_slugs=True)

    print("\n" + "="*60)
    summary = get_job_summary(results)
    print(f"Summary:")
    print(f"  Companies queried: {summary['total_companies']}")
    print(f"  Successful: {summary['successful']}")
    print(f"  Failed: {summary['failed']}")
    print(f"  Slug resolutions: {summary['resolved']}")
    print(f"  Total jobs found: {summary['total_jobs']}")
    print(f"  Avg jobs/company: {summary['avg_jobs_per_company']}")
