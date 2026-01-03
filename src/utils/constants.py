"""Constants for job application pipeline."""

# Job evaluation status
STATUS_NOT_RELEVANT = 0  # Claude evaluated, not relevant
STATUS_PENDING = 1       # Claude evaluated, relevant, needs review
STATUS_REVIEWED = 2      # User reviewed, decided not to apply
STATUS_APPLIED = 3       # Application sent

STATUS_LABELS = {
    0: "Not Relevant",
    1: "Pending",
    2: "Reviewed",
    3: "Applied"
}

# =============================================================================
# Company Size Configuration
# =============================================================================

# Size categories
SIZE_SMALL = "small"
SIZE_MEDIUM = "medium"
SIZE_LARGE = "large"

# -----------------------------------------------------------------------------
# Workflow Selection
# -----------------------------------------------------------------------------
# True = Use LinkedIn/Google search to find company size (uses API quota)
# False = Use job posting count as proxy for company size (free, no API calls)
USE_LINKEDIN_FOR_COMPANY_SIZE = True

# -----------------------------------------------------------------------------
# Workflow 1: LinkedIn Employee Count Method
# -----------------------------------------------------------------------------
# Used when USE_LINKEDIN_FOR_COMPANY_SIZE = True
# Searches Google for LinkedIn company page to get employee count
#
# Thresholds (employee count):
#   small:  < 50 employees
#   medium: 50-500 employees
#   large:  500+ employees
EMPLOYEE_COUNT_THRESHOLDS = {
    SIZE_SMALL: 50,      # < 50 = small
    SIZE_MEDIUM: 500,    # 50-500 = medium, > 500 = large
}

# -----------------------------------------------------------------------------
# Workflow 2: Job Count Proxy Method
# -----------------------------------------------------------------------------
# Used when USE_LINKEDIN_FOR_COMPANY_SIZE = False
# Uses number of job postings as proxy for company size (no API calls)
#
# Thresholds (job posting count):
#   small:  < 5 jobs
#   medium: 5-8 jobs
#   large:  9+ jobs
JOB_COUNT_THRESHOLDS = {
    SIZE_SMALL: 5,       # < 5 = small
    SIZE_MEDIUM: 9,      # 5-8 = medium, >= 9 = large
}

# Targeting strategy by company size
# Maps size -> list of role search groups
CONTACT_TARGETING = {
    SIZE_SMALL: [
        # Target decision makers directly
        ['founder', 'co-founder', 'CEO', 'Chief Executive'],
        ['CTO', 'Chief Technology Officer', 'VP Engineering'],
    ],
    SIZE_MEDIUM: [
        # Target engineering leadership
        ['CTO', 'Chief Technology Officer', 'VP Engineering'],
        ['Engineering Manager', 'Director of Engineering', 'Head of Engineering'],
    ],
    SIZE_LARGE: [
        # Target recruiters
        ['recruiter', 'talent acquisition', 'technical recruiter'],
        ['recruiting manager', 'recruiting lead'],
    ],
}

# Priority role keywords (contacts marked as priority for outreach)
PRIORITY_ROLE_KEYWORDS = [
    # Decision makers (small companies)
    'founder', 'co-founder', 'ceo', 'chief executive',
    'cto', 'chief technology officer',
    # Engineering leadership (medium companies)
    'vp engineering', 'director of engineering', 'head of engineering',
    # Recruiters (large companies)
    'recruiter', 'recruiting', 'talent acquisition',
    'technical recruiter',
]


def get_company_size_from_employees(employee_count):
    """Determine company size category from employee count."""
    if employee_count < EMPLOYEE_COUNT_THRESHOLDS[SIZE_SMALL]:
        return SIZE_SMALL
    elif employee_count < EMPLOYEE_COUNT_THRESHOLDS[SIZE_MEDIUM]:
        return SIZE_MEDIUM
    else:
        return SIZE_LARGE


def get_company_size_from_jobs(job_count):
    """Determine company size category from job count (proxy)."""
    if job_count < JOB_COUNT_THRESHOLDS[SIZE_SMALL]:
        return SIZE_SMALL
    elif job_count < JOB_COUNT_THRESHOLDS[SIZE_MEDIUM]:
        return SIZE_MEDIUM
    else:
        return SIZE_LARGE
