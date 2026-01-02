#!/usr/bin/env python3
"""
Simplify Jobs GitHub scraper - Extracts companies from New-Grad-Positions repo.

This scraper:
1. Fetches the README from SimplifyJobs/New-Grad-Positions
2. Parses HTML table to extract unique company names
3. Filters out companies already in our database
4. Outputs prospective companies to data/prospective_companies.txt
"""

import requests
import sqlite3
from bs4 import BeautifulSoup
from pathlib import Path


# Paths
REPO_URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md"
DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"
OUTPUT_PATH = Path(__file__).parent.parent.parent / "data" / "prospective_companies.txt"


def fetch_simplify_readme():
    """Fetch the raw README from Simplify Jobs repo."""
    print(f"Fetching README from {REPO_URL}...")
    response = requests.get(REPO_URL)
    response.raise_for_status()
    print(f"✓ Downloaded {len(response.text)} characters")
    return response.text


def parse_companies(html_content):
    """Parse HTML table and extract unique company names."""
    soup = BeautifulSoup(html_content, 'html.parser')

    # Find all table rows
    companies = set()
    rows = soup.find_all('tr')

    print(f"Found {len(rows)} table rows")

    for row in rows:
        cells = row.find_all('td')
        if not cells:
            continue  # Skip header rows

        # First cell is company name
        company_cell = cells[0]

        # Extract text and clean it
        # Company name might be in a link or plain text
        company_name = company_cell.get_text(strip=True)

        # Remove emoji and special characters from start
        company_name = company_name.lstrip('🔥🛂🇺🇸🔒🎓 ')

        if company_name and company_name.lower() != 'company':
            companies.add(company_name)

    print(f"✓ Extracted {len(companies)} unique companies")
    return sorted(companies, key=str.lower)


def get_existing_companies():
    """Query database for companies we already have."""
    if not DB_PATH.exists():
        print("⚠ Database not found, assuming no existing companies")
        return set()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM companies")
    existing = {row[0] for row in cursor.fetchall()}

    conn.close()

    print(f"✓ Found {len(existing)} companies in database")
    return existing


def save_prospective_companies(companies, existing_companies):
    """Save new prospective companies to file."""
    # Filter out companies already in DB (case-insensitive comparison)
    existing_lower = {name.lower() for name in existing_companies}
    new_companies = [c for c in companies if c.lower() not in existing_lower]

    print(f"\n{'='*60}")
    print(f"Total companies from Simplify: {len(companies)}")
    print(f"Already in database: {len(companies) - len(new_companies)}")
    print(f"New prospective companies: {len(new_companies)}")
    print(f"{'='*60}\n")

    # Create data directory if needed
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Write to file
    with open(OUTPUT_PATH, 'w') as f:
        f.write(f"# Prospective Companies from Simplify Jobs\n")
        f.write(f"# Source: {REPO_URL}\n")
        f.write(f"# Total: {len(new_companies)} companies\n")
        f.write(f"# Generated: {__import__('datetime').datetime.now().isoformat()}\n")
        f.write(f"#\n")
        f.write(f"# Note: Companies already in jobs.db are excluded from this list\n")
        f.write(f"#\n\n")

        for company in new_companies:
            f.write(f"{company}\n")

    print(f"✓ Saved to {OUTPUT_PATH}")

    # Also show first 20
    if new_companies:
        print(f"\nFirst 20 prospective companies:")
        for i, company in enumerate(new_companies[:20], 1):
            print(f"  {i:2d}. {company}")

        if len(new_companies) > 20:
            print(f"  ... and {len(new_companies) - 20} more")

    return new_companies


def main():
    """Main execution."""
    print("Simplify Jobs Company Scraper")
    print("="*60)

    # Fetch README
    readme_content = fetch_simplify_readme()

    # Parse companies
    all_companies = parse_companies(readme_content)

    # Get existing companies from DB
    existing_companies = get_existing_companies()

    # Save prospective companies (excluding existing ones)
    new_companies = save_prospective_companies(all_companies, existing_companies)

    print(f"\n✓ Done! New prospective companies saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
