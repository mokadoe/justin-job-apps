import requests
from typing import List, Dict, Optional
import time
import re
from ats_utils import try_simple_variations


def _is_potentially_relevant(job_title: str) -> bool:
    """
    Quick pre-filter to determine if a job might be relevant for new grads.

    Rejects obvious non-starters (senior, staff, principal, manager, director, VP, etc.)
    to avoid fetching detailed descriptions for clearly irrelevant jobs.

    Returns True if job should get detailed description fetch.
    """
    title_lower = job_title.lower()

    # Reject obvious senior/leadership roles
    reject_keywords = [
        'senior', 'sr.', 'sr ', 'staff', 'principal', 'lead', 'manager',
        'director', 'vp ', 'vice president', 'head of', 'chief',
        'expert', 'architect', 'distinguished', 'fellow',
        'executive', ' ii', ' iii', ' iv',  # Senior levels
    ]

    for keyword in reject_keywords:
        if keyword in title_lower:
            return False

    # Must contain engineering/software related keywords
    engineering_keywords = ['engineer', 'software', 'developer', 'programmer', 'swe']
    has_engineering = any(keyword in title_lower for keyword in engineering_keywords)

    if not has_engineering:
        return False

    # Passed pre-filter
    return True


def _fetch_job_description(company_slug: str, job_id: int) -> Optional[str]:
    """Fetch detailed job description for a single job."""
    try:
        url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs/{job_id}"
        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            data = response.json()
            return data.get('content', None)
        else:
            return None
    except Exception as e:
        return None


def _fetch_single_company(company_slug: str, fetch_descriptions: bool = True) -> dict:
    """
    Try fetching jobs for a single company slug from Greenhouse.

    Args:
        company_slug: Company slug
        fetch_descriptions: If True, fetch detailed descriptions for potentially relevant jobs
    """
    try:
        # Greenhouse API endpoint
        url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs"

        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            data = response.json()
            # Greenhouse returns {'jobs': [...]}
            jobs = data.get('jobs', []) if isinstance(data, dict) else []

            # If fetch_descriptions enabled, get descriptions for potentially relevant jobs
            descriptions_fetched = 0
            if fetch_descriptions and jobs:
                for job in jobs:
                    if _is_potentially_relevant(job.get('title', '')):
                        description = _fetch_job_description(company_slug, job.get('id'))
                        if description:
                            job['content'] = description
                            descriptions_fetched += 1
                        time.sleep(0.3)

            return {
                'success': True,
                'data': data,
                'job_count': len(jobs),
                'descriptions_fetched': descriptions_fetched if fetch_descriptions else 0,
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


def fetch_greenhouse_jobs(company_names: List[str], auto_resolve_slugs: bool = True, fetch_descriptions: bool = True) -> Dict[str, any]:
    """
    Fetch job postings from Greenhouse ATS for a list of companies.

    Args:
        company_names: List of company slugs/names
        auto_resolve_slugs: If True, try simple variations for 404 errors
        fetch_descriptions: If True, fetch detailed descriptions for potentially relevant jobs

    Returns:
        Dictionary mapping company names to their job posting data
    """
    results = {}

    print(f"Fetching Greenhouse jobs for {len(company_names)} companies...")
    print("="*60)

    # PASS 1: Try original slugs
    print("\n[Pass 1] Trying original company slugs...")
    failed_companies = []

    for company in company_names:
        result = _fetch_single_company(company, fetch_descriptions=fetch_descriptions)

        if result['success']:
            results[company] = result
            desc_info = f" ({result.get('descriptions_fetched', 0)} with descriptions)" if fetch_descriptions else ""
            print(f"✓ {company}: {result['job_count']} jobs{desc_info}")
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
    if failed_companies:
        print(f"\n[Pass 2] Trying variations for {len(failed_companies)} companies...")

    for company in failed_companies:
        found = False
        for slug in try_simple_variations(company):
            result = _fetch_single_company(slug, fetch_descriptions=fetch_descriptions)
            if result['success']:
                result['slug_resolved'] = True
                result['resolution_method'] = 'simple_variation'
                results[company] = result
                desc_info = f" ({result.get('descriptions_fetched', 0)} desc)" if fetch_descriptions else ""
                print(f"✓ {company}: {result['job_count']} jobs{desc_info}")
                found = True
                break
            time.sleep(0.3)

        if not found:
            results[company] = {'success': False, 'error': 'HTTP 404', 'job_count': 0}
            print(f"✗ {company}: Not found")

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
    test_companies = ['stripe']  # Test with just 1 company

    print("Testing Greenhouse Scraper (with smart pre-filter)")
    print("="*60)

    results = fetch_greenhouse_jobs(test_companies, auto_resolve_slugs=True, fetch_descriptions=True)

    # Verify smart filter and descriptions
    company = test_companies[0]
    if company in results and results[company]['success']:
        result = results[company]
        total_jobs = result['job_count']
        desc_fetched = result.get('descriptions_fetched', 0)

        print(f"\n✓ Total jobs: {total_jobs}")
        print(f"✓ Descriptions fetched: {desc_fetched} ({desc_fetched/total_jobs*100:.1f}%)")
        print(f"✓ Smart filter saved {total_jobs - desc_fetched} API calls")

        # Check if descriptions are actually populated
        data = result['data']
        jobs_with_content = sum(1 for job in data.get('jobs', []) if job.get('content'))
        print(f"✓ Jobs with content field: {jobs_with_content}")

    print("\n" + "="*60)
    summary = get_job_summary(results)
    print(f"Summary: {summary['total_jobs']} jobs from {summary['successful']} companies")
