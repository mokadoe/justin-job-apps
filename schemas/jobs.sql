-- Companies table
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    ats_platform TEXT NOT NULL,
    ats_url TEXT,
    website TEXT,
    last_scraped TEXT,
    is_active BOOLEAN DEFAULT 1,
    discovered_date TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Jobs table
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    job_url TEXT UNIQUE NOT NULL,
    job_title TEXT NOT NULL,
    job_description TEXT,
    location TEXT,
    evaluated BOOLEAN DEFAULT 0,
    discovered_date TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id)
);

-- Target jobs table (filtered jobs to apply to)
-- Status: 0=not_relevant, 1=pending, 2=reviewed, 3=applied
CREATE TABLE IF NOT EXISTS target_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL UNIQUE,
    relevance_score REAL,
    match_reason TEXT,
    status INTEGER DEFAULT 1,
    added_date TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

-- Contacts table (key people at companies)
-- is_priority: 1=founder/CEO/CTO (decision maker), 0=other engineering leadership
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    title TEXT,
    linkedin_url TEXT,
    is_priority BOOLEAN DEFAULT 0,
    discovered_date TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id),
    UNIQUE(company_id, name)
);

-- Messages table (generated outreach messages)
-- Stores personalized messages for each company
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    message_text TEXT NOT NULL,
    company_research TEXT,
    generated_date TEXT DEFAULT CURRENT_TIMESTAMP,
    sent_date TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id),
    UNIQUE(company_id)
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_job_url ON jobs(job_url);
CREATE INDEX IF NOT EXISTS idx_company_id ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_evaluated ON jobs(evaluated);
CREATE INDEX IF NOT EXISTS idx_company_name ON companies(name);
CREATE INDEX IF NOT EXISTS idx_ats_platform ON companies(ats_platform);
CREATE INDEX IF NOT EXISTS idx_target_job_id ON target_jobs(job_id);
CREATE INDEX IF NOT EXISTS idx_status ON target_jobs(status);
CREATE INDEX IF NOT EXISTS idx_contact_company ON contacts(company_id);
CREATE INDEX IF NOT EXISTS idx_contact_priority ON contacts(is_priority);
CREATE INDEX IF NOT EXISTS idx_message_company ON messages(company_id);
