"""
Aggregator type definitions.

All aggregators return AggregatorResult containing CompanyLead and JobLead objects.
"""

from dataclasses import dataclass, field


@dataclass
class CompanyLead:
    """
    A company discovered by an aggregator.

    Attributes:
        name: Company name (required, used as unique identifier)
        website: Company website URL (optional)
        ats_platform: ATS platform - 'ashbyhq', 'greenhouse', 'lever', or 'unknown'
        ats_url: Full URL to company's job board on the ATS
    """
    name: str
    website: str | None = None
    ats_platform: str = 'unknown'
    ats_url: str | None = None


@dataclass
class JobLead:
    """
    A specific job URL for unsupported ATS platforms.

    When a company uses an unsupported ATS (Workday, iCIMS, etc.),
    we queue the specific job URL for Sonnet analysis instead of
    scraping via API.

    Attributes:
        company_name: Name of the company (for linking after DB insert)
        job_url: Direct URL to the job posting
    """
    company_name: str
    job_url: str


@dataclass
class AggregatorResult:
    """
    Result returned by aggregator.fetch().

    Attributes:
        companies: List of discovered companies
        jobs: List of job URLs for unsupported ATS (can be empty)
    """
    companies: list[CompanyLead] = field(default_factory=list)
    jobs: list[JobLead] = field(default_factory=list)
