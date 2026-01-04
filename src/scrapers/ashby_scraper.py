import requests
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


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


def fetch_ashby_jobs(
    company_names: List[str],
    include_compensation: bool = True,
    max_workers: int = 10,
    progress_callback=None
) -> Dict[str, any]:
    """
    Fetch job postings from Ashby ATS for a list of companies.

    Uses ThreadPoolExecutor for parallel fetching.

    Args:
        company_names: List of company slugs
        include_compensation: Whether to include compensation data
        max_workers: Max concurrent requests (default 10)
        progress_callback: Optional callback(company, result, completed, total)

    Returns:
        Dictionary mapping company names to their job posting data
    """
    results = {}
    base_url = "https://api.ashbyhq.com/posting-api/job-board"
    params = {'includeCompensation': 'true'} if include_compensation else {}

    total = len(company_names)
    completed = 0
    lock = threading.Lock()

    # Only print if no callback (avoid duplicate output)
    verbose = progress_callback is None
    if verbose:
        print(f"Fetching jobs for {total} companies (max {max_workers} concurrent)...")
        print("=" * 60)

    def fetch_and_track(company: str) -> tuple[str, dict]:
        """Fetch a single company and return (company, result)."""
        result = _fetch_single_company(company, base_url, params)
        return company, result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(fetch_and_track, company): company
            for company in company_names
        }

        for future in as_completed(futures):
            company, result = future.result()

            with lock:
                results[company] = result
                completed += 1

                # Callback for streaming progress (preferred)
                if progress_callback:
                    progress_callback(company, result, completed, total)
                elif verbose:
                    # Fallback: print to stdout
                    if result['success']:
                        print(f"[{completed}/{total}] ✓ {company}: {result['job_count']} jobs")
                    else:
                        print(f"[{completed}/{total}] ✗ {company}: {result['error']}")

    # Summary (only if verbose)
    if verbose:
        successful = sum(1 for r in results.values() if r.get('success'))
        failed = total - successful
        total_jobs = sum(r.get('job_count', 0) for r in results.values())

        print(f"\n{'=' * 60}")
        print(f"✓ Completed: {successful}/{total} companies successful")
        print(f"✗ Failed: {failed}")
        print(f"📋 Total jobs found: {total_jobs}")

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
    test_companies = [
        'openai',
        'ramp',
        'anthropic',
        'cohere',
        'fake-company-xyz'  # Should fail
    ]

    print("Testing Parallel Ashby Scraper")
    print("=" * 60)

    results = fetch_ashby_jobs(test_companies, max_workers=5)

    print("\n" + "=" * 60)
    summary = get_job_summary(results)
    print(f"Summary:")
    print(f"  Companies queried: {summary['total_companies']}")
    print(f"  Successful: {summary['successful']}")
    print(f"  Failed: {summary['failed']}")
    print(f"  Total jobs found: {summary['total_jobs']}")
    print(f"  Avg jobs/company: {summary['avg_jobs_per_company']}")
