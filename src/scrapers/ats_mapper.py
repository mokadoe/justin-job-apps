import json
from pathlib import Path
from typing import Dict, List, Any, Optional


class ATSMapper:
    """Maps ATS API responses to our database schema."""

    MAPPINGS_FILE = Path(__file__).parent / "ats_mappings.json"

    # Our target schema fields
    SCHEMA_FIELDS = [
        'job_url',
        'company_name',
        'job_title',
        'job_description',
        'location',
        'ats_platform'
    ]

    def __init__(self):
        """Load existing mappings if they exist."""
        self.mappings = self._load_mappings()

    def _load_mappings(self) -> Dict:
        """Load mappings from JSON file."""
        if self.MAPPINGS_FILE.exists():
            with open(self.MAPPINGS_FILE, 'r') as f:
                return json.load(f)
        return {}

    def _save_mappings(self):
        """Save mappings to JSON file."""
        with open(self.MAPPINGS_FILE, 'w') as f:
            json.dump(self.mappings, indent=2, fp=f)
        print(f"✓ Saved mappings to {self.MAPPINGS_FILE}")

    def create_mapping(self, ats_platform: str, sample_response: Dict,
                      company_name: str, mapping_config: Dict[str, str]):
        """
        Create and store a mapping for an ATS platform.

        Args:
            ats_platform: Name of ATS (e.g., 'ashby', 'greenhouse', 'lever')
            sample_response: Sample API response to validate against
            company_name: Company name from the sample
            mapping_config: Dictionary mapping schema fields to JSON paths
                Example for Ashby:
                {
                    'job_title': 'jobs[].title',
                    'job_url': 'jobs[].jobUrl',
                    'location': 'jobs[].locationName',
                    'job_description': 'jobs[].description',
                }
        """
        # Validate the mapping works
        test_extract = self._extract_with_mapping(sample_response, mapping_config, company_name, ats_platform)

        if not test_extract:
            raise ValueError("Mapping validation failed - couldn't extract any jobs")

        # Store the mapping
        self.mappings[ats_platform] = {
            'platform': ats_platform,
            'mapping': mapping_config,
            'base_url_pattern': f'https://jobs.{ats_platform}.com/{{company}}',
            'validated_with': company_name,
            'sample_job_count': len(test_extract)
        }

        self._save_mappings()
        print(f"✓ Created mapping for {ats_platform}")
        print(f"  Validated with {company_name}: {len(test_extract)} jobs extracted")

    def _get_nested_value(self, data: Any, path: str) -> Any:
        """
        Get value from nested dict/list using dot notation path.

        Examples:
            'jobs[].title' -> data['jobs'][0]['title']
            'postings[].location.name' -> data['postings'][0]['location']['name']
        """
        # Handle array notation
        if '[]' in path:
            parts = path.split('[]', 1)
            base_path = parts[0]
            rest_path = parts[1].lstrip('.')

            # Get the array
            current = data
            if base_path:
                for key in base_path.split('.'):
                    if key:
                        current = current.get(key, {})

            # If it's a list, return list of values from each item
            if isinstance(current, list):
                if rest_path:
                    return [self._get_nested_value(item, rest_path) for item in current]
                return current

            return []

        # Simple dot notation
        current = data
        for key in path.split('.'):
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return None

        return current

    def _extract_with_mapping(self, api_response: Dict, mapping: Dict,
                             company_name: str, ats_platform: str) -> List[Dict]:
        """
        Extract job data using a mapping configuration.

        Returns list of job dictionaries matching our schema.
        """
        jobs = []

        # Find the jobs array path
        jobs_array_path = None
        for field, path in mapping.items():
            if '[]' in path:
                jobs_array_path = path.split('[]')[0]
                break

        if not jobs_array_path:
            # No array notation - single job
            return [self._extract_single_job(api_response, mapping, company_name, ats_platform)]

        # Get the array of jobs
        jobs_data = self._get_nested_value(api_response, jobs_array_path + '[]')

        if not isinstance(jobs_data, list):
            return []

        # Extract each job
        for job_data in jobs_data:
            job = {}

            for schema_field, api_path in mapping.items():
                # Remove the array prefix since we're already in the array
                if '[]' in api_path:
                    field_path = api_path.split('[]', 1)[1].lstrip('.')
                else:
                    field_path = api_path

                value = self._get_nested_value(job_data, field_path) if field_path else job_data
                job[schema_field] = value

            # Add constant fields
            job['company_name'] = company_name
            job['ats_platform'] = ats_platform

            jobs.append(job)

        return jobs

    def _extract_single_job(self, api_response: Dict, mapping: Dict,
                           company_name: str, ats_platform: str) -> Dict:
        """Extract a single job (no array)."""
        job = {}

        for schema_field, api_path in mapping.items():
            job[schema_field] = self._get_nested_value(api_response, api_path)

        job['company_name'] = company_name
        job['ats_platform'] = ats_platform

        return job

    def extract_jobs(self, ats_platform: str, api_response: Dict,
                    company_name: str) -> List[Dict]:
        """
        Extract jobs from API response using stored mapping.

        Args:
            ats_platform: ATS platform name (must have mapping stored)
            api_response: API response data
            company_name: Company name

        Returns:
            List of job dictionaries matching our schema
        """
        if ats_platform not in self.mappings:
            raise ValueError(f"No mapping found for {ats_platform}. Create one first with create_mapping()")

        mapping = self.mappings[ats_platform]['mapping']
        return self._extract_with_mapping(api_response, mapping, company_name, ats_platform)

    def get_mapping(self, ats_platform: str) -> Optional[Dict]:
        """Get stored mapping for an ATS platform."""
        return self.mappings.get(ats_platform)

    def list_platforms(self) -> List[str]:
        """List all platforms with stored mappings."""
        return list(self.mappings.keys())


# Example usage
if __name__ == "__main__":
    import requests

    mapper = ATSMapper()

    # Example: Create Ashby mapping
    print("Fetching sample Ashby data...")
    response = requests.get("https://api.ashbyhq.com/posting-api/job-board/replit?includeCompensation=true")
    sample_data = response.json()

    ashby_mapping = {
        'job_title': 'jobs[].title',
        'job_url': 'jobs[].jobUrl',
        'location': 'jobs[].locationName',
        'job_description': 'jobs[].description',
    }

    mapper.create_mapping('ashbyhq', sample_data, 'replit', ashby_mapping)

    # Test extraction
    print("\nTesting extraction...")
    jobs = mapper.extract_jobs('ashbyhq', sample_data, 'replit')
    print(f"Extracted {len(jobs)} jobs")
    if jobs:
        print("\nSample job:")
        print(json.dumps(jobs[0], indent=2))
