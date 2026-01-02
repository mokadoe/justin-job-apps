# Job Application Automation Pipeline

> Automated system to discover new grad software engineering jobs, find recruiting contacts at startups, and enable targeted outreach.

**🔗 Repository:** https://github.com/mokadoe/justin-job-apps

**📊 Status:** MVP Complete (Day 6/7) - End-to-end outreach pipeline ready for testing

**💻 Tech Stack:** Python 3.13, SQLite, Claude API (Anthropic), Google Custom Search API

---

## 📌 For New Claude Sessions - Read This First

**Current State (as of Jan 1, 2026):**
- ✅ Complete end-to-end pipeline built and tested
- ✅ All code committed (10 commits) and pushed to GitHub
- ✅ Full documentation in place (README, claude.md, docs/)
- 🔄 **Next step:** Send first batch of real outreach emails and track responses

**What's Working:**
- Job scraping: 7,124 jobs from 305 companies loaded
- AI filtering: 16 pending jobs identified (0.22% pass rate)
- Contact discovery: 73 contacts found (17 priority decision-makers)
- Message generation: Complete outreach packages with personalized messages + email candidates
- Database: SQLite with 5 tables, all working

**What You Need to Know:**
- Database is in `data/jobs.db` (gitignored, local only)
- API keys in `.env` file (also gitignored)
- Virtual environment: `env/` (NOT `venv/`)
- Run `python3 src/outreach/prepare_outreach.py` to see a complete outreach example
- All make commands work: `make help` for full list

**Common Next Tasks:**
1. Improve data quality (populate missing company websites)
2. Send test outreach emails manually
3. Build response tracking system
4. Expand contact discovery to remaining companies

---

## Quick Start

```bash
# Setup environment (uses direnv)
# Ensure .env file exists with API keys:
# - ANTHROPIC_API_KEY
# - GOOGLE_API_KEY
# - GOOGLE_CSE_ID

# Initialize database
make init

# Load jobs from Ashby ATS
make load

# Filter jobs with Claude API (strict new grad criteria)
make filter

# View results
make targets         # Show pending jobs
make inspect         # Full database overview
make analyze         # Job data analysis

# Discover contacts at companies with pending jobs
python3 src/discovery/discover_contacts.py

# Generate personalized outreach package (random company + contact)
python3 src/outreach/prepare_outreach.py
```

---

## Project Architecture

### Core Pipeline

1. **Job Scraping** → 2. **AI Filtering** → 3. **Contact Discovery** → 4. **Message Generation** → 5. **Outreach** (Manual)

### Data Sources

**Current Sources:**

1. **Ashby ATS** (Primary - Automated)
   - 305 companies actively scraped via API
   - 7,124 jobs loaded
   - 16 pending new grad positions identified
   - Direct API access: `https://api.ashbyhq.com/posting-api/job-board/{company}`

2. **Simplify Jobs GitHub** (Prospective - Manual)
   - Repository: [SimplifyJobs/New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions)
   - 587 unique companies extracted (572 new, 15 already in DB)
   - Updated daily by Simplify team
   - Output: `data/prospective_companies.txt`
   - Command: `make simplify` to refresh
   - **Use case:** Discovery of new companies to add to scraping pipeline

**Future Sources:**
- Y Combinator Work at a Startup (1000+ companies)
- Greenhouse ATS
- Lever ATS
- LinkedIn job postings

### Database Schema

**5 Tables:**
- `companies` - Company metadata (ATS platform, URLs, website, scrape status)
- `jobs` - All scraped jobs (title, location, URL, raw JSON)
- `target_jobs` - Filtered relevant jobs (status, relevance score, match reason)
- `contacts` - Decision makers at companies (founders, CTOs, VPs with priority flag)
- `messages` - Generated outreach messages (personalized per company)

**Current Data (as of Jan 1):**
- 305 companies (Ashby ATS)
- 7,124 total jobs scraped
- 16 pending jobs (0.22% pass rate - strict new grad filter)
- 73 contacts discovered (17 priority: founders/CEOs/CTOs)
- 6,876 rejected jobs

### File Structure

```
justin-job-apps/
├── README.md              # This file - project overview
├── Makefile              # Command shortcuts
├── .env                  # API keys (gitignored)
├── .envrc                # direnv config (sources env/bin/activate)
│
├── src/                  # Source code
│   ├── scrapers/         # Job scraping & loading
│   │   ├── ashby_scraper.py       # Ashby ATS API scraper
│   │   ├── simplify_scraper.py    # Simplify Jobs GitHub scraper
│   │   ├── ats_mapper.py          # Dynamic ATS field mapping
│   │   ├── ats_mappings.json      # ATS platform configs
│   │   └── load_jobs.py           # Main job loading pipeline
│   │
│   ├── filters/          # Job filtering & validation
│   │   ├── filter_jobs.py        # Claude API filtering (new grad only)
│   │   └── validate_targets.py   # Re-validate pending jobs
│   │
│   ├── discovery/        # Contact discovery
│   │   └── discover_contacts.py  # Google/LinkedIn contact search
│   │
│   ├── outreach/         # Message generation & outreach
│   │   ├── prepare_outreach.py   # Complete outreach pipeline (random)
│   │   ├── generate_messages.py  # Batch message generation
│   │   └── profile.json          # User profile for personalization
│   │
│   └── utils/            # Utilities & tools
│       ├── constants.py          # Status codes & labels
│       ├── init_db.py            # Database initialization
│       └── view.py               # Database inspection CLI
│
├── data/                 # Data directory
│   ├── jobs.db                    # SQLite database (gitignored)
│   ├── ashby_companies.txt        # List of Ashby companies (305)
│   └── prospective_companies.txt  # Companies from Simplify (572 new)
│
├── schemas/              # Database schemas
│   └── jobs.sql          # Table definitions
│
├── docs/                 # Documentation
│   ├── mvp_design.md     # Original MVP design & timeline
│   └── learnings.md      # Decision-making principles
│
└── env/                  # Python virtual environment (gitignored)
```

---

## Key Components

### 1. Job Scraping (`src/scrapers/`)

**Purpose:** Fetch job postings from ATS platforms and discover new companies

**How it works:**
- `ashby_scraper.py` - Hits public Ashby API with intelligent slug resolution
  - **3-pass approach**: original slug → simple variations → batched AI suggestions
  - Uses Claude Haiku (cheapest model) for batch slug resolution on 404 errors
  - Example: "Hims & Hers" → auto-resolves to "hims-and-hers"
- `slug_resolver.py` - Batched slug resolution using Claude Haiku (NEW)
  - Makes ONE API call for all failed companies (efficient)
  - Tries simple patterns first (free), AI as fallback
- `simplify_scraper.py` - Extracts companies from Simplify Jobs GitHub repo (prospecting tool)
- `ats_mapper.py` - Dynamic field mapping system (learn schema once per platform, reuse for all companies)
- `load_jobs.py` - Main pipeline to load jobs into database

**Key Decisions:**
- Direct ATS API > web scraping (clean JSON, no HTML parsing, reliable structure)
- Simplify Jobs as discovery source > manual company research (curated list, daily updates)
- Batched AI slug resolution > per-company API calls (cost-efficient, faster)

**Status:**
- ✅ Ashby: 7,124 jobs loaded from 305 companies (with auto slug resolution)
- ✅ Simplify: 572 new prospective companies identified (run `make simplify`)
- ✅ Slug resolver: Handles tricky company names automatically

### 2. Job Filtering (`src/filters/`)

**Purpose:** Filter for new grad software engineering roles only

**How it works:**
- Two-stage filtering:
  1. **Regex pre-filter** (free, fast) - Must contain "engineer" OR "software", exclude senior/staff/principal/manager
  2. **Claude API filter** (paid, accurate) - Strict new grad validation (must say "New Grad", "Junior", "Entry Level", or "Associate")

**Key Decision:** 96.5% rejection rate shows strict criteria working (only truly relevant jobs pass)

**Prompt Strategy:**
```
Strict criteria:
- Must explicitly say "New Grad", "Junior", "Entry Level", or "Associate"
- No experience requirements beyond 0-2 years
- Software engineering role (not data science, research, etc.)
- Return score 0.0-1.0 and reasoning
```

**Status:** ✅ Working - 16 pending jobs identified

### 3. Contact Discovery (`src/discovery/`)

**Purpose:** Find founders, CTOs, engineering leads at startups (no recruiters)

**How it works:**
- Google Custom Search API to find:
  - LinkedIn profiles (founders, CTO, VP Engineering)
  - Company websites (from ATS URLs)
  - Team/about/contact pages
- Extract names and titles from search results
- Parse LinkedIn URLs for names
- Store in `contacts` table with `is_priority` flag for decision-makers

**Key Decision:** Google Search > LinkedIn API (no API access required, gets what we need)

**Results:**
- 73 contacts discovered across 10 companies
- 17 priority contacts (founders/CEOs/CTOs)
- Stored with LinkedIn URLs and titles

**Status:** ✅ Complete - discovered contacts for pending job companies

### 4. Message Generation (`src/outreach/`)

**Purpose:** Generate personalized outreach messages for each company/contact

**How it works:**
- `profile.json` - User profile with background, interests, and project details (populated from resume)
- `prepare_outreach.py` - Complete pipeline for generating one outreach package:
  1. Selects random company with priority contacts
  2. Selects random priority contact (founder/CEO/CTO)
  3. Generates personalized message using Claude API
  4. Generates email candidates with confidence scoring
  5. Displays complete package for manual review
- `generate_messages.py` - Batch generation for all companies

**Message Strategy:**
- 5-7 sentences, conversational tone
- Structure: Background (1-2 sent) → Company interest (2-3 sent) → Project mention (1-2 sent) → CTA (1 sent)
- Personalized using company context from job postings
- Mentions automation project with GitHub link (meta/authentic approach)

**Email Generation:**
- 5 common patterns: first.last@domain (high confidence), first@domain (medium), etc.
- Uses company website domain when available
- Falls back to company name for domain construction (e.g., `n8n.com`, `fermat.com`)
- Confidence scoring: HIGH/MEDIUM/LOW

**Key Learnings:**
- Claude API model: Uses `claude-3-opus-20240229` (working model version)
- Many companies missing website field → email candidates use company name fallback
- Profile-based personalization more authentic than templates

**Status:** ✅ Complete - generates personalized messages with email candidates

### 5. Outreach Tracking

**Purpose:** Manual outreach with review-before-send workflow

**Current Approach:**
- `prepare_outreach.py` displays complete outreach package:
  - Company info and website
  - Contact name, title, LinkedIn URL
  - Personalized message body
  - 5 email candidates sorted by confidence
  - Job posting context used
- User manually copies message, chooses email, and sends
- No automated sending (ensures quality and personal touch)

**Future Enhancements:**
- Track sent messages in `messages` table with `sent_date`
- Response tracking in database
- A/B testing different message styles
- Email verification before sending

**Status:** ✅ MVP Complete - ready for manual outreach testing

---

## Database Details

### Status Codes (see `src/utils/constants.py`)

```python
STATUS_NOT_RELEVANT = 0  # Rejected by filter (96.5% of jobs)
STATUS_PENDING = 1       # Relevant, ready to apply (16 jobs)
STATUS_REVIEWED = 2      # User reviewed, decided to skip
STATUS_APPLIED = 3       # Application sent
```

### Key Queries

```sql
-- Get all pending jobs
SELECT * FROM target_jobs WHERE status = 1;

-- Company with most jobs
SELECT c.name, COUNT(j.id) as job_count
FROM companies c JOIN jobs j ON c.id = j.company_id
GROUP BY c.id ORDER BY job_count DESC;

-- Acceptance rate
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) as pending
FROM target_jobs;
```

---

## Command Reference

### Make Commands

```bash
make init       # Initialize database with schema
make load       # Load all Ashby jobs into database
make simplify   # Extract prospective companies from Simplify Jobs GitHub
make inspect    # Display database contents (companies, jobs, targets)
make targets    # Show filtered jobs statistics and sample
make analyze    # Analyze job data (locations, titles, keywords)
make filter     # Filter jobs with Claude API (strict new grad)
make validate   # Re-validate pending jobs with strict criteria
make purge      # Delete all data (keeps schema)
make clean      # Delete entire database file
```

### Outreach Commands

```bash
# Generate one random outreach package (company + contact + message + emails)
python3 src/outreach/prepare_outreach.py

# Discover contacts for companies with pending jobs
python3 src/discovery/discover_contacts.py

# Batch generate messages for all companies (future)
python3 src/outreach/generate_messages.py
```

### Advanced View Commands

```bash
# Direct CLI usage (more options than make targets)
python3 src/utils/view.py db                    # Database overview
python3 src/utils/view.py targets               # All targets
python3 src/utils/view.py targets --pending     # Only pending
python3 src/utils/view.py targets --sample 20   # Random 20
python3 src/utils/view.py targets --url         # Include URLs
python3 src/utils/view.py analyze               # Full analysis
```

---

## Development Principles

From `docs/learnings.md` - Key decision-making frameworks:

### Think Smart
- **Identify bottlenecks** - Optimize the constraint, not what's easy
- **Impact > Effort** - High-impact low-effort first (quick wins)
- **Critical path** - Do blocking work first, parallelize the rest

### Build Pragmatically
- **Simple first** - Complexity must be earned through necessity
- **Modular design** - Independent components, test in isolation
- **Time-box everything** - Exceeding budget is a signal to reassess

### Validate Early
- **Test assumptions** - Don't build on untested assumptions
- **Real feedback > theory** - Build smallest version, see what happens
- **Reversible decisions** - Structure work to change direction easily

### Avoid Traps
- Planning theater - Set "start building by [date]" deadline
- Solving hypothetical problems - Only solve encountered problems
- Premature optimization - Optimize for iteration speed first

---

## Key Learnings from MVP Build

### What Worked Well

**1. Profile-based personalization beats templates**
- Creating `profile.json` from resume made messages more authentic
- Claude API generates better content when given user context
- Mentioning the automation project itself is meta and memorable

**2. Company name fallback for email domains**
- Many companies (fermat, n8n, hims-and-hers) don't have websites in DB
- Using company name to construct domain (e.g., `n8n.com`) better than generic `company.com`
- Users can still manually verify, but starting point is reasonable

**3. Priority contact flag critical**
- Separating decision-makers (founders/CEOs/CTOs) from other contacts saves time
- 17 priority contacts out of 73 total (23%) - focused outreach
- Much more likely to get responses from founders than general employees

**4. Manual review is valuable for MVP**
- Not auto-sending forces quality check
- User learns what good messages look like
- Easier to iterate on message quality before scaling

### What Didn't Work (Problems Encountered)

**1. Claude API model version confusion**
- Multiple model versions tried: `claude-3-5-sonnet-20241022`, `claude-3-5-sonnet-20240620`, `claude-3-5-sonnet-latest`
- All returned 404 errors
- Working version: `claude-3-opus-20240229` (but deprecated, EOL Jan 2026)
- **Lesson:** Need to check Anthropic docs for current model versions before coding

**2. Missing company websites hurts email accuracy**
- Only some companies have website field populated
- Email candidates less useful with generic domains
- **Solution implemented:** Company name fallback
- **Better solution:** Scrape/populate websites from ATS URLs or Google

**3. Job posting context is limited**
- Messages use job title/description as company context
- Doesn't capture company mission, recent news, or products
- **Future:** Scrape company about pages or use Google search for richer context

### Technical Decisions That Paid Off

**1. SQLite with separate tables for contacts and messages**
- Flexible schema allowed adding tables without migration headaches
- `is_priority` flag on contacts table made filtering easy
- Prepared for future response tracking

**2. Confidence scoring on email candidates**
- HIGH/MEDIUM/LOW helps user choose which email to try first
- Based on common patterns (first.last@ is usually right)
- Simple but effective

**3. Single outreach pipeline script**
- `prepare_outreach.py` does everything: select company, contact, generate message, emails
- One command gets you a complete package ready to send
- Easy to iterate and test

### Metrics That Matter

**Current performance:**
- 7,124 jobs scraped → 16 pending (0.22% pass rate)
- 10 companies contacted → 73 contacts found (7.3 avg per company)
- 73 total contacts → 17 priority (23% are decision-makers)

**What to track next:**
- Response rate (% who reply to outreach)
- Positive response rate (% interested in talking)
- Time to response (how long before they reply)
- Which message variations work best

---

## Key Design Decisions

### Why SQLite?
- Local-first design (no cloud dependency for MVP)
- Simple setup, no server required
- Sufficient for 10k+ jobs, 1k+ companies
- Easy to inspect/debug with CLI tools

### Why Direct ATS APIs?
- Clean JSON > HTML scraping (no parsing brittleness)
- Reliable structure (official APIs)
- Dynamic mapping system reusable across companies
- Ashby has public endpoints (no auth needed)

### Why Two-Stage Filtering?
- Regex pre-filter saves API costs (cheap, fast elimination)
- Claude API for nuanced decisions (accurate, worth the cost)
- 96.5% rejection shows pre-filter working well

### Why Google Search for Contacts?
- No LinkedIn API access needed
- Gets what we need (names, titles, LinkedIn URLs)
- Multi-strategy approach (website, team pages, profiles)
- Pragmatic over perfect (email guessing acceptable for MVP)

---

## Current Status & Next Steps

### ✅ Completed (Days 1-6)
- ✅ Database schema & initialization (5 tables: companies, jobs, target_jobs, contacts, messages)
- ✅ Ashby job scraper (7,124 jobs from 305 companies)
- ✅ Dynamic ATS mapping system
- ✅ Two-stage filtering (16 pending jobs identified with 0.22% pass rate)
- ✅ Contact discovery (73 contacts, 17 priority decision-makers)
- ✅ Message generation pipeline with Claude API
- ✅ Email candidate generation with confidence scoring
- ✅ Profile-based personalization (from resume)
- ✅ Database inspection & statistics tools

### 🔄 Ready for Testing (Day 7)
The complete end-to-end pipeline is built and ready for real-world testing:
1. Run `python3 src/outreach/prepare_outreach.py` to generate outreach package
2. Review generated message and email candidates
3. Manually send via LinkedIn or email
4. Track results and iterate

### 📋 Immediate Next Steps (Week 2)

**1. Data Quality Improvements** (Priority: HIGH)
- Populate missing company websites in database
  - Currently many show "Website: Not found"
  - Better websites → more accurate email domains
  - Can scrape from ATS URLs or Google search results
- Verify email patterns for key companies
  - Test a few high-priority emails manually
  - Learn actual patterns (some might use firstlast@domain, not first.last@)
- Add company descriptions/context to database
  - Current messages use job posting context only
  - Company mission/product would improve personalization

**2. Outreach Execution** (Priority: HIGH)
- Send first 5-10 outreach emails manually
  - Start with highest-priority contacts (founders at top companies)
  - Track: sent date, email used, response (yes/no), response time
  - Document what works vs. what doesn't
- A/B test message variations
  - Test with/without project mention
  - Test different CTAs (quick chat vs. learn more vs. apply)
  - Test message length (current 5-7 sent vs. shorter 3-4 sent)
- Track response rates by:
  - Contact type (founder vs. CTO vs. VP)
  - Company size (from employee count)
  - Message variation

**3. Pipeline Improvements** (Priority: MEDIUM)
- Add batch mode to `prepare_outreach.py`
  - Currently generates one random company
  - Add flag to generate 5-10 packages at once
  - Allows user to review and choose best options
- Create tracking script to log sent messages
  - After manually sending, run script to log to `messages` table
  - Track: message_text, sent_date, email_used, contact_id
  - Enables response rate analysis later
- Improve message quality
  - Current model: `claude-3-opus-20240229` (deprecated, EOL Jan 2026)
  - Need to find newer working model version
  - Experiment with prompt variations for better personalization

**4. Response Tracking System** (Priority: MEDIUM)
- Add `responses` table to database
  ```sql
  CREATE TABLE responses (
    id INTEGER PRIMARY KEY,
    message_id INTEGER,
    response_date TEXT,
    response_type TEXT, -- 'positive', 'negative', 'no_response'
    response_text TEXT,
    outcome TEXT -- 'interview_scheduled', 'rejected', 'ghosted', etc.
  )
  ```
- Create CLI tool to log responses as they come in
- Calculate metrics:
  - Response rate (% who reply)
  - Positive response rate (% interested)
  - Time to response (how long before they reply)
  - Outcome distribution

**5. Discovery Expansion** (Priority: LOW)
- Discover contacts for remaining companies
  - Currently only 10 companies have contacts
  - 6 more companies with pending jobs need contact discovery
- Add more contact sources beyond Google Search
  - Crunchbase for founder info
  - Company about pages (scrape team section)
  - GitHub for engineering contacts
- Improve priority detection
  - Current: simple keyword matching ("founder", "CEO", "CTO")
  - Better: consider company size, role seniority

### 🚀 Future Enhancements (Post-MVP)

**Scalability:**
- Add more ATS platforms (Greenhouse, Lever, Workday)
- Automate daily re-scraping (cron job for new postings)
- Scale to 1000+ companies

**Automation:**
- Email verification before sending (hunter.io, clearbit, etc.)
- Automated email sending (with safeguards)
- Auto follow-ups after N days of no response
- LinkedIn connection requests (if no email found)

**Intelligence:**
- Learn from responses (which messages work best)
- Personalization improvements (company research, recent news)
- Contact prioritization (who's most likely to respond)
- Timing optimization (best time to send)

**Integrations:**
- Gmail/Outlook API for direct sending
- LinkedIn API for automated connection requests
- Notion/Airtable for kanban-style application tracking
- Calendar integration for interview scheduling

---

## Environment Setup

### Required API Keys (in `.env`)

```bash
ANTHROPIC_API_KEY=sk-ant-...    # For job filtering & message generation
GOOGLE_API_KEY=...              # For contact discovery
GOOGLE_CSE_ID=...               # Custom Search Engine ID
```

### Python Environment

**Uses `env/` (NOT `venv/`)**
- Managed by `direnv` (`.envrc` auto-sources `env/bin/activate`)
- Python 3.13
- Dependencies: requests, anthropic, tabulate, beautifulsoup4, python-dotenv

### Installation

```bash
# Create virtual environment
python3 -m venv env

# Install dependencies (activate env first)
source env/bin/activate
pip install requests anthropic tabulate beautifulsoup4 python-dotenv

# Or if direnv is configured
direnv allow
pip install requests anthropic tabulate beautifulsoup4 python-dotenv
```

### Shell Configuration Notes

**Important:** This system uses `zsh` with `rm` aliased to `trash` for safer file deletion. This prevents accidental permanent deletion of files. If you need to permanently delete something, use `/bin/rm` directly.

---

## Sample Output

### Pending Jobs (make targets)
```
Company              Title                                     Score
1password           Junior Rust Developer                      0.95
anima               Intern/New Grad Software Engineer          1.00
column              Payment Operations (New Grad 2026)         0.95
fermat              Software Engineer, New Grad                1.00
hims-and-hers       Jr. Developer (R&D, Formulations)          0.90
```

### Filter Results
```
✓ Pending (to apply):     16 (0.2%)
✗ Not relevant:           6876 (99.8%)
⊙ Reviewed (skipped):     0 (0.0%)
✉ Applied:                0 (0.0%)

Average score (relevant): 0.96
Average score (rejected): 0.09
```

---

## Troubleshooting

### Database Issues
```bash
# Reset database completely
make clean
make init
make load

# Just clear data (keep schema)
make purge
```

### API Rate Limits
- Claude API: Tier-based limits, batch requests in `filter_jobs.py`
- Google Search: 100 queries/day on free tier

### Missing Jobs
- Check company in `ashby_companies.txt`
- Verify company actually uses Ashby ATS
- Check `jobs` table for raw data before filtering

---

## Contributing / Iteration Notes

### For Future Claude Sessions

**What to read first:**
1. This README (architecture, status, key decisions)
2. `docs/learnings.md` (decision-making principles)
3. `make targets` output (current data state)

**Common tasks:**
- Add new ATS platform: Update `ats_mapper.py` and `ats_mappings.json`
- Adjust filter criteria: Edit prompts in `filter_jobs.py`
- Add contact sources: Extend `discover_contacts.py`
- New database queries: Add to `view.py`

**Key files to understand:**
- `src/utils/constants.py` - Status codes & labels
- `src/scrapers/ats_mapper.py` - How dynamic mapping works
- `src/filters/filter_jobs.py` - AI filtering logic
- `Makefile` - All available commands

---

## License & Usage

Personal project for job search automation. Not for redistribution or commercial use.

---

**Last Updated:** 2026-01-01 (All commits pushed to GitHub)
**Project Start:** 2025-12-26
**Days Elapsed:** 6/7 (MVP complete, ready for testing)
**Repository:** https://github.com/mokadoe/justin-job-apps
