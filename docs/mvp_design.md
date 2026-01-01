# Job Application Automation - MVP Design

## Overview

Automated pipeline to find job postings, discover recruiting contacts, and send personalized outreach messages.

**Core Principle:** Local-first, simple automation that runs daily. Build modular components that work independently.

**Tech Stack:** Python, SQLite, Claude API

## What I Need Help With

1. **Prompt engineering** - Message generation tone, personalization depth, different templates for founder vs. recruiter outreach
2. **Contact discovery strategy** - Viable approaches for programmatically finding decision-makers (founders, CTOs) at small startups

---

## What's Hardest

**Discovery Automation**

Most technically complex: Automate scraping multiple sources (GitHub repos, Y-Combinator), automatically detect which ATS platform companies use, build intelligent AI-powered parsing for different JSON structures, validate companies actively hiring, create ongoing pipeline.

**Why this is hardest:** Multiple moving parts, inconsistent data formats, need AI to auto-generate parsers for different JSON schemas.

**Contact Discovery - Biggest Pain Point**

I don't know how to do this yet. Startups don't have recruiters. Need to find founders, CTOs, or hiring managers, but no clear programmatic approach.

**Why this is critical:** Wrong person = no response. Entire pipeline fails if I can't find the right contacts.

---

## Implementation Components

### Job Scraping

**Why:** Need job data for roles and personalization. Enabling work for entire pipeline.

**Current Approach:**

- Direct ATS API access (Ashby public endpoint: `https://api.ashbyhq.com/posting-api/job-board/{company}`)
- Dynamic mapping system that stores field mappings per ATS platform in JSON
- Reusable extraction logic - define mapping once, use for all companies on that platform

**What's Working:**

- ✅ Ashby scraper fetching 100+ jobs from companies like OpenAI (449), Deel (214), Ramp (127)
- ✅ Clean, structured JSON data from API (no HTML parsing needed)
- ✅ Field mapping: job_title, job_url, location, company_name, ats_platform
- ✅ Ready to scale to all 369 Ashby companies

**Uncertainties:**

- Do most tech startups use ATS platforms? (Yes, at least for YC/funded companies)
- Need to expand to Greenhouse, Lever for broader coverage (future work)

---

### Discovery Automation

**Why:** Top of funnel. Without continuous discovery, pipeline dries up. Directly determines throughput.

**Current Approach (MVP):**

- Start with manual company lists (Ashby companies from various sources)
- Direct ATS API scraping (Ashby public API) - clean, structured JSON data
- Dynamic ATS mapping system - learn schema once per platform, reuse for all companies

**Trade-offs:** Manual discovery upfront, but automated extraction. Quality over quantity for MVP.

**Completed:**

- ✅ 369 Ashby companies identified
- ✅ Ashby API scraper built
- ✅ Dynamic mapping system working

**Next:** Add more companies to list, then automate discovery (GitHub scraping, YC directory) once initial pipeline proves effective.

---

### Re-scraping & State Management

**Why:** Jobs posted/filled constantly. Need continuous scraping while avoiding duplicate work.

**Approach:** Daily re-scraping. SQLite tracks jobs by URL. Batch query to find new vs. existing. Process only new jobs (contacts, messages, outreach). Track company-level state to avoid duplicate outreach.

**Uncertainties:**

- Is daily overkill? Could be weekly, but daily catches fast opportunities.
- What about removed jobs - filled or just unlisted?

---

### Contact Discovery

**This is my biggest pain point and where I need the most help.**

Targets don't have recruiters. Need to find founders, CTOs, or hiring managers. No clear programmatic path.

**Considering:** LinkedIn search (manual vs. automated), company team pages (AI parsing), email discovery services (Hunter.io, Apollo.io), or pattern guessing (first.last@domain).

**What I Don't Know:**

1. How to programmatically find decision-makers at small companies?
2. Is manual work for initial batch acceptable for MVP, then automate?
3. Do I need paid tools, or can free approaches work?
4. How do I validate who has hiring authority?
5. Fallback for companies with no public presence?

---

### Personalized Messages

**Why:** Message quality affects response rate. But good enough at scale beats perfect at small scale.

**Approach:** Scrape company /about pages for context. Use Claude API for message generation. Template-based for MVP, iterate based on responses. Different prompts for different contact types.

**Uncertainties:** Tone (professional vs. casual)? Personalization depth? Different templates per contact type?

**Need help with prompt engineering.**

---

### Data & Execution

**Data Storage:** SQLite for local state - simple, portable, can migrate to Postgres/cloud later if needed.

**Execution:** Local manual runs, automate with cron once stable. Cloud (Lambda) later if needed.

---

## Open Questions for Feedback

1. **Contact strategy (CRITICAL):** How do I find founders/CTOs at small startups programmatically? What's a viable MVP approach?
2. **Discovery scale:** Is initial GitHub + YC harvest sufficient to validate approach?
3. **Paid tools:** Worth investing in email discovery services early, or build free approach first?
4. **Scraping infrastructure:** Will local execution with JSON APIs work, or need cloud-based scraping from the start?

---

## Timeline

**Start Date: December 26, 2024**

### Days 1-3: Validate Discovery + Build Data Pipeline (Dec 26-28)

**What to build:**

- SQLite setup and schema ✅
- Build ATS scraper for Ashby (using public API) ✅
- Create dynamic ATS mapper that learns JSON structure and stores mappings ✅
- Test extraction pipeline with real companies ✅
- Database insertion and deduplication logic

**Success looks like:**

- Working Ashby API scraper that fetches job data ✅
- ATS mapper that stores platform-specific field mappings in JSON ✅
- Can extract jobs from multiple companies using stored mapping ✅
- Database contains job listings from at least 30-50 companies
- Can re-run script and see it correctly deduplicates (doesn't re-add same jobs)

**Decision point:** Pipeline working end-to-end? Data quality good enough to proceed?

---

### Days 4-5: Solve Contact Strategy (Dec 29-30)

**What to test:**

- Manual contact discovery for initial batch of companies
- Test approaches (LinkedIn, team pages, pattern guessing)
- Validate what works

**Success looks like:**

- Found contact info (name + email) for at least 10-15 companies
- Documented which approach worked for each (LinkedIn, team page, etc.)
- Email addresses generated using validated or reasonable patterns
- Clear sense of which strategy is most viable for scaling

**Decision point:** Can we find decision-makers consistently enough to proceed?

**Blocker:** If no viable approach emerges, need to rethink entire strategy before Day 6.

---

### Day 6: Message Generation + First Outreach (Dec 31)

**What to build:**

- Message generation with Claude API
- Generate messages for initial 10-15 companies with contacts
- Send first batch

**Success looks like:**

- Working message generation that incorporates company context
- At least 10 emails sent to real contacts
- Basic tracking in place (who was contacted, when, message content)
- Messages feel personalized, not generic templates

**Decision point:** Messages sent successfully? Good enough quality to iterate from here?

---

### Day 7+: Iterate & Scale (Jan 1+)

**What to figure out:**

- Establish feedback/reward loop: What metrics matter? Response rate? Interview rate?
- Define success criteria: What response rate means approach is working?
- Determine measurement cadence: How long to wait before evaluating (1 week? 2 weeks?)

**Based on results, prioritize:**

- Scale discovery if running low on companies
- Improve contact finding if success rate too low (<50% contact discovery)
- Refine messages if response rate too low (<5% responses)
- Automate working approaches (contact finding, message generation)
- Add tracking for responses, opens, conversions

**Working smart means:** Don't optimize what isn't broken. Identify the bottleneck (discovery? contacts? messages?) and fix that first.

---

## Future Considerations

### Discovery Expansion

- **GitHub repo scraping** - Parse SimplifyJobs/New-Grad-Positions HTML tables using BeautifulSoup to discover more companies
- **Y-Combinator directory scraper** - High-quality startup targets
- **Additional ATS platforms** - Greenhouse, Lever, Workday parsers
- **Multi-source aggregation** - Combine multiple discovery sources into unified pipeline

### Optimization & Scale

- Delivery optimization (send times, multi-channel)
- Tracking & observability (email opens, response tracking, dashboard)
- Filtering & prioritization (LLM-based job relevance scoring)
- Cloud deployment (Lambda, DynamoDB, SES)
- Automated re-scraping and freshness tracking
