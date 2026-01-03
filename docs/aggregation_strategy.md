# Job Aggregation Strategy

**Date:** 2026-01-03
**Status:** Planned for implementation

---

## Executive Summary

**Current situation:**
- Pass rate: 0.22% (16 jobs from 7,124)
- Need 450+ jobs scraped per relevant match
- **Problem:** Too few jobs at top of funnel
- **Solution:** Expand from Ashby-only to multiple sources

**Recommended approach:** Bottom-up discovery (Google dorking + ATS APIs) supplemented with aggregators

**Expected outcome:** 40,000-100,000 jobs → 80-220 relevant new grad matches

---

## Approach Comparison

### Bottom-Up Discovery

**Architecture:**
1. Dork each major ATS: `site:greenhouse.io`, `site:lever.co`, `site:ashbyhq.com`
2. Extract company subdomains/slugs
3. Poll public APIs daily for job updates
4. Let AI filter handle the volume

**Pros:**
- Comprehensive (70-80% coverage of tech jobs)
- Passive discovery (finds companies you didn't know about)
- Scales to thousands of companies easily
- Works well with AI filtering (designed to handle volume)

**Cons:**
- Higher initial setup effort
- Requires good filtering to manage noise

**Best for:**
- Maximizing number of relevant jobs found
- Finding rare/niche roles (chemistry+CS)
- Building comprehensive job database

### Top-Down Curation

**Architecture:**
1. Curate list of 50-200 target companies
2. Check their careers pages individually
3. Monitor only pre-selected companies

**Pros:**
- Low noise (only companies you care about)
- Fast time to first value
- Simple to implement
- Quality over quantity

**Cons:**
- Limited coverage (5% of companies have new grad matches)
- Requires manual research to identify target companies
- May miss unexpected opportunities
- Harder to scale past a few hundred companies

**Best for:**
- Highly targeted job search
- Clear company preferences
- Supplement to bottom-up approach

---

## Analysis: Why Bottom-Up Makes Sense for This Use Case

### 1. **The Math Doesn't Lie**

**Current reality:**
- 305 companies (Ashby only)
- 7,124 jobs scraped
- 16 pending matches
- **Pass rate: 0.22%** (1 match per 445 jobs)

**To find 100 relevant jobs:**
- Need to scrape: 100 ÷ 0.0022 = **~45,000 jobs**
- From companies: 45,000 ÷ 23 avg jobs/company = **~2,000 companies**

**You cannot manually curate 2,000 companies.** You need discovery automation.

### 2. **New Grad Roles Are Rare and Unpredictable**

From database analysis:
- Only **7 jobs** explicitly say "New Grad" (0.1% of all jobs)
- Only **5% of companies** have new grad matches
- **Chemistry+CS roles** are even rarer (estimated <0.05% of all tech jobs)

**Implication:** You can't predict which companies will have relevant roles. You need comprehensive coverage.

### 3. **Your AI Filter Can Handle Volume**

**Current filter:**
- Uses Claude Haiku (~$1 per 7,000 jobs)
- Already has strict criteria (96.5% rejection rate)
- **New description-based filter:** Even better at finding hidden matches

**Cost at scale:**
- 100,000 jobs × $0.01/job = **$1,000 filtering cost**
- Result: 220 relevant matches
- **$4.50 per qualified lead** (cheaper than any recruiter)

### 4. **The Chemistry Advantage Requires Breadth**

Justin's **CS + Chemistry** background is rare. Target roles include:
- "Computational Chemist" at Schrödinger
- "ML Engineer, Drug Discovery" at Insitro
- "Software Engineer, Biotech" at random startups
- "Cheminformatics Scientist" at niche companies

**These roles appear at unpredictable companies.** You can't curate for this—you need to cast a wide net and let the filter find them.

---

## Implementation Plan

### Phase 1: Core ATS Expansion (Week 1)

**Goal:** Add Greenhouse and Lever to capture 60-70% of market

**Steps:**
1. **Dork for companies:**
   ```
   site:greenhouse.io
   site:lever.co
   ```
2. **Extract company subdomains** from results
3. **Add to ats_mappings.json** (similar to Ashby)
4. **Run load pipeline:** `make load`
5. **Filter with new description analysis:** `make filter`

**Expected result:**
- +15,000 jobs from Greenhouse (35-40% of market)
- +10,000 jobs from Lever (25-30% of market)
- **Total: ~32,000 jobs → ~70 relevant matches**

**Cost:**
- Google dorking: $5-10 (one-time)
- Haiku filtering: ~$3 for 25,000 new jobs
- **Total: ~$15 one-time cost**

---

### Phase 2: Aggregators (Week 2)

**Goal:** Fill gaps from Workday/Taleo and other platforms

**Aggregators to integrate:**

| Aggregator | API | Coverage | Cost |
|------------|-----|----------|------|
| **Adzuna** | Free (250 calls/month) | Good international + US | Free |
| **Simplify Jobs** | Already have | Tech startups | Free |
| **HN "Who's Hiring"** | Parseable | Monthly threads | Free |
| **Wellfound (AngelList)** | API available | Startup-focused | Free tier |
| **Y Combinator** | Web scrape | YC companies | Free |

**Expected result:**
- +30,000 jobs from aggregators
- Captures Workday/Taleo jobs we can't scrape directly
- **Total with Phase 1: ~62,000 jobs → ~135 relevant matches**

**Cost:** Mostly free (API limits sufficient for weekly polling)

---

### Phase 3: Chemistry Sector (Week 3)

**Goal:** Capture Justin's differentiated channel (chem+CS roles)

**Sources:**

| Platform | Type | Estimated Jobs | Priority |
|----------|------|----------------|----------|
| **BioSpace** | Biotech job board | 1,000+ | High |
| **ACS Careers** | Chemistry-specific | 500+ | High |
| **Tier 1 Biotech** | Direct scraping | 200+ | Medium |
| **Science Careers** | Academic + industry | 500+ | Medium |

**Expected result:**
- +2,000 biotech/pharma jobs
- ~10-20 chemistry-relevant roles (high value)
- **Total: ~64,000 jobs → ~145 relevant matches**

**Cost:** ~$20 (BioSpace API if needed, otherwise free)

---

## Success Metrics

### Current State (Ashby Only)
- **Companies:** 304
- **Jobs:** 7,079
- **Matches:** 7 explicit "New Grad" jobs (0.1%)
- **Coverage:** 15-20% of tech job market

### Phase 1 Target (+ Greenhouse + Lever)
- **Companies:** ~1,500
- **Jobs:** ~32,000
- **Expected matches:** ~70 (0.22% pass rate)
- **Coverage:** 60-70% of tech job market

### Phase 2 Target (+ Aggregators)
- **Companies:** ~2,000
- **Jobs:** ~62,000
- **Expected matches:** ~135 (0.22% pass rate)
- **Coverage:** 80-90% of tech job market (including Workday/Taleo via aggregators)

### Phase 3 Target (+ Chemistry Sector)
- **Companies:** ~2,200
- **Jobs:** ~64,000
- **Expected matches:** ~145 (including high-value chem+CS roles)
- **Coverage:** 85%+ of addressable market for CS new grads

### With New Description-Based Filtering
- **Improved pass rate:** 0.22% → 0.7-1.4% (3-6x improvement)
- **Phase 3 with description filtering:** 64,000 jobs → **450-900 matches**
- **Realistic target:** 200-400 high-quality new grad roles

---

## Cost Analysis

### One-Time Costs
- Google dorking (discovery): $5-10
- Initial API setup: $0 (public endpoints)
- **Total one-time: ~$10**

### Ongoing Costs (Monthly)
- **Filtering:** 60,000 jobs/month × $0.01/job = **$600/month**
- API polling: $0 (free public endpoints)
- Google Search (contact discovery): ~$10/month (within free tier)
- **Total monthly: ~$610**

### Cost Per Qualified Lead
- 400 relevant jobs ÷ $610 = **$1.50 per qualified lead**
- Compared to:
  - Recruiters: $1,000-3,000 per placement
  - Job boards: $50-200/month with manual searching
  - LinkedIn Premium: $40/month + manual effort

**Verdict:** Extremely cost-effective at scale.

---

## Hybrid Approach (Recommended)

**Start bottom-up, supplement with top-down:**

1. **Phase 1:** Bottom-up discovery (Greenhouse + Lever + Ashby)
   - Goal: Comprehensive coverage, find unexpected opportunities
   - Expected: 30,000+ jobs → 60-140 relevant matches

2. **Phase 2:** Add aggregators (Adzuna, Simplify, HN)
   - Goal: Fill gaps from Workday/Taleo
   - Expected: +30,000 jobs → +60 matches

3. **Phase 3:** Targeted curation (chemistry sector)
   - Goal: Focus on high-value niche (BioSpace, ACS Careers)
   - Expected: +2,000 jobs → +10-20 high-value matches

**This combines:**
- Breadth (bottom-up) for discovering rare roles
- Depth (top-down) for high-priority sectors like chemistry+CS

---

## Next Steps

1. **This Weekend:** Implement Greenhouse scraper
   - Dork for companies: `site:greenhouse.io`
   - Add to ats_mappings.json
   - Test with 10 companies
   - Scale to all discovered companies

2. **Next Week:** Add Lever scraper
   - Same process as Greenhouse
   - Run full pipeline with both platforms

3. **Week After:** Integrate first aggregator (Adzuna or Simplify enhancement)

4. **Week 3:** Add BioSpace for chemistry sector

**Goal:** 10x the matches within 3 weeks (from 16 → 160+ relevant jobs)

---

## Conclusion

**Recommended strategy: Bottom-up discovery with targeted supplementation**

**Why this works:**
- ✅ Solves the actual bottleneck (too few jobs at top of funnel)
- ✅ Leverages AI filtering strength (designed for volume)
- ✅ Captures rare chemistry+CS roles (requires breadth)
- ✅ Cost-effective at scale ($1.50/lead vs. $1000s for recruiters)
- ✅ Flexible (can add targeted curation for specific sectors)

**The math:** Need 45,000+ jobs to find 100 matches. Bottom-up discovery scales to this volume efficiently.

**Next step:** Start with Phase 1 (Greenhouse + Lever) to 10x job count and validate the approach.
