import requests
from typing import List, Dict, Optional
import time


def fetch_ashby_jobs(company_names: List[str], include_compensation: bool = True) -> Dict[str, any]:
    """
    Fetch job postings from Ashby ATS for a list of companies.

    Args:
        company_names: List of company slugs (e.g., ['openai', 'deel', 'ramp'])
        include_compensation: Whether to include compensation data in response

    Returns:
        Dictionary mapping company names to their job posting data:
        {
            'openai': {'success': True, 'data': {...}, 'job_count': 10},
            'deel': {'success': False, 'error': 'Not found'},
            ...
        }
    """
    results = {}
    base_url = "https://api.ashbyhq.com/posting-api/job-board"

    for company in company_names:
        try:
            # Build URL with optional compensation parameter
            url = f"{base_url}/{company}"
            params = {'includeCompensation': 'true'} if include_compensation else {}

            # Make request
            response = requests.get(url, params=params, timeout=10)

            # Check if successful
            if response.status_code == 200:
                data = response.json()
                results[company] = {
                    'success': True,
                    'data': data,
                    'job_count': len(data.get('jobs', [])) if isinstance(data, dict) else 0
                }
                print(f"✓ {company}: {results[company]['job_count']} jobs")
            else:
                results[company] = {
                    'success': False,
                    'error': f"HTTP {response.status_code}",
                    'job_count': 0
                }
                print(f"✗ {company}: HTTP {response.status_code}")

        except requests.exceptions.Timeout:
            results[company] = {
                'success': False,
                'error': 'Request timeout',
                'job_count': 0
            }
            print(f"✗ {company}: Timeout")

        except requests.exceptions.RequestException as e:
            results[company] = {
                'success': False,
                'error': str(e),
                'job_count': 0
            }
            print(f"✗ {company}: {str(e)}")

        # Be respectful - small delay between requests
        time.sleep(0.5)

    return results


def get_job_summary(results: Dict[str, any]) -> Dict[str, int]:
    """
    Generate summary statistics from fetch results.

    Args:
        results: Output from fetch_ashby_jobs()

    Returns:
        Dictionary with summary stats
    """
    total_companies = len(results)
    successful = sum(1 for r in results.values() if r['success'])
    failed = total_companies - successful
    total_jobs = sum(r['job_count'] for r in results.values())

    return {
        'total_companies': total_companies,
        'successful': successful,
        'failed': failed,
        'total_jobs': total_jobs,
        'avg_jobs_per_company': round(total_jobs / successful, 1) if successful > 0 else 0
    }


# Example usage
if __name__ == "__main__":
    # Test with a few companies
    test_companies = ['openai', 'deel', 'ramp', 'supabase', 'replit']

    print("Fetching job data from Ashby...\n")
    results = fetch_ashby_jobs(test_companies)

    print("\n" + "="*50)
    summary = get_job_summary(results)
    print(f"Summary:")
    print(f"  Companies queried: {summary['total_companies']}")
    print(f"  Successful: {summary['successful']}")
    print(f"  Failed: {summary['failed']}")
    print(f"  Total jobs found: {summary['total_jobs']}")
    print(f"  Avg jobs/company: {summary['avg_jobs_per_company']}")
