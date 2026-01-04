import requests
from typing import List, Dict, Optional
import time
from ats_utils import try_simple_variations


def _fetch_single_company(company_slug: str) -> dict:
    """Try fetching jobs for a single company slug from Lever."""
    try:
        # Lever API endpoint
        url = f"https://api.lever.co/v0/postings/{company_slug}"
        params = {'mode': 'json'}

        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            # Lever returns a list of jobs directly
            return {
                'success': True,
                'data': data,
                'job_count': len(data) if isinstance(data, list) else 0,
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


def fetch_lever_jobs(company_names: List[str], auto_resolve_slugs: bool = True) -> Dict[str, any]:
    """
    Fetch job postings from Lever ATS for a list of companies.

    Args:
        company_names: List of company slugs/names
        auto_resolve_slugs: If True, try simple variations for 404 errors

    Returns:
        Dictionary mapping company names to their job posting data
    """
    results = {}

    print(f"Fetching Lever jobs for {len(company_names)} companies...")
    print("="*60)

    # PASS 1: Try original slugs
    print("\n[Pass 1] Trying original company slugs...")
    failed_companies = []

    for company in company_names:
        result = _fetch_single_company(company)

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
    if failed_companies:
        print(f"\n[Pass 2] Trying variations for {len(failed_companies)} companies...")

    for company in failed_companies:
        found = False
        for slug in try_simple_variations(company):
            result = _fetch_single_company(slug)
            if result['success']:
                result['slug_resolved'] = True
                result['resolution_method'] = 'simple_variation'
                results[company] = result
                print(f"✓ {company}: {result['job_count']} jobs")
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
    test_companies = ['nordsec']  # Test with just 1 company

    print("Testing Lever Scraper")
    print("="*60)

    results = fetch_lever_jobs(test_companies, auto_resolve_slugs=True)

    # Verify descriptions
    company = test_companies[0]
    if company in results and results[company]['success']:
        data = results[company]['data']
        print(f"\n✓ Fetched {len(data)} jobs")

        if data and len(data) > 0:
            job = data[0]
            has_desc = 'descriptionPlain' in job and job['descriptionPlain']
            print(f"✓ Has descriptions: {has_desc}")
            if has_desc:
                print(f"  Sample description length: {len(job['descriptionPlain'])} chars")

    print("\n" + "="*60)
    summary = get_job_summary(results)
    print(f"Summary: {summary['total_jobs']} jobs from {summary['successful']} companies")
