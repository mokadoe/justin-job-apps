# Scraping Improvements Feature Spec

> **Purpose:** Address critical gaps in job data collection that limit pipeline effectiveness.
> **Priority:** High - These issues significantly reduce both quantity and quality of job matches.
> **Created:** 2026-01-02

---

## Executive Summary

Analysis of the current database (7,118 jobs from 304 companies) revealed four critical issues:

| Issue | Impact | Estimated Opportunity Loss |
|-------|--------|---------------------------|
| Single ATS source | Missing 80%+ of job market | ~5,000-10,000 jobs |
| No job descriptions | Filter accuracy ~50% | ~50+ missed matches |
| No posting dates | Stale job outreach | ~30% wasted effort |
| Title-only filtering | Systematic false negatives | ~100+ missed matches |

### Justin's Competitive Advantage: Chemistry + CS

Justin's **CS + Chemistry** background (UMich, May 2026) combined with **ML experience in drug discovery** opens a **differentiated channel**:

- **Computational chemistry** - Most CS grads can't compete here
- **Drug discovery ML** - Direct experience from Cove.ai
- **Biotech startups** - High demand for CS + life sciences combo
- **Materials science** - Battery tech, molecular modeling

**This spec expands Issue #1 to capture this underserved market segment.**

---

## Issue #1: Single ATS Source (Ashby Only)

### Problem Statement

The current scraper only collects jobs from Ashby HQ (`jobs.ashbyhq.com`). This creates a massive blind spot because startups use many different Applicant Tracking Systems.

### Evidence from Data Analysis

```sql
-- Current ATS distribution
SELECT ats_platform, COUNT(*) as companies FROM companies GROUP BY ats_platform;

-- Result:
-- ashbyhq | 304
-- (no other platforms)
```

**100% of 304 companies and 7,118 jobs come from a single ATS platform.**

### Market Reality

Estimated ATS market share among VC-backed startups:

| ATS Platform | Est. Market Share | Current Coverage |
|--------------|-------------------|------------------|
| Greenhouse | 35-40% | 0% |
| Lever | 25-30% | 0% |
| Ashby | 15-20% | 100% |
| Workday | 10-15% | 0% |
| Workable | 5-10% | 0% |
| Other (BambooHR, JazzHR, etc.) | 5-10% | 0% |

**Implication:** We're capturing roughly 15-20% of the addressable job market.

### Case Study: OpenAI

OpenAI has 448 jobs in our database (all from Ashby), but **zero new grad roles**. However, OpenAI is known to hire new grads. Their careers page (https://openai.com/careers) likely has roles posted through a different system or direct application that we're not capturing.

### Proposed Solution

#### 1.1 Add Lever Scraper

**Target:** `jobs.lever.co/{company-name}`

**URL Pattern:**
```
https://jobs.lever.co/{company-slug}
https://jobs.lever.co/{company-slug}/{job-id}
```

**Data Available:**
- Job title
- Location
- Team/department
- Commitment type (Full-time, Part-time, Intern)
- Job description (full HTML)
- Posted date (often in metadata)

**Example Companies on Lever:**
- Figma: `jobs.lever.co/figma`
- Notion: `jobs.lever.co/notion`
- Stripe: Listed on Lever historically

**Implementation Notes:**
- Lever provides JSON API at `jobs.lever.co/{company}/`
- Returns structured data including posting date
- Rate limiting: ~1 request/second recommended

#### 1.2 Add Greenhouse Scraper

**Target:** `boards.greenhouse.io/{company-name}`

**URL Pattern:**
```
https://boards.greenhouse.io/{company-slug}
https://boards.greenhouse.io/{company-slug}/jobs/{job-id}
```

**Data Available:**
- Job title
- Location (often structured)
- Department
- Job description (full HTML)
- Application form fields (useful for knowing requirements)

**Example Companies on Greenhouse:**
- Airbnb: `boards.greenhouse.io/airbnb`
- Discord: `boards.greenhouse.io/discord`
- Coinbase: `boards.greenhouse.io/coinbase`

**Implementation Notes:**
- Greenhouse has an embed API that returns JSON
- URL pattern: `boards-api.greenhouse.io/v1/boards/{company}/jobs`
- May require parsing HTML for some fields

#### 1.3 Company Discovery for New Platforms

**Problem:** We need a list of company slugs for Lever and Greenhouse.

**Approach 1: Cross-reference existing Ashby companies**
```python
# For each company in our DB, check if they also have Lever/Greenhouse
for company in companies:
    lever_url = f"https://jobs.lever.co/{company.name.lower().replace(' ', '')}"
    greenhouse_url = f"https://boards.greenhouse.io/{company.name.lower().replace(' ', '')}"
    # Check if 200 response
```

**Approach 2: Curated high-priority list**
- Start with YC companies list (publicly available)
- Add known AI/ML startups from our research
- Expand based on funding announcements

**Approach 3: Simplify Jobs integration**
- We already have `src/scrapers/simplify_scraper.py`
- Simplify aggregates jobs from multiple ATS platforms
- Could use this as a discovery source for companies on other platforms

---

### 1.4 Biotech/Pharma/Computational Chemistry Sector

#### Justin's Unique Advantage

Justin's **CS + Chemistry** background is rare and highly valued in:
- Computational chemistry / molecular modeling
- Drug discovery / pharmaceutical R&D
- Materials science / battery tech
- Biotech startups using ML for biology
- Cheminformatics and QSAR modeling

**His gradient boosting work for drug discovery at Cove.ai directly translates to this sector.**

This is a **differentiated channel** - most CS grads can't compete here, but Justin can.

#### 1.4.1 Biotech/Life Sciences Job Boards

| Platform | URL | Focus | New Grad Friendly |
|----------|-----|-------|-------------------|
| **BioSpace** | biospace.com/jobs | Biotech & pharma | Yes - has entry-level filter |
| **Science Careers (AAAS)** | sciencecareers.org | Academic + industry | Yes |
| **Nature Careers** | nature.com/naturecareers | Research + biotech | Yes |
| **LinkedIn Life Sciences** | linkedin.com/jobs (filtered) | All life sciences | Yes |
| **Glassdoor** | glassdoor.com | General + biotech | Yes |
| **Indeed** | indeed.com | General aggregator | Yes |
| **BioTechne Careers** | careers.bio-techne.com | Biotech specific | Yes |
| **Labcorp Careers** | careers.labcorp.com | Lab/clinical | Yes |

**Implementation: BioSpace Scraper**

```python
# BioSpace has structured job listings
# URL: https://www.biospace.com/jobs/?keywords=computational+chemistry&location=&industry=&jobType=

BASE_URL = "https://www.biospace.com/api/jobs"
PARAMS = {
    "keywords": "computational chemistry OR machine learning OR software engineer",
    "page": 1,
    "pageSize": 50,
    "jobType": "Full-time",
}

# They have experience level filters:
# - Entry Level
# - Mid Level
# - Senior Level
```

#### 1.4.2 Tech Job Aggregators (Multi-Source)

| Platform | URL | Why Valuable |
|----------|-----|--------------|
| **Simplify** | simplify.jobs | Already integrated - aggregates from all ATS |
| **Wellfound (AngelList)** | wellfound.com | Startup-focused, has new grad filter |
| **Levels.fyi** | levels.fyi/jobs | Tech jobs with comp data |
| **Otta** | otta.com | Curated startup jobs, good filters |
| **Handshake** | joinhandshake.com | University recruiting focus |
| **RippleMatch** | ripplematch.com | New grad / early career |
| **Untapped** | untapped.io | Diversity-focused tech jobs |
| **BuiltIn** | builtin.com | Regional tech hubs |
| **Y Combinator Work at a Startup** | workatastartup.com | YC company jobs |

**High Priority: Wellfound (AngelList Talent)**

```python
# Wellfound has excellent filtering for startups
# URL: https://wellfound.com/role/software-engineer

# Key filters available:
# - Role: Software Engineer, ML Engineer, Data Scientist
# - Experience: 0-1 years, 1-2 years
# - Remote: Yes/No/Hybrid
# - Visa Sponsorship: Available
# - Company Stage: Seed, Series A, Series B, etc.

# API endpoint (requires auth):
# GET https://wellfound.com/api/jobs
```

**High Priority: Y Combinator Work at a Startup**

```python
# YC's job board for portfolio companies
# URL: https://www.workatastartup.com/jobs

# Excellent for:
# - Early stage startups (most new-grad friendly)
# - AI/ML companies (YC invests heavily here)
# - Well-funded companies (less layoff risk)

# Has filters for:
# - Role type
# - Experience level
# - Industry (including biotech)
# - Visa sponsorship
```

#### 1.4.3 Target Companies: Computational Chemistry & Drug Discovery

**Tier 1: Well-Funded AI-First Drug Discovery**

| Company | Focus | Funding | ATS | New Grad Likelihood |
|---------|-------|---------|-----|---------------------|
| **Recursion** | AI drug discovery | $1.5B+ | Greenhouse | High |
| **Insitro** | ML for drug discovery | $700M+ | Lever | High |
| **Schrödinger** | Computational chemistry | Public | Workday | High |
| **Relay Therapeutics** | Structure-based drug design | Public | Greenhouse | Medium |
| **Insilico Medicine** | Generative AI for drugs | $400M+ | Custom | Medium |
| **Atomwise** | AI drug screening | $175M+ | Lever | High |
| **BenevolentAI** | AI drug discovery | Public (UK) | Workday | Medium |
| **Exscientia** | AI-driven drug design | Public (UK) | Greenhouse | Medium |
| **Generate Biomedicines** | Generative biology | $370M+ | Lever | High |
| **Dyno Therapeutics** | ML for gene therapy | $300M+ | Greenhouse | High |
| **Terray Therapeutics** | ML + high-throughput chem | $260M+ | Lever | High |
| **XtalPi** | AI pharma | $700M+ | Custom | Medium |
| **Charm Therapeutics** | AlphaFold-based drug design | $60M+ | Lever | High |
| **Isomorphic Labs** | DeepMind drug discovery | Alphabet | Custom | Low (selective) |

**Tier 2: Biotech with Strong Computational Teams**

| Company | Focus | Why Relevant |
|---------|-------|--------------|
| **Genentech/Roche** | Large pharma, ML teams | Computational biology roles |
| **Moderna** | mRNA, uses ML | Bioinformatics + ML |
| **Illumina** | Sequencing, ML | Software + genomics |
| **10x Genomics** | Single-cell tech | Computational biology |
| **Twist Bioscience** | DNA synthesis | Software + biotech |
| **Zymergen** (acquired by Ginkgo) | Synthetic biology | ML + chemistry |
| **Ginkgo Bioworks** | Synthetic biology | Large computational team |
| **Tempus** | Precision medicine | ML + genomics |
| **Freenome** | Cancer detection | ML + biology |
| **Grail** | Cancer screening | ML heavy |
| **Color Health** | Genetic testing | Software + genomics |
| **Invitae** | Genetic testing | Bioinformatics |

**Tier 3: Materials Science & Adjacent**

| Company | Focus | Why Relevant |
|---------|-------|--------------|
| **Tesla** | Battery R&D | Computational materials |
| **QuantumScape** | Solid-state batteries | Materials ML |
| **Sila Nanotechnologies** | Battery materials | Computational chemistry |
| **Form Energy** | Iron-air batteries | Materials science |
| **Citrine Informatics** | Materials AI platform | Directly ML + chemistry |
| **Kebotix** | Autonomous chemistry | ML + lab automation |
| **Emerald Cloud Lab** | Remote lab platform | Software + chemistry |

#### 1.4.4 Specialized Chemistry/Pharma Job Sites

| Site | URL | Notes |
|------|-----|-------|
| **ACS Careers** | careers.acs.org | American Chemical Society |
| **ChemJobs** | chemjobs.net | Chemistry-specific |
| **PharmaOpportunities** | pharmaopportunities.com | Pharma industry |
| **MedReps** | medreps.com | Medical/pharma sales (less relevant) |
| **C&EN Jobs** | chemistryjobs.acs.org | C&E News job board |
| **RSC Jobs** | jobs.rsc.org | Royal Society of Chemistry |
| **iHireChemists** | ihirechemists.com | Chemistry jobs aggregator |

**Implementation: ACS Careers Scraper**

```python
# American Chemical Society job board
# URL: https://chemistryjobs.acs.org/jobs/

# Filters available:
# - Keywords: "computational", "machine learning", "software"
# - Job Type: Full-time, Internship
# - Experience: Entry Level, Associate, Mid-Senior
# - Industry: Biotechnology, Pharmaceutical, etc.

# Good for:
# - Roles that value chemistry background explicitly
# - Computational chemistry positions
# - Pharma R&D roles with coding component
```

#### 1.4.5 Job Title Patterns for Chemistry + CS Roles

When scraping, search for these chemistry-adjacent tech roles:

**Direct Matches (High Priority)**
```python
CHEM_CS_TITLES = [
    "Computational Chemist",
    "Computational Scientist",
    "Cheminformatics",
    "Cheminformatics Scientist",
    "Molecular Modeling",
    "Computational Biology",
    "Bioinformatics Engineer",
    "Bioinformatics Scientist",
    "Machine Learning Engineer, Drug Discovery",
    "ML Scientist, Chemistry",
    "Research Scientist, Computational",
    "Software Engineer, Life Sciences",
    "Software Engineer, Biotech",
    "Data Scientist, Drug Discovery",
    "AI/ML Engineer, Pharma",
    "Scientific Software Developer",
    "Research Software Engineer",
]
```

**Broader Matches (Medium Priority)**
```python
BROADER_TITLES = [
    "Machine Learning Engineer",  # + filter by company in biotech
    "Data Scientist",             # + filter by company in biotech
    "Software Engineer",          # + filter by company in drug discovery
    "Research Engineer",          # Often computational
    "Applied Scientist",          # Amazon/pharma term
    "Quantitative Scientist",     # Pharma term
]
```

**Filter Enhancement for Chemistry Background**

```python
def calculate_chemistry_bonus(job: Job, description: str) -> float:
    """Boost score for jobs that value chemistry background."""
    chemistry_signals = [
        ('computational chemistry', 0.3),
        ('molecular modeling', 0.3),
        ('drug discovery', 0.25),
        ('pharmaceutical', 0.2),
        ('cheminformatics', 0.3),
        ('QSAR', 0.25),
        ('molecular dynamics', 0.25),
        ('docking', 0.2),
        ('rdkit', 0.3),  # Chemistry Python library
        ('openeye', 0.25),  # Chemistry software
        ('schrodinger', 0.25),  # Computational chem software
        ('chemistry background', 0.35),
        ('life sciences', 0.15),
        ('biotech', 0.15),
        ('biology', 0.1),
        ('wet lab', 0.1),  # May indicate cross-functional
        ('bench to bytes', 0.3),  # Specifically values chem+CS
    ]

    bonus = 0.0
    desc_lower = description.lower()

    for signal, score in chemistry_signals:
        if signal in desc_lower:
            bonus += score

    return min(bonus, 0.5)  # Cap at 0.5 bonus
```

#### 1.4.6 Implementation Priority for Chemistry Sector

| Priority | Source | Estimated Jobs | Effort |
|----------|--------|----------------|--------|
| 1 | Wellfound (biotech filter) | 500+ | Medium |
| 2 | Y Combinator Work at a Startup | 300+ | Low |
| 3 | BioSpace | 1000+ | Medium |
| 4 | Tier 1 company direct scraping | 200+ | High |
| 5 | ACS Careers | 500+ | Medium |
| 6 | Simplify (already have, add filters) | 1000+ | Low |

---

### 1.5 Job Aggregator Scrapers

Beyond ATS-specific scrapers, add aggregators that pull from multiple sources:

#### 1.5.1 Simplify Jobs Enhancement

We already have `src/scrapers/simplify_scraper.py`. Enhance it:

```python
# Simplify aggregates from:
# - Greenhouse
# - Lever
# - Workday
# - And 50+ other ATS platforms

# Current limitation: May not have all filters exposed
# Enhancement: Use their API more fully

SIMPLIFY_FILTERS = {
    "new_grad": True,
    "sponsorship": True,  # H1B/OPT friendly
    "categories": ["Software Engineering", "Data Science", "Machine Learning"],
    "locations": ["Remote", "San Francisco", "New York", "Boston"],
}
```

#### 1.5.2 LinkedIn Jobs Scraper

```python
# LinkedIn has the largest job database
# Challenge: Aggressive anti-scraping, requires auth

# Options:
# 1. LinkedIn API (limited, requires partnership)
# 2. Manual export via saved searches
# 3. Third-party tools (risky)

# Recommended: Set up saved searches, export weekly
LINKEDIN_SEARCH_QUERIES = [
    "new grad software engineer",
    "entry level machine learning",
    "junior software developer biotech",
    "computational chemistry",
    "software engineer drug discovery",
]
```

#### 1.5.3 Indeed/Glassdoor (API Access)

```python
# Indeed Publisher API (requires approval)
# https://developers.indeed.com/

# Glassdoor API (deprecated, but job data available)
# May need to scrape carefully

# Both useful for:
# - Volume (millions of jobs)
# - Company reviews (filter by rating)
# - Salary data
```

---

### 1.6 Company Discovery Pipeline

#### Master Company List Sources

| Source | Companies | Quality |
|--------|-----------|---------|
| Y Combinator directory | 4,000+ | High (funded, growing) |
| Crunchbase (Series A+) | 10,000+ | Medium-High |
| PitchBook | 5,000+ | High (requires subscription) |
| LinkedIn (biotech filter) | 2,000+ | Medium |
| BioSpace company directory | 1,500+ | High for biotech |
| Fierce Biotech 50 | 50 | Very High (curated) |
| CB Insights AI 100 | 100 | Very High |
| Forbes AI 50 | 50 | Very High |

#### Company Metadata to Collect

```sql
-- Expanded company schema
ALTER TABLE companies ADD COLUMN industry TEXT;  -- 'AI', 'Biotech', 'Fintech', etc.
ALTER TABLE companies ADD COLUMN sub_industry TEXT;  -- 'Drug Discovery', 'Genomics', etc.
ALTER TABLE companies ADD COLUMN funding_stage TEXT;  -- 'Seed', 'Series A', 'Public'
ALTER TABLE companies ADD COLUMN funding_total INTEGER;  -- Total raised in USD
ALTER TABLE companies ADD COLUMN employee_count INTEGER;
ALTER TABLE companies ADD COLUMN founded_year INTEGER;
ALTER TABLE companies ADD COLUMN hq_location TEXT;
ALTER TABLE companies ADD COLUMN remote_friendly BOOLEAN;
ALTER TABLE companies ADD COLUMN h1b_sponsor BOOLEAN;
ALTER TABLE companies ADD COLUMN chemistry_relevant BOOLEAN;  -- Flags for Justin
```

#### Company Prioritization Score

```python
def calculate_company_priority(company: Company) -> float:
    """Score companies for Justin's profile."""
    score = 0.0

    # Chemistry relevance (huge bonus)
    if company.chemistry_relevant:
        score += 0.4
    if company.sub_industry in ['Drug Discovery', 'Computational Chemistry', 'Biotech']:
        score += 0.3

    # Funding stage (Series A-C most new-grad friendly)
    stage_scores = {
        'Seed': 0.1,
        'Series A': 0.25,
        'Series B': 0.25,
        'Series C': 0.2,
        'Series D+': 0.1,
        'Public': 0.15,
    }
    score += stage_scores.get(company.funding_stage, 0.1)

    # Size (smaller = more likely to hire new grads)
    if company.employee_count:
        if company.employee_count < 50:
            score += 0.2
        elif company.employee_count < 200:
            score += 0.15
        elif company.employee_count < 500:
            score += 0.1

    # New-grad friendly signals
    if company.h1b_sponsor:
        score += 0.1
    if company.remote_friendly:
        score += 0.05

    return min(score, 1.0)
```

### Schema Changes

```sql
-- Update ats_platform to track source
ALTER TABLE companies ADD COLUMN secondary_ats TEXT;

-- Or create a junction table for companies with multiple ATS
CREATE TABLE company_ats_sources (
    company_id INTEGER NOT NULL,
    ats_platform TEXT NOT NULL,
    ats_url TEXT NOT NULL,
    is_primary BOOLEAN DEFAULT 0,
    last_scraped TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id),
    UNIQUE(company_id, ats_platform)
);
```

### Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| ATS platforms covered | 1 | 5+ |
| Job aggregators integrated | 1 (Simplify) | 4+ |
| Total companies | 304 | 1,500+ |
| Total jobs | 7,118 | 40,000+ |
| New grad roles found | 14 | 100+ |
| Biotech/pharma companies | 0 | 200+ |
| Chemistry-relevant roles | 0 | 50+ |

### Implementation Priority

**Phase 1: Quick Wins (High ROI, Low Effort)**
1. **Y Combinator Work at a Startup** - Curated YC jobs, new-grad friendly
2. **Wellfound (AngelList)** - Startup jobs with great filters
3. **Enhance Simplify scraper** - Already integrated, add biotech filters

**Phase 2: Core ATS Expansion**
4. **Lever scraper** - Many top startups (Figma, Notion, Insitro)
5. **Greenhouse scraper** - Large coverage (Airbnb, Discord, Recursion)

**Phase 3: Chemistry Sector (Justin's Differentiator)**
6. **BioSpace scraper** - Biotech job board with entry-level filter
7. **ACS Careers scraper** - Chemistry-specific jobs
8. **Tier 1 biotech direct scraping** - Recursion, Insitro, Schrödinger, etc.

**Phase 4: Company Discovery**
9. **YC company directory** - 4,000+ companies
10. **Crunchbase integration** - Funding data, industry tags
11. **BioSpace company directory** - Biotech-specific

---

## Issue #2: Zero Job Descriptions

### Problem Statement

Job descriptions are not being scraped or stored, forcing the filter to rely solely on job titles. This causes both false positives and false negatives.

### Evidence from Data Analysis

```sql
-- Check job description coverage
SELECT
    SUM(CASE WHEN job_description IS NULL OR job_description = '' THEN 1 ELSE 0 END) as no_description,
    SUM(CASE WHEN job_description IS NOT NULL AND job_description != '' THEN 1 ELSE 0 END) as has_description
FROM jobs;

-- Result:
-- no_description: 7118
-- has_description: 0
```

**0% of jobs have descriptions stored.**

### Impact Analysis

#### False Negatives (Missed Opportunities)

Jobs rejected by title that may be new-grad friendly based on description:

| Job Title | Rejection Reason | Likely Reality |
|-----------|------------------|----------------|
| "Software Engineer" | No new grad qualifier | Description may say "0-2 years" |
| "Software Engineer II" | No new grad qualifier | Level II often = 0-2 years at startups |
| "ML Engineer" | No new grad qualifier | May accept strong new grads |

**Quantified:** 866 jobs rejected with "No new grad qualifier in title"

```sql
SELECT COUNT(*) FROM target_jobs WHERE match_reason = 'No new grad qualifier in title';
-- Result: 866
```

Many of these likely have descriptions stating "entry-level welcome" or "0-2 years experience."

#### False Positives (Wasted Effort)

Jobs accepted by title that may have disqualifying requirements in description:

| Job Title | Why Accepted | Potential Issue in Description |
|-----------|--------------|-------------------------------|
| "Junior Developer" | Junior keyword | "5+ years required" (title mismatch) |
| "Entry-Level Engineer" | Entry-level keyword | "PhD required" |
| "Associate SWE" | Associate keyword | "Must have 3+ years" |

#### Missing Skill Matching

Without descriptions, we cannot match Justin's specific skills:

| Justin's Skill | Jobs Mentioning (Estimated) | Current Match Capability |
|----------------|---------------------------|-------------------------|
| React | ~500-800 | None |
| Python | ~2000+ | None |
| Machine Learning | ~300-500 | None |
| Playwright/Testing | ~100-200 | None |
| TypeScript | ~600-900 | None |

### Current Scraper Analysis

Looking at the existing Ashby scraper to understand why descriptions aren't captured:

**File:** `src/scrapers/ashby_scraper.py`

The Ashby job listing API returns job metadata but may require a second request to get full description. Need to verify:

1. Does the listing endpoint include descriptions?
2. Is there a separate job detail endpoint?
3. Are descriptions being fetched but not stored?

### Proposed Solution

#### 2.1 Update Ashby Scraper to Fetch Descriptions

**Ashby API Structure:**

```
# Job listing (current)
GET https://jobs.ashbyhq.com/api/non-user-graphql
Body: { "operationName": "ApiJobBoardWithTeams", ... }

# Job detail (need to add)
GET https://jobs.ashbyhq.com/api/non-user-graphql
Body: { "operationName": "ApiJobPosting", "variables": { "jobPostingId": "..." } }
```

**Implementation:**

```python
def scrape_job_detail(job_id: str) -> dict:
    """Fetch full job description for a specific job."""
    payload = {
        "operationName": "ApiJobPosting",
        "variables": {"jobPostingId": job_id},
        "query": """
            query ApiJobPosting($jobPostingId: String!) {
                jobPosting(id: $jobPostingId) {
                    id
                    title
                    descriptionHtml
                    locationName
                    publishedDate
                    employmentType
                }
            }
        """
    }
    response = requests.post(ASHBY_API_URL, json=payload)
    return response.json()
```

#### 2.2 Schema Already Supports Descriptions

The current schema has the field, it's just not populated:

```sql
CREATE TABLE jobs (
    ...
    job_description TEXT,  -- Already exists, just empty
    ...
);
```

#### 2.3 Description Processing Pipeline

**Raw storage:**
```python
# Store full HTML description
job.job_description = detail_response['descriptionHtml']
```

**Extracted fields (new columns to add):**

```sql
ALTER TABLE jobs ADD COLUMN years_experience_min INTEGER;
ALTER TABLE jobs ADD COLUMN years_experience_max INTEGER;
ALTER TABLE jobs ADD COLUMN degree_required TEXT;  -- 'BS', 'MS', 'PhD', 'None'
ALTER TABLE jobs ADD COLUMN skills_mentioned TEXT;  -- JSON array
ALTER TABLE jobs ADD COLUMN remote_type TEXT;  -- 'Remote', 'Hybrid', 'Onsite'
ALTER TABLE jobs ADD COLUMN visa_sponsorship BOOLEAN;
```

**Extraction logic:**

```python
def extract_experience_requirement(description: str) -> tuple[int, int]:
    """Extract years of experience from job description."""
    patterns = [
        r'(\d+)\+?\s*years?\s*(?:of\s*)?experience',
        r'(\d+)-(\d+)\s*years?\s*(?:of\s*)?experience',
        r'entry.?level|new\s*grad|0\s*years',
    ]
    # Return (min_years, max_years) or (0, 0) for entry-level
    ...

def extract_skills(description: str) -> list[str]:
    """Extract mentioned technologies/skills."""
    skill_patterns = [
        'React', 'Python', 'TypeScript', 'JavaScript', 'Node.js',
        'Machine Learning', 'ML', 'AI', 'PyTorch', 'TensorFlow',
        'AWS', 'GCP', 'Docker', 'Kubernetes', 'PostgreSQL',
        # ... comprehensive list
    ]
    ...
```

#### 2.4 Backfill Strategy

For existing 7,118 jobs:

```python
def backfill_descriptions():
    """Fetch descriptions for jobs that don't have them."""
    jobs_without_desc = db.execute("""
        SELECT j.id, j.job_url
        FROM jobs j
        WHERE j.job_description IS NULL OR j.job_description = ''
    """).fetchall()

    for job in jobs_without_desc:
        job_id = extract_job_id_from_url(job.job_url)
        detail = scrape_job_detail(job_id)
        db.execute("""
            UPDATE jobs
            SET job_description = ?, location = ?
            WHERE id = ?
        """, (detail['descriptionHtml'], detail['locationName'], job.id))
        time.sleep(0.5)  # Rate limiting
```

**Estimated time:** 7,118 jobs × 0.5s = ~1 hour

### Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Jobs with descriptions | 0% | 95%+ |
| Jobs with extracted experience reqs | 0% | 80%+ |
| Jobs with extracted skills | 0% | 80%+ |
| Filter accuracy (estimated) | ~50% | ~85%+ |

---

## Issue #3: No Job Posting Date

### Problem Statement

We capture `discovered_date` (when we scraped the job) but not when the job was originally posted. This means we can't:

1. Prioritize fresh listings
2. Filter out stale/filled positions
3. Track job market velocity
4. Avoid wasting outreach on dead opportunities

### Evidence from Data Analysis

```sql
-- Check date fields
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN discovered_date IS NOT NULL THEN 1 ELSE 0 END) as has_discovered,
    0 as has_posted  -- Column doesn't exist
FROM jobs;

-- Schema inspection shows no posted_date field
```

**Current schema has `discovered_date` only - no `posted_date`.**

### Impact Analysis

#### Stale Job Problem

Industry data on job posting lifecycle:

| Days Since Posted | Status | Response Rate |
|-------------------|--------|---------------|
| 0-7 days | Fresh | 15-20% |
| 8-14 days | Active | 10-15% |
| 15-30 days | Cooling | 5-10% |
| 30-60 days | Stale | 2-5% |
| 60+ days | Likely filled | <2% |

**Without posting dates, we treat a 6-month-old listing the same as one posted yesterday.**

#### Outreach Efficiency

Estimated waste without date filtering:

```
Total jobs passing filter: 14
Estimated stale (>30 days): ~30-40%
Wasted outreach effort: 4-6 contacts
Hours wasted on stale leads: 2-4 hours
```

#### Case Study: Seasonal Hiring

New grad roles are highly seasonal:

| Month | New Grad Posting Volume |
|-------|------------------------|
| Aug-Oct | High (Fall recruiting) |
| Jan-Mar | Medium (Spring recruiting) |
| Apr-Jun | Low (Most filled) |
| Jul | Very low |

**Current date: January 2026** - We're in spring recruiting season. Jobs posted in Aug-Oct 2025 are likely filled.

### Proposed Solution

#### 3.1 Schema Changes

```sql
-- Add posting date tracking
ALTER TABLE jobs ADD COLUMN posted_date TEXT;
ALTER TABLE jobs ADD COLUMN last_seen_date TEXT;
ALTER TABLE jobs ADD COLUMN is_active BOOLEAN DEFAULT 1;

-- Add index for date-based queries
CREATE INDEX idx_posted_date ON jobs(posted_date);
CREATE INDEX idx_job_active ON jobs(is_active);
```

**Field Definitions:**

| Field | Description | Source |
|-------|-------------|--------|
| `posted_date` | When job was originally posted | ATS API or page scraping |
| `discovered_date` | When we first saw it (existing) | Our scraper timestamp |
| `last_seen_date` | Most recent scrape where job was present | Our scraper timestamp |
| `is_active` | Whether job still appears in listings | Derived from scraping |

#### 3.2 Ashby Posted Date Extraction

Ashby includes `publishedDate` in their API response:

```python
# In job detail response
{
    "jobPosting": {
        "id": "abc123",
        "title": "Software Engineer",
        "publishedDate": "2025-12-15T00:00:00.000Z",  # <-- This field
        ...
    }
}
```

**Implementation:**

```python
def scrape_job_with_date(job_id: str) -> dict:
    """Fetch job with posting date."""
    # ... API call ...
    return {
        'title': data['title'],
        'description': data['descriptionHtml'],
        'posted_date': data.get('publishedDate'),  # May be null
        'location': data.get('locationName'),
    }
```

#### 3.3 Date Estimation Fallback

Some jobs may not have explicit posting dates. Fallback strategies:

**Strategy 1: Use discovered_date as upper bound**
```python
# Job can't be newer than when we first saw it
if posted_date is None:
    posted_date = discovered_date
```

**Strategy 2: Wayback Machine / Historical data**
```python
# Check if job URL appeared in earlier scrapes
# Not recommended for MVP - adds complexity
```

**Strategy 3: Flag as unknown**
```python
# Mark jobs with uncertain dates for manual review
if posted_date is None:
    date_confidence = 'estimated'
else:
    date_confidence = 'confirmed'
```

#### 3.4 Freshness Scoring

Add freshness to relevance scoring:

```python
def calculate_freshness_score(posted_date: str) -> float:
    """Score from 1.0 (today) to 0.0 (>60 days old)."""
    if posted_date is None:
        return 0.5  # Unknown = neutral

    days_old = (datetime.now() - parse_date(posted_date)).days

    if days_old <= 7:
        return 1.0
    elif days_old <= 14:
        return 0.9
    elif days_old <= 30:
        return 0.7
    elif days_old <= 60:
        return 0.4
    else:
        return 0.1

def calculate_total_relevance(job) -> float:
    """Combine title match, skill match, and freshness."""
    title_score = calculate_title_score(job)  # Existing
    freshness_score = calculate_freshness_score(job.posted_date)

    # Weighted combination
    return (title_score * 0.7) + (freshness_score * 0.3)
```

#### 3.5 Stale Job Detection

Detect jobs that have disappeared (likely filled):

```python
def mark_stale_jobs():
    """Mark jobs not seen in recent scrape as inactive."""
    db.execute("""
        UPDATE jobs
        SET is_active = 0
        WHERE last_seen_date < date('now', '-7 days')
        AND is_active = 1
    """)
```

#### 3.6 Reporting Queries

```sql
-- Jobs by freshness
SELECT
    CASE
        WHEN posted_date >= date('now', '-7 days') THEN '0-7 days'
        WHEN posted_date >= date('now', '-14 days') THEN '8-14 days'
        WHEN posted_date >= date('now', '-30 days') THEN '15-30 days'
        WHEN posted_date >= date('now', '-60 days') THEN '31-60 days'
        ELSE '60+ days'
    END as age_bucket,
    COUNT(*) as count
FROM jobs
WHERE is_active = 1
GROUP BY age_bucket;

-- Fresh new grad roles (priority queue)
SELECT c.name, j.job_title, j.posted_date
FROM jobs j
JOIN companies c ON j.company_id = c.id
JOIN target_jobs t ON j.id = t.job_id
WHERE t.status = 1
AND j.posted_date >= date('now', '-14 days')
ORDER BY j.posted_date DESC;
```

### Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Jobs with posting date | 0% | 80%+ |
| Stale job detection | None | Automated weekly |
| Fresh job prioritization | None | Top of queue |
| Outreach to stale jobs | Unknown (~30%?) | <5% |

---

## Issue #4: Title-Only Filter Has Systematic Bias

### Problem Statement

The current filter uses regex patterns on job titles only, causing systematic false negatives (missing good jobs) and false positives (including bad jobs).

### Evidence from Data Analysis

#### Rejection Reason Breakdown

```sql
SELECT match_reason, COUNT(*) as count
FROM target_jobs
WHERE status = 0
GROUP BY match_reason
ORDER BY count DESC
LIMIT 10;
```

**Results:**

| Rejection Reason | Count | Analysis |
|------------------|-------|----------|
| Regex: Seniority indicator: Senior | 1,456 | Correct rejections |
| Regex: Seniority indicator: Manager | 1,111 | Correct rejections |
| **No new grad qualifier in title** | **866** | **Potential false negatives** |
| Non-engineering role | 509 | Correct rejections |
| Regex: Seniority indicator: Lead | 370 | Correct rejections |
| Regex: Seniority indicator: Staff | 333 | Correct rejections |

**866 jobs rejected solely because the title lacked "new grad," "junior," "entry," etc.**

#### False Negative Examples

```sql
SELECT j.job_title, c.name, t.match_reason
FROM target_jobs t
JOIN jobs j ON t.job_id = j.id
JOIN companies c ON j.company_id = c.id
WHERE t.status = 0
AND t.match_reason = 'No new grad qualifier in title'
AND (LOWER(j.job_title) LIKE '%software%' OR LOWER(j.job_title) LIKE '%engineer%')
LIMIT 10;
```

**Results:**

| Job Title | Company | Issue |
|-----------|---------|-------|
| Fullstack Engineer | 9fin | May accept new grads |
| Software Engineer II (Risk) | Acorns | Level II often = 0-2 years |
| AI Software Engineer - Model Evaluation | AlephAlpha | May accept strong new grads |
| Software Engineer - Backend | Anon | Generic title, check description |
| Software Engineer - Full Stack | Anon | Generic title, check description |
| Forward Deployed Software Engineer | Credal | May accept new grads |
| Systems Software Engineer | Crusoe | May accept new grads |
| Software Engineer, Infrastructure | DatologyAI | May accept new grads |

#### False Negative: Combined Roles

```sql
SELECT j.job_title, t.match_reason
FROM target_jobs t
JOIN jobs j ON t.job_id = j.id
WHERE j.job_title LIKE '%Intern/New Grad%';
```

**Result:**
| Job Title | Rejection Reason |
|-----------|------------------|
| Intern/New Grad Software Engineer | Regex: Internship: Intern |

**This role explicitly says "New Grad" but was rejected because "Intern" matched first.**

### Current Filter Logic

**File:** `src/filters/ai_filter.py` (or similar)

The current filter likely uses patterns like:

```python
# Rejection patterns (checked first)
SENIOR_PATTERNS = ['senior', 'sr.', 'sr ', 'staff', 'principal', 'lead', 'manager', 'director', 'head of', 'vp']
INTERN_PATTERNS = ['intern', 'co-op', 'coop']
NON_ENG_PATTERNS = ['sales', 'marketing', 'hr', 'recruiter', 'account executive', ...]

# Acceptance patterns
NEW_GRAD_PATTERNS = ['new grad', 'entry', 'junior', 'jr.', 'associate', 'early career', 'university', 'college grad']

def filter_job(title: str) -> tuple[bool, str]:
    title_lower = title.lower()

    # Check rejections first
    for pattern in SENIOR_PATTERNS:
        if pattern in title_lower:
            return (False, f"Seniority indicator: {pattern}")

    for pattern in INTERN_PATTERNS:
        if pattern in title_lower:
            return (False, f"Internship: {pattern}")

    # Check acceptances
    for pattern in NEW_GRAD_PATTERNS:
        if pattern in title_lower:
            return (True, f"New grad qualifier: {pattern}")

    # Default: reject if no qualifier
    return (False, "No new grad qualifier in title")
```

**Problems with this logic:**

1. **Order dependency:** "Intern" checked before "New Grad" → "Intern/New Grad" rejected
2. **Binary classification:** No "maybe" category for human review
3. **No context:** Can't consider job description
4. **Overly conservative:** Rejects anything without explicit qualifier

### Proposed Solution

#### 4.1 Three-Tier Classification

Instead of binary pass/fail, use three tiers:

```python
class FilterResult(Enum):
    ACCEPT = "accept"      # Definitely new-grad appropriate
    REVIEW = "review"      # Maybe appropriate, needs human/AI review
    REJECT = "reject"      # Definitely not appropriate

def filter_job_v2(title: str, description: str = None) -> tuple[FilterResult, str, float]:
    """
    Returns (result, reason, confidence)
    """
    ...
```

#### 4.2 Updated Filter Logic

```python
def filter_job_v2(title: str, description: str = None) -> tuple[FilterResult, str, float]:
    title_lower = title.lower()

    # === PHASE 1: Title-based quick filters ===

    # Hard rejections (high confidence)
    HARD_REJECT_PATTERNS = [
        ('senior', 0.95),
        ('staff', 0.95),
        ('principal', 0.95),
        ('director', 0.95),
        ('vp ', 0.95),
        ('vice president', 0.95),
        ('head of', 0.90),
        ('manager', 0.85),  # Some "manager" roles are IC
    ]

    for pattern, confidence in HARD_REJECT_PATTERNS:
        if pattern in title_lower:
            return (FilterResult.REJECT, f"Seniority: {pattern}", confidence)

    # Hard accepts (high confidence)
    HARD_ACCEPT_PATTERNS = [
        ('new grad', 0.99),
        ('new graduate', 0.99),
        ('entry level', 0.95),
        ('entry-level', 0.95),
        ('college grad', 0.95),
        ('university grad', 0.95),
        ('early career', 0.90),
        ('junior', 0.85),
        ('jr.', 0.85),
    ]

    for pattern, confidence in HARD_ACCEPT_PATTERNS:
        if pattern in title_lower:
            return (FilterResult.ACCEPT, f"New grad qualifier: {pattern}", confidence)

    # Special case: Combined roles like "Intern/New Grad"
    if 'new grad' in title_lower or 'new graduate' in title_lower:
        # New grad mentioned anywhere = accept, even if "intern" also present
        return (FilterResult.ACCEPT, "New grad qualifier found", 0.95)

    # Internships - separate category, not rejected
    INTERN_PATTERNS = ['intern', 'co-op', 'coop', 'internship']
    for pattern in INTERN_PATTERNS:
        if pattern in title_lower:
            return (FilterResult.ACCEPT, f"Internship: {pattern}", 0.90)

    # Non-engineering roles (reject)
    NON_ENG_PATTERNS = [
        'sales', 'account executive', 'account manager',
        'marketing', 'recruiter', 'recruiting', 'hr ',
        'human resources', 'customer success', 'support',
        'legal', 'finance', 'accounting', 'operations',
        'designer', 'design', 'writer', 'content',
    ]

    is_engineering = any(p in title_lower for p in ['engineer', 'developer', 'software', 'ml', 'machine learning', 'data scientist'])

    for pattern in NON_ENG_PATTERNS:
        if pattern in title_lower and not is_engineering:
            return (FilterResult.REJECT, f"Non-engineering: {pattern}", 0.85)

    # === PHASE 2: Description-based analysis (if available) ===

    if description:
        desc_lower = description.lower()

        # Check for experience requirements
        exp_match = re.search(r'(\d+)\+?\s*years?\s*(?:of\s*)?experience', desc_lower)
        if exp_match:
            years = int(exp_match.group(1))
            if years >= 5:
                return (FilterResult.REJECT, f"Requires {years}+ years experience", 0.90)
            elif years >= 3:
                return (FilterResult.REVIEW, f"Requires {years}+ years (borderline)", 0.60)
            elif years <= 2:
                return (FilterResult.ACCEPT, f"Requires only {years} years", 0.80)

        # Check for new grad signals in description
        NEW_GRAD_DESC_SIGNALS = [
            'new grad', 'recent graduate', 'entry level',
            '0-2 years', '0-1 years', 'early career',
            'bootcamp', 'self-taught welcome',
        ]
        for signal in NEW_GRAD_DESC_SIGNALS:
            if signal in desc_lower:
                return (FilterResult.ACCEPT, f"Description indicates: {signal}", 0.85)

    # === PHASE 3: Default handling ===

    # Engineering role without clear seniority indicator
    if is_engineering:
        if description:
            # We have description but no clear signals - needs review
            return (FilterResult.REVIEW, "Engineering role, unclear seniority", 0.50)
        else:
            # No description - needs review
            return (FilterResult.REVIEW, "Engineering role, no description to analyze", 0.40)

    # Non-engineering, unclear
    return (FilterResult.REJECT, "Non-engineering or unclear role", 0.60)
```

#### 4.3 Schema Changes for Three-Tier System

```sql
-- Update target_jobs to support three tiers
ALTER TABLE target_jobs ADD COLUMN filter_confidence REAL;
ALTER TABLE target_jobs ADD COLUMN needs_review BOOLEAN DEFAULT 0;

-- New status values:
-- 0 = Rejected
-- 1 = Needs Review (NEW)
-- 2 = Accepted
-- 3 = Accepted (human verified)
```

#### 4.4 Review Queue Workflow

```python
def get_review_queue() -> list[Job]:
    """Get jobs that need human review."""
    return db.execute("""
        SELECT j.*, t.match_reason, t.filter_confidence
        FROM jobs j
        JOIN target_jobs t ON j.id = t.job_id
        WHERE t.status = 1  -- Needs review
        ORDER BY t.filter_confidence DESC  -- Highest confidence first
    """).fetchall()

def review_job(job_id: int, decision: str, reviewer_notes: str = None):
    """Human reviews a job in the queue."""
    new_status = 3 if decision == 'accept' else 0
    db.execute("""
        UPDATE target_jobs
        SET status = ?, reviewer_notes = ?
        WHERE job_id = ?
    """, (new_status, reviewer_notes, job_id))
```

#### 4.5 AI-Assisted Review (Optional Enhancement)

For jobs in the review queue, use Claude to analyze:

```python
def ai_review_job(job: Job) -> tuple[str, str]:
    """Use Claude to review ambiguous jobs."""
    prompt = f"""
    Analyze this job posting for a new grad software engineer (CS major, ML/React experience):

    Title: {job.job_title}
    Company: {job.company_name}
    Description: {job.job_description[:2000]}

    Questions:
    1. Is this role appropriate for a new grad (0-1 years experience)?
    2. What experience level does it actually require?
    3. Does it match skills in React, Python, ML?

    Respond with:
    DECISION: ACCEPT or REJECT
    CONFIDENCE: 0.0-1.0
    REASON: Brief explanation
    """

    response = claude.complete(prompt)
    # Parse response...
    return (decision, reason)
```

### Testing the New Filter

**Test cases to validate:**

```python
test_cases = [
    # Should ACCEPT
    ("Software Engineer, New Grad", None, FilterResult.ACCEPT),
    ("Intern/New Grad Software Engineer", None, FilterResult.ACCEPT),
    ("Junior Software Developer", None, FilterResult.ACCEPT),
    ("Entry-Level ML Engineer", None, FilterResult.ACCEPT),
    ("Software Engineering Intern (Summer 2026)", None, FilterResult.ACCEPT),

    # Should REJECT
    ("Senior Software Engineer", None, FilterResult.REJECT),
    ("Staff ML Engineer", None, FilterResult.REJECT),
    ("VP of Engineering", None, FilterResult.REJECT),
    ("Sales Account Executive", None, FilterResult.REJECT),

    # Should REVIEW (ambiguous)
    ("Software Engineer", None, FilterResult.REVIEW),
    ("ML Engineer", None, FilterResult.REVIEW),
    ("Software Engineer II", None, FilterResult.REVIEW),
    ("Fullstack Engineer", None, FilterResult.REVIEW),

    # With description context
    ("Software Engineer", "0-2 years experience required", FilterResult.ACCEPT),
    ("Software Engineer", "5+ years experience required", FilterResult.REJECT),
]
```

### Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| False negative rate | ~30% (estimated) | <10% |
| Jobs needing review | 0 | ~200-500 |
| Filter accuracy | ~50% | ~85% |
| Human review time | N/A | <2 hrs/week |

---

## Implementation Roadmap

### Phase 1: Quick Wins (1-2 days)

1. **Fix false negative for "Intern/New Grad"** - Reorder pattern matching
2. **Add `posted_date` column** - Schema migration
3. **Fetch posted dates from Ashby API** - Update scraper

### Phase 2: Core Improvements (3-5 days)

4. **Backfill job descriptions** - Run for 7,118 existing jobs
5. **Implement three-tier filter** - Replace binary filter
6. **Add description-based filtering** - Experience requirements

### Phase 3: Expansion (5-7 days)

7. **Lever scraper** - New ATS platform
8. **Greenhouse scraper** - New ATS platform
9. **Company discovery** - Expand company list

### Phase 4: Optimization (Ongoing)

10. **AI-assisted review** - Claude for ambiguous jobs
11. **Freshness scoring** - Prioritize recent jobs
12. **Skill matching** - Justin's profile vs job requirements

---

## Appendix: SQL Queries for Validation

### After Implementation, Run These Queries:

```sql
-- Verify description coverage improved
SELECT
    SUM(CASE WHEN job_description IS NOT NULL AND job_description != '' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as description_coverage_pct
FROM jobs;

-- Verify posting dates captured
SELECT
    SUM(CASE WHEN posted_date IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as posted_date_coverage_pct
FROM jobs;

-- Check three-tier filter distribution
SELECT
    CASE status
        WHEN 0 THEN 'Rejected'
        WHEN 1 THEN 'Needs Review'
        WHEN 2 THEN 'Accepted'
        WHEN 3 THEN 'Accepted (Verified)'
    END as status,
    COUNT(*) as count
FROM target_jobs
GROUP BY status;

-- Verify ATS platform expansion
SELECT ats_platform, COUNT(*) as companies
FROM companies
GROUP BY ats_platform;
```

---

**Document Version:** 1.0
**Last Updated:** 2026-01-02
**Author:** Data Analysis Session
