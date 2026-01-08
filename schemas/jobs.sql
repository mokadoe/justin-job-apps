-- Companies table
-- ats_platform = 'unknown' indicates leads that need ATS discovery
-- discovery_source: where we found this company (simplify, google, manual)
-- ats_platform: which ATS they use (ashbyhq, greenhouse, lever, unknown)
-- ats_slug: the URL-friendly identifier for their careers page
-- employee_count: number of employees (from LinkedIn or manual entry)
-- employee_count_source: 'linkedin', 'manual', 'job_proxy' (how we got the count)
-- contacts_searched_at: when we last attempted contact discovery (even if none found)
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    discovery_source TEXT DEFAULT 'manual',
    ats_platform TEXT,
    ats_slug TEXT,
    ats_url TEXT,
    website TEXT,
    employee_count INTEGER,
    employee_count_source TEXT,
    contacts_searched_at TEXT,
    last_scraped TEXT,
    is_active BOOLEAN DEFAULT 1,
    discovered_date TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Jobs table
-- source: 'ats_scrape' (default), 'simplify', 'linkedin', etc.
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    job_url TEXT UNIQUE NOT NULL,
    job_title TEXT NOT NULL,
    job_description TEXT,
    location TEXT,
    posted_date TEXT,
    evaluated BOOLEAN DEFAULT 0,
    discovered_date TEXT DEFAULT CURRENT_TIMESTAMP,
    source TEXT DEFAULT 'ats_scrape',
    FOREIGN KEY (company_id) REFERENCES companies(id)
);

-- Target jobs table (filtered jobs to apply to)
-- Status: 0=not_relevant, 1=pending, 2=reviewed, 3=applied
-- Priority: 1=high (US), 2=medium, 3=low (non-US but relevant)
CREATE TABLE IF NOT EXISTS target_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL UNIQUE,
    relevance_score REAL,
    match_reason TEXT,
    status INTEGER DEFAULT 1,
    priority INTEGER DEFAULT 1,
    is_intern BOOLEAN DEFAULT 0,
    experience_analysis TEXT,
    added_date TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

-- Contacts table (key people at companies)
-- is_priority: 1=founder/CEO/CTO (decision maker), 0=other engineering leadership
-- match_confidence: 'high' (exact company match), 'medium' (likely match)
-- person_context: snippet about the person from web search (for message personalization)
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    title TEXT,
    linkedin_url TEXT,
    is_priority BOOLEAN DEFAULT 0,
    match_confidence TEXT DEFAULT 'medium',
    person_context TEXT,
    context_source TEXT,
    discovered_date TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id),
    UNIQUE(company_id, name)
);

-- Messages table (generated outreach messages)
-- Stores personalized messages for each (company, job, contact) combination
-- contact_id can be NULL if no priority contact exists for the company
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    contact_id INTEGER,
    message_text TEXT NOT NULL,
    company_research TEXT,
    generated_date TEXT DEFAULT CURRENT_TIMESTAMP,
    sent_date TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id),
    FOREIGN KEY (job_id) REFERENCES jobs(id),
    FOREIGN KEY (contact_id) REFERENCES contacts(id),
    UNIQUE(company_id, job_id, contact_id)
);

-- Outreach table (tracks individual outreach attempts)
-- Supports multiple attempts per company (different contacts, retries, follow-ups)
-- Status: draft, sent, bounced, replied, no_response
CREATE TABLE IF NOT EXISTS outreach (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    contact_id INTEGER NOT NULL,
    email_used TEXT,
    message_text TEXT NOT NULL,
    status TEXT DEFAULT 'draft',
    generated_date TEXT DEFAULT CURRENT_TIMESTAMP,
    sent_date TEXT,
    response_date TEXT,
    response_text TEXT,
    notes TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id),
    FOREIGN KEY (contact_id) REFERENCES contacts(id)
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_job_url ON jobs(job_url);
CREATE INDEX IF NOT EXISTS idx_company_id ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_evaluated ON jobs(evaluated);
CREATE INDEX IF NOT EXISTS idx_posted_date ON jobs(posted_date);
CREATE INDEX IF NOT EXISTS idx_company_name ON companies(name);
CREATE INDEX IF NOT EXISTS idx_ats_platform ON companies(ats_platform);
CREATE INDEX IF NOT EXISTS idx_discovery_source ON companies(discovery_source);
CREATE INDEX IF NOT EXISTS idx_ats_slug ON companies(ats_slug);
CREATE INDEX IF NOT EXISTS idx_target_job_id ON target_jobs(job_id);
CREATE INDEX IF NOT EXISTS idx_status ON target_jobs(status);
CREATE INDEX IF NOT EXISTS idx_contact_company ON contacts(company_id);
CREATE INDEX IF NOT EXISTS idx_contact_priority ON contacts(is_priority);
CREATE INDEX IF NOT EXISTS idx_message_company ON messages(company_id);
CREATE INDEX IF NOT EXISTS idx_message_job ON messages(job_id);
CREATE INDEX IF NOT EXISTS idx_message_contact ON messages(contact_id);
CREATE INDEX IF NOT EXISTS idx_outreach_company ON outreach(company_id);
CREATE INDEX IF NOT EXISTS idx_outreach_contact ON outreach(contact_id);
CREATE INDEX IF NOT EXISTS idx_outreach_status ON outreach(status);
