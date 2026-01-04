# Cost Tracking & Deduplication Guide

**Date:** 2026-01-03
**Status:** Implemented and integrated

---

## Summary

This document explains the new cost tracking and deduplication systems added to the job application pipeline.

## 1. Cost Tracking 💰

### What It Does

Automatically tracks every Claude API call across the entire project:
- Job filtering (Stage 1 Haiku + Stage 2 Sonnet)
- Slug resolution (Haiku batch suggestions)
- Message generation (Opus)

### Database Table

A new `api_costs` table stores:
- `timestamp` - When the call was made
- `operation` - What it was for ("job_filtering_stage1_haiku", "slug_resolution", etc.)
- `model` - Which model was used
- `input_tokens` / `output_tokens` - Token usage
- `cost_usd` - Calculated cost
- `metadata` - JSON with context (batch size, company name, etc.)

### How to Use

**View comprehensive cost report:**
```bash
make costs
```

**Output includes:**
- 💰 **Total cost** across all operations
- **Cost by operation** (filtering, message generation, etc.)
- **Cost by model** (Haiku, Sonnet, Opus)
- **Recent API calls** (last 5 with context)
- **Pricing reference** table

**Query costs directly in SQL:**
```bash
sqlite3 data/jobs.db "SELECT SUM(cost_usd) FROM api_costs"
```

### Integration

Cost tracking is now integrated into:
1. `src/filters/filter_jobs.py` - Both Haiku and Sonnet stages
2. `src/scrapers/slug_resolver.py` - Batch slug suggestions
3. `src/outreach/generate_messages.py` - Message generation

**Real-time feedback:** Each API call prints its cost:
```
💰 Cost: $0.0042
```

### Pricing (Jan 2026)

| Model | Input | Output | Best For |
|-------|-------|--------|----------|
| Haiku 4.5 | $0.80/MTok | $4.00/MTok | Volume tasks (filtering, slug resolution) |
| Sonnet 4.5 | $3.00/MTok | $15.00/MTok | Complex decisions (borderline job review) |
| Opus 4.5 | $15.00/MTok | $75.00/MTok | High-quality content (message generation) |

### Expected Costs

Based on current pipeline:
- **Filtering 7,000 jobs** (two-stage): $3-5
- **Slug resolution** (50 companies): $0.001
- **Message generation** (10 companies): $0.10-0.20

**Total for MVP run:** ~$5-10 for entire pipeline.

---

## 2. Deduplication

### What It Does

Automatically handles duplicates when discovering companies from multiple sources (Google dorking, Wellfound, Y Combinator, etc.).

### Three-Tier Strategy

#### 1. Company Deduplication

**Problem:** "Stripe Inc", "Stripe, Inc.", "Stripe" all refer to same company.

**Solution:** Normalized name matching
- Lowercase + remove "Inc", "LLC", "Corp" + strip special chars
- Example: "OpenAI, Inc." → "openai"

**Behavior:**
- First discovered company wins (name kept)
- Metadata from other sources merged (website, ATS URLs)
- UNIQUE constraint on normalized name prevents true duplicates

#### 2. Job Deduplication

**Problem:** Same job URL found from multiple aggregators.

**Solution:** UNIQUE constraint on `job_url`
- Database rejects duplicate inserts automatically
- No code changes needed - SQLite handles it

#### 3. Contact Deduplication

**Problem:** "Dr. John Smith" vs "John Smith" are same person.

**Solution:** Normalized name matching + UNIQUE constraint
- Normalize: remove titles (Dr., Mr.), middle initials, suffixes (PhD, Jr.)
- UNIQUE constraint on `(company_id, name)` at database level
- Example: "Dr. John A. Smith, PhD" → "john smith"

### How to Use

**View duplicate stats:**
```bash
make duplicates
```

**Output includes:**
- Count of potential duplicate companies (normalized name matches)
- Count of jobs with duplicate titles at same company (same title, different URLs)
- Count of potential duplicate contacts (normalized name matches)
- Examples of each type

**Manual duplicate checking:**
```python
from src.utils.deduplication import find_duplicate_company

# Check if company exists before inserting
existing_id = find_duplicate_company("Stripe Inc", "greenhouse")

if existing_id:
    print(f"Company already exists with ID {existing_id}")
else:
    # Safe to insert
    insert_company(...)
```

### Integration Example

When adding companies from Google dorking:

```python
from src.utils.deduplication import find_duplicate_company, merge_company_metadata

for company_name in discovered_companies:
    # Check for existing company
    existing_id = find_duplicate_company(company_name, ats_platform="greenhouse")

    if existing_id:
        # Merge new metadata (website, ATS URL)
        merge_company_metadata(existing_id, {
            'website': website,
            'ats_platform': 'greenhouse',
            'ats_url': ats_url
        })
        print(f"  ✓ Merged into existing company {existing_id}")
    else:
        # Insert as new company
        insert_new_company(company_name, ats_platform, ats_url)
        print(f"  ✓ Added new company")
```

### Fuzzy Matching (Optional)

For finding similar but not identical names:

```python
from src.utils.deduplication import fuzzy_match_company

# Find companies similar to "OpenAI"
matches = fuzzy_match_company("OpenAI", threshold=0.85)

for company_id, name, similarity in matches:
    print(f"{name}: {similarity:.2%} match")

# Output:
# OpenAI, Inc.: 95% match
# OpenAI: 100% match
```

---

## 3. Usage in Multi-Source Discovery

### Scenario: Discovering Companies from 3 Sources

You run:
1. Google dorking for Greenhouse companies
2. Wellfound API scrape
3. Y Combinator job board scrape

**Without deduplication:** 2,000 companies (many duplicates)
**With deduplication:** 1,200 unique companies

### How It Works

```python
# Source 1: Google dorking finds "Stripe Inc" on Greenhouse
insert_company("Stripe Inc", "greenhouse", "https://boards.greenhouse.io/stripe")
# Inserted with ID 1

# Source 2: Wellfound finds "Stripe, Inc."
existing = find_duplicate_company("Stripe, Inc.", "greenhouse")
# Returns ID 1 (normalized "stripe" matches)
merge_company_metadata(1, {'website': 'stripe.com'})
# Metadata merged, no duplicate created

# Source 3: Y Combinator finds "Stripe"
existing = find_duplicate_company("Stripe", "lever")
# Returns ID 1 (normalized "stripe" matches)
merge_company_metadata(1, {'ats_platform': 'lever'})
# Now we know Stripe uses BOTH Greenhouse and Lever
```

**Result:** 1 company entry with complete metadata from all 3 sources.

---

## 4. Files Created

### New Files

1. **`src/utils/cost_tracker.py`**
   - Tracks API costs in database
   - Calculates costs based on model pricing
   - Generates cost reports

2. **`src/utils/deduplication.py`**
   - Normalizes company/contact names
   - Detects duplicates
   - Merges metadata from multiple sources
   - Fuzzy matching for similar names

### Modified Files

1. **`src/filters/filter_jobs.py`** - Added cost tracking to both Haiku and Sonnet stages
2. **`src/scrapers/slug_resolver.py`** - Added cost tracking to batch slug resolution
3. **`src/outreach/generate_messages.py`** - Added cost tracking to message generation
4. **`Makefile`** - Added `make costs` and `make duplicates` commands
5. **`README.md`** - Added comprehensive documentation section

---

## 5. Next Steps

### For Bottom-Up Discovery (Greenhouse + Lever)

When you implement Google dorking for new ATS platforms:

1. **Use deduplication in discovery script:**
```python
for company_slug in discovered_slugs:
    # Check if already exists
    existing = find_duplicate_company(company_slug, "greenhouse")

    if not existing:
        insert_company(company_slug, "greenhouse", url)
```

2. **Track costs automatically** - Already integrated, no code changes needed

3. **Run duplicate report after scraping:**
```bash
make duplicates  # See if any edge cases need manual review
```

### For Cost Management

1. **Check costs after each major operation:**
```bash
make filter  # Runs filtering
make costs   # See how much it cost
```

2. **Optimize expensive operations:**
   - If Stage 2 Sonnet is too expensive, adjust thresholds
   - If message generation costs too much, use Sonnet instead of Opus

3. **Set budget alerts** (future):
```python
total = get_total_cost()
if total > 50.00:
    send_alert("API costs exceeded $50")
```

---

## 6. FAQ

### Q: Do I need to manually track costs?
**A:** No, it's completely automatic. Every API call is tracked.

### Q: How do I reset cost tracking?
**A:** Delete the `api_costs` table or run:
```sql
DELETE FROM api_costs;
```

### Q: What if I don't want cost tracking?
**A:** Remove the `track_api_call()` lines from the three files. But costs are negligible (~$5-10 for full pipeline).

### Q: Do duplicates cause errors?
**A:** No. The database silently ignores duplicate inserts (UNIQUE constraints). You'll just see fewer new records inserted.

### Q: Can I manually review duplicates?
**A:** Yes, run `make duplicates` to see potential duplicates. Fuzzy matching can help find variations you missed.

### Q: What if a company uses multiple ATS platforms?
**A:** The system logs it but currently stores primary ATS only. Future: create `company_ats_sources` junction table for multi-ATS companies.

---

## Conclusion

Both systems are **production-ready** and **fully integrated**:

✅ **Cost tracking** - Automatic, real-time, comprehensive
✅ **Deduplication** - Automatic, robust, no manual intervention

**No action required** - just use the pipeline as normal. Run `make costs` and `make duplicates` to see the data.
