#!/usr/bin/env python3
"""Test the ATS mapper with real Ashby data."""

import sys
from pathlib import Path

# Add src directory to path so we can import modules
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "scrapers"))

import json
from ats_mapper import ATSMapper
from ashby_scraper import fetch_ashby_jobs


def load_company_list(filepath: str) -> list:
    """Load company names from text file."""
    with open(filepath, 'r') as f:
        return [line.strip() for line in f if line.strip()]


def test_ashby_mapping():
    """Test Ashby mapping with multiple companies."""

    print("="*60)
    print("Testing ATS Mapper with Ashby companies")
    print("="*60)

    # Load a sample of companies (file is in data directory)
    companies_file = Path(__file__).parent.parent / "data" / "ashby_companies.txt"
    all_companies = load_company_list(companies_file)

    # Test with first 2 companies
    test_companies = all_companies[:2]

    print(f"\nTesting with {len(test_companies)} companies: {', '.join(test_companies)}\n")

    # Fetch job data
    print("Step 1: Fetching job data from Ashby API...")
    print("-" * 60)
    results = fetch_ashby_jobs(test_companies)

    # Initialize mapper
    mapper = ATSMapper()

    # Verify Ashby mapping exists
    if 'ashbyhq' not in mapper.list_platforms():
        print("\n⚠ No Ashby mapping found. Run ats_mapper.py first to create it.")
        return

    print("\n" + "="*60)
    print("Step 2: Extracting jobs using stored mapping...")
    print("-" * 60)

    all_extracted_jobs = []
    extraction_summary = {
        'successful': 0,
        'failed': 0,
        'total_jobs': 0
    }

    first_company_jobs = None
    first_company_name = None

    for company, result in results.items():
        if not result['success']:
            print(f"✗ {company}: Skipped (API fetch failed)")
            extraction_summary['failed'] += 1
            continue

        try:
            # Extract jobs using mapper
            jobs = mapper.extract_jobs('ashbyhq', result['data'], company)
            all_extracted_jobs.extend(jobs)
            extraction_summary['successful'] += 1
            extraction_summary['total_jobs'] += len(jobs)

            # Store first company's jobs for detailed inspection
            if first_company_jobs is None:
                first_company_jobs = jobs
                first_company_name = company

            print(f"✓ {company}: Extracted {len(jobs)} jobs")

        except Exception as e:
            print(f"✗ {company}: Extraction failed - {str(e)}")
            extraction_summary['failed'] += 1

    # Print summary
    print("\n" + "="*60)
    print("Extraction Summary")
    print("="*60)
    print(f"Companies processed: {extraction_summary['successful'] + extraction_summary['failed']}")
    print(f"Successful extractions: {extraction_summary['successful']}")
    print(f"Failed extractions: {extraction_summary['failed']}")
    print(f"Total jobs extracted: {extraction_summary['total_jobs']}")

    if extraction_summary['successful'] > 0:
        avg_jobs = extraction_summary['total_jobs'] / extraction_summary['successful']
        print(f"Average jobs per company: {avg_jobs:.1f}")

    # Show detailed JSON structure for first company
    if first_company_jobs:
        print("\n" + "="*60)
        print(f"Detailed JSON Structure for {first_company_name} (all jobs)")
        print("="*60)
        for i, job in enumerate(first_company_jobs, 1):
            print(f"\nJob {i}/{len(first_company_jobs)}:")
            print(json.dumps(job, indent=2))

    # Show sample jobs
    if all_extracted_jobs:
        print("\n" + "="*60)
        print("Sample Extracted Jobs (first 3)")
        print("="*60)
        for i, job in enumerate(all_extracted_jobs[:3], 1):
            print(f"\nJob {i}:")
            print(f"  Company: {job.get('company_name')}")
            print(f"  Title: {job.get('job_title')}")
            print(f"  Location: {job.get('location')}")
            print(f"  URL: {job.get('job_url')}")
            print(f"  ATS: {job.get('ats_platform')}")
            # Truncate description if present
            desc = job.get('job_description')
            if desc:
                print(f"  Description: {desc[:100]}..." if len(desc) > 100 else f"  Description: {desc}")

    # Validate required fields
    print("\n" + "="*60)
    print("Validation: Checking required fields")
    print("="*60)

    required_fields = ['job_title', 'job_url', 'company_name', 'ats_platform']
    validation_pass = True

    for job in all_extracted_jobs[:5]:  # Check first 5 jobs
        missing_fields = [field for field in required_fields if not job.get(field)]
        if missing_fields:
            print(f"✗ Job missing fields: {missing_fields}")
            print(f"  Job data: {job}")
            validation_pass = False

    if validation_pass:
        print("✓ All sampled jobs have required fields")

    # Final result
    print("\n" + "="*60)
    if extraction_summary['successful'] > 0 and validation_pass:
        print("✓ TEST PASSED: Mapping works correctly!")
    else:
        print("✗ TEST FAILED: Issues detected")
    print("="*60)

    return all_extracted_jobs


if __name__ == "__main__":
    test_ashby_mapping()
