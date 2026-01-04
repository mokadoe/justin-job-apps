# Job Application Automation Pipeline

> Automated system to discover new grad software engineering jobs, filter with AI, and track applications.

**🔗 Repository:** https://github.com/mokadoe/justin-job-apps

**📊 Status:** Cupcake In Progress - Core pipeline works, needs job browsing + mark-as-applied

**💻 Tech Stack:** Python 3.13, SQLite/PostgreSQL, Claude API, FastAPI + Railway

---

## 📌 Cupcake: Minimum Useful Product

The cupcake is the minimum for this to be actually useful:

| Requirement | Status | How |
|-------------|--------|-----|
| 1. Discover & scrape jobs | ✅ Done | `/scrape ashby`, `/scrape simplify` |
| 2. AI filter & rank jobs | ✅ Done | `/filter` (Haiku + Sonnet two-stage) |
| 3. Browse ranked jobs with URLs | ⚠️ Partial | `/jobs pending` shows 20 max, no URLs |
| 4. Mark jobs as applied/skipped | ❌ Missing | Need `/jobs mark` command |

### What's Blocking Cupcake

1. **`/jobs pending` is limited** - Shows 20 jobs, no URLs, can't paginate
2. **No mark command** - Can't cross off jobs when you apply

### To Complete Cupcake

```bash
# 1. Add /jobs list command with full output + URLs
# 2. Add /jobs mark <id> applied|skipped command
```

---

## Two Interfaces

### 1. Web Agent (Primary) - Railway

**URL:** https://justin-job-apps-production.up.railway.app

Chat interface with slash commands. This is the main way to use the system.

```
/scrape ashby              # Fetch jobs from all Ashby companies
/scrape simplify           # Discover companies from SimplifyJobs GitHub
/scrape yc                 # Discover YC companies
/filter                    # Run AI filter (Haiku + Sonnet)
/filter 100                # Filter first 100 jobs only
/jobs stats                # Database statistics
/jobs pending              # Show pending target jobs
```

### 2. CLI (Development) - Local

```bash
make init          # Initialize database
make load          # Alias for scrape (local only)
make filter        # Run filter
make targets       # View pending jobs
make targets --pending --url   # With URLs
```

**Note:** CLI uses local SQLite. Set `USE_REMOTE_DB=true` to use Railway PostgreSQL.

---

## Current State (Jan 4, 2026)

Run `/jobs stats` in the agent to see actual numbers. The stats below are from the last run:

- **Companies:** ~300+ (Ashby) + aggregator discoveries
- **Jobs scraped:** ~7,000+
- **Jobs filtered:** Depends on last `/filter` run
- **Pass rate:** ~4% with two-stage filter

### What's Actually Working

| Feature | Agent Command | Status |
|---------|---------------|--------|
| Discover from Simplify | `/scrape simplify` | ✅ |
| Discover from YC | `/scrape yc` | ✅ |
| Discover from a16z | `/scrape a16z` | ✅ |
| Discover from manual list | `/scrape manual` | ✅ |
| Scrape Ashby jobs | `/scrape ashby` | ✅ |
| AI filter (Haiku+Sonnet) | `/filter` | ✅ |
| View stats | `/jobs stats` | ✅ |
| View pending jobs | `/jobs pending` | ⚠️ Limited to 20 |
| Browse all jobs with URLs | - | ❌ Missing |
| Mark as applied | - | ❌ Missing |
| Contact discovery | CLI only | ✅ (not in agent) |
| Message generation | CLI only | ✅ (not in agent) |

### What's NOT Working / Missing

1. **Job browsing is limited** - `/jobs pending` shows 20 jobs max, no URLs
2. **No mark command** - Can't track which jobs you've applied to
3. **Contact/message commands not in agent** - Have to use CLI

---

## Quick Start (Agent)

1. Go to https://justin-job-apps-production.up.railway.app
2. Start a new chat
3. Run these commands:

```
/jobs stats                # See current state
/scrape ashby              # Fetch latest jobs (skip if recently done)
/filter                    # Run AI filter
/jobs pending              # See top results
```

---

## Quick Start (CLI)

```bash
# Setup
pip install -r requirements.txt
cp .env.example .env  # Add your API keys

# Pipeline
make init              # Create database
make simplify          # Discover companies
make load              # Scrape Ashby jobs
make filter            # AI filter
make targets --url     # View with URLs
```

---

## Architecture

### Pipeline

```
Discover → Scrape → Filter → [Browse → Apply → Track]
   ✅        ✅       ✅        ⚠️      ❌       ❌
```

### Data Sources

| Source | Command | Status |
|--------|---------|--------|
| Ashby ATS | `/scrape ashby` | ✅ Primary |
| SimplifyJobs GitHub | `/scrape simplify` | ✅ Discovery |
| Y Combinator | `/scrape yc` | ✅ Discovery |
| a16z Portfolio | `/scrape a16z` | ✅ Discovery |
| Manual list | `/scrape manual` | ✅ Discovery |

### Database (5 tables)

- `companies` - Company metadata, ATS platform, scrape status
- `jobs` - All scraped jobs, evaluated flag
- `target_jobs` - Filtered jobs with score, priority, status
- `contacts` - Decision makers (CLI only for now)
- `messages` - Outreach messages (CLI only for now)

### File Structure

```
justin-job-apps/
├── agent/                # Railway deployment (FastAPI + Claude Agent SDK)
│   ├── main.py           # Server + embedded HTML frontend
│   ├── jobs_db.py        # SQLAlchemy async DB layer
│   ├── commands/         # Slash command handlers
│   └── spec.md           # Agent documentation
│
├── src/                  # Source code (CLI)
│   ├── scrapers/         # Job scraping (Ashby API)
│   ├── filters/          # AI filtering (Haiku + Sonnet)
│   ├── discovery/        # Company aggregators
│   └── utils/            # Database abstraction, CLI tools
│
├── data/                 # SQLite database (local only, gitignored)
├── schemas/              # SQL schema definitions
└── docs/                 # Additional documentation
```

---

## Two-Stage Filtering

```
Regex → Haiku → Sonnet
 72%     24%      4%
reject  reject   accept
```

1. **Regex** (free): Reject senior roles, non-engineering
2. **Haiku** (~$1/7K jobs): Analyze descriptions, ACCEPT/REVIEW/REJECT
3. **Sonnet** (~$5/400 jobs): Review borderlines with your `profile.json`

**Result:** ~4% pass rate, sorted by score, priority 1 (US) vs 3 (non-US)

---

## Environment

```bash
# .env file
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
GOOGLE_CSE_ID=...
DATABASE_URL=postgresql://...  # Optional: Railway PostgreSQL
USE_REMOTE_DB=true             # Optional: Use PostgreSQL instead of SQLite
```

---

## Next Steps: Complete the Cupcake

1. **Add `/jobs list` command** - Show all pending jobs with URLs, pagination
2. **Add `/jobs mark` command** - Mark jobs as `applied` or `skipped`

After cupcake:
- Contact discovery in agent
- Message generation in agent
- Response tracking

---

**Last Updated:** 2026-01-04
**Repository:** https://github.com/mokadoe/justin-job-apps
