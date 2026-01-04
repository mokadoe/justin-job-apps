# Discovery System Notes

## Current State (2026-01-03)

### What Works
- `dork_ats.py` - Google dorking with parallelization, CLI args, direct DB insert
- Aggregators: `simplify_aggregator.py`, `yc_aggregator.py`
- Database split: `companies` (scrapable) vs `company_leads` (need ATS discovery)

### Database Status
- **companies**: 678 (all on supported ATS: ashbyhq/greenhouse/lever)
- **company_leads**: 1004 (unknown ATS, unsupported platforms like workday/icims)

---

## Google Dorking Limitations

### Hard Limit: 100 Results Per Query
Google Custom Search API caps at 100 results (10 pages max). This is a Google limitation with no workaround.

**Implications:**
- `site:jobs.ashbyhq.com` returns only top 100 most "relevant" URLs
- Popular companies with many jobs dominate results
- Smaller/newer companies get buried

### Strategies to Discover More Companies

1. **Query Variations** (not yet implemented)
   ```
   site:jobs.ashbyhq.com -inurl:openai -inurl:ramp  # exclude known
   site:jobs.ashbyhq.com inurl:/a                    # alphabetical
   site:jobs.ashbyhq.com after:2025-06-01            # recent only
   site:jobs.ashbyhq.com "new grad"                  # entry-level focused
   ```

2. **Alternative Search APIs**
   - Bing API: up to ~1000 results, different index
   - Brave Search API: up to ~1000 results
   - Common Crawl: unlimited historical data, free

3. **ATS Platform Directories**
   - Checked: No public sitemaps exist for Ashby/Greenhouse/Lever
   - Checked: No public customer directories with job board links
   - APIs require company slugs, don't list all companies

### Potential Improvements (TODO)

- [ ] Add `--exclude` flag to exclude known company slugs
- [ ] Add `--letter` flag for alphabetical queries (a-z = 26 queries × 100 = 2600 potential)
- [ ] Add `--keywords` flag for query variations
- [ ] Implement Bing API as alternative (higher limits)
- [ ] Consider Common Crawl for exhaustive historical discovery

---

## Data Quality Issues (Fixed)

These were fixed in the 2026-01-03 session:
- Emoji prefixes stripped from company names
- `ashby` → `ashbyhq` platform name normalized
- Duplicate entries merged (case-insensitive)
- `discovery_source` corrected for Simplify URLs
- Unsupported ATS moved to `company_leads` table

---

## Architecture

```
src/discovery/
├── dork_ats.py              # Google dorking (parallelized, CLI)
├── aggregators/
│   ├── simplify_aggregator.py  # Simplify Jobs GitHub
│   └── yc_aggregator.py        # Y Combinator Algolia API
└── DISCOVERY_NOTES.md       # This file

schemas/jobs.sql             # Includes company_leads table

data/dork_results/           # Raw JSON backups from dorking
```

## Usage

```bash
# Dork a single ATS (default 10 pages = 100 results max)
python3 src/discovery/dork_ats.py --ats ashbyhq
python3 src/discovery/dork_ats.py --ats lever --start-page 5
python3 src/discovery/dork_ats.py --ats greenhouse --max-pages 10

# Run aggregators
python3 src/discovery/aggregators/simplify_aggregator.py
python3 src/discovery/aggregators/yc_aggregator.py

# Via agent command
/scrape aggregator simplify
/scrape aggregator yc
```
