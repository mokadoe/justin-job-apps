# Aggregators

Aggregators discover companies and job URLs from external sources.

## Quick Start: Adding a New Aggregator

### 1. Create the aggregator file

```python
# src/discovery/aggregators/my_aggregator.py

from .types import CompanyLead, JobLead, AggregatorResult
from .utils import detect_ats_from_url, probe_ats_apis

class MyAggregator:
    name = 'my_source'  # Used as discovery_source in DB

    def __init__(self, some_option: int = 10):
        """Optional: accept configuration via constructor."""
        self.some_option = some_option

    def fetch(self) -> AggregatorResult:
        """Fetch companies and job leads. NO database operations here."""
        companies = []
        jobs = []

        # Your scraping/parsing logic...

        return AggregatorResult(companies=companies, jobs=jobs)
```

### 2. Register in run.py

```python
# In run.py, add to _get_aggregators():

def _get_aggregators():
    from .my_aggregator import MyAggregator
    # ...
    return {
        # ...
        'my_source': MyAggregator,
    }

# If your aggregator has constructor options, handle them in run_aggregator():
if name == 'my_source':
    aggregator = aggregator_class(some_option=options.get('some_option', 10))
```

### 3. Run it

```bash
python -m src.discovery.aggregators.run my_source
```

## Types

```python
from .types import CompanyLead, JobLead, AggregatorResult

# A company you discovered
CompanyLead(
    name="Stripe",                    # Required - unique identifier
    website="https://stripe.com",     # Optional
    ats_platform="greenhouse",        # 'ashbyhq', 'greenhouse', 'lever', or 'unknown'
    ats_url="https://boards.greenhouse.io/stripe"  # Optional
)

# A specific job URL (for unsupported ATS only)
JobLead(
    company_name="Stripe",            # Must match a CompanyLead.name
    job_url="https://jobs.stripe.com/..."
)

# What fetch() returns
AggregatorResult(
    companies=[...],  # List of CompanyLead
    jobs=[...]        # List of JobLead (empty if source doesn't have job URLs)
)
```

## Available Utils

```python
from .utils import detect_ats_from_url, probe_ats_apis, extract_clean_website

# Detect ATS from a job/careers URL (fast, no HTTP requests)
platform, ats_url = detect_ats_from_url("https://boards.greenhouse.io/stripe/...")
# -> ('greenhouse', 'https://boards.greenhouse.io/stripe')

# Probe ATS APIs to find a company (slower, makes HTTP requests)
# Use this when you only have company name, no job URL
platform, slug, ats_url = probe_ats_apis("Stripe")
# -> ('greenhouse', 'stripe', 'https://boards.greenhouse.io/stripe')

# Extract clean website from job URL
website = extract_clean_website("https://careers.stripe.com/jobs/123")
# -> 'https://stripe.com'
```

## When to Return JobLeads

Only return `JobLead` objects when:
1. The source provides specific job URLs (not just company info)
2. The company uses an **unsupported ATS** (not Ashby/Greenhouse/Lever)

```python
# In fetch():
platform, ats_url = detect_ats_from_url(job_url)

companies.append(CompanyLead(
    name=company_name,
    ats_platform=platform,
    ats_url=ats_url,
))

# Only queue job URL if ATS is unsupported
if platform not in {'ashbyhq', 'greenhouse', 'lever'}:
    jobs.append(JobLead(company_name, job_url))
```

Sources that **should** return JobLeads:
- `simplify` - has specific job URLs from GitHub README

Sources that **should NOT** return JobLeads:
- `yc` - only has company names/websites
- `a16z` - only has company names
- `manual` - only has company names

## Existing Aggregators

| Aggregator | Source | Returns Jobs | ATS Probing |
|------------|--------|--------------|-------------|
| `simplify` | SimplifyJobs GitHub | Yes | No (URLs have ATS info) |
| `yc` | yc-oss API | No | Optional (`--check N`) |
| `a16z` | a16z.com/investment-list | No | Optional (`--check-ats`) |
| `manual` | data/manual_companies.txt | No | Always |

## CLI Reference

```bash
# List available aggregators
python -m src.discovery.aggregators.run --list

# Run specific aggregator
python -m src.discovery.aggregators.run simplify
python -m src.discovery.aggregators.run yc --check 100
python -m src.discovery.aggregators.run a16z --check-ats
python -m src.discovery.aggregators.run manual --limit 10

# Run all aggregators
python -m src.discovery.aggregators.run --all
```

## What Happens After fetch()

The runner (`run.py`) handles everything:
1. `store_companies()` - Inserts new companies into DB (skips existing)
2. `queue_jobs()` - Queues job URLs for Sonnet analysis

Your aggregator should NOT touch the database directly.

## Supported ATS Platforms

Jobs from these platforms can be scraped automatically via API:
- `ashbyhq` - Ashby
- `greenhouse` - Greenhouse
- `lever` - Lever

All others are marked `unknown` and job URLs go to the analysis queue.
