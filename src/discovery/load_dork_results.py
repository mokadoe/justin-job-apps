#!/usr/bin/env python3
"""
Load Google dorking results into companies table.

Reads from data/dork_results/companies_discovered.json and inserts
companies into the database with discovery_source='google_dork'.
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / 'data' / 'jobs.db'
INPUT_FILE = Path(__file__).parent.parent.parent / 'data' / 'dork_results' / 'companies_discovered.json'


def load_dork_results():
    """Load discovered companies from JSON into database."""

    if not INPUT_FILE.exists():
        print(f"Error: {INPUT_FILE} not found. Run dork_ats.py first.")
        return

    if not DB_PATH.exists():
        print(f"Error: {DB_PATH} not found. Run 'make init' first.")
        return

    print("Loading dorking results...")

    with open(INPUT_FILE) as f:
        companies = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    stats = {'total': len(companies), 'added': 0, 'skipped': 0}

    for company in companies:
        name = company['company_slug']
        ats_platform = company['ats_platform']
        ats_slug = company['ats_slug']
        ats_url = company['ats_url']
        is_active = company['is_active']

        # Check if exists
        cursor.execute("SELECT id FROM companies WHERE name = ?", (name,))
        if cursor.fetchone():
            stats['skipped'] += 1
        else:
            cursor.execute("""
                INSERT INTO companies (name, discovery_source, ats_platform, ats_slug, ats_url, is_active)
                VALUES (?, 'google_dork', ?, ?, ?, ?)
            """, (name, ats_platform, ats_slug, ats_url, is_active))
            stats['added'] += 1

    conn.commit()
    conn.close()

    print(f"Total: {stats['total']} | Added: {stats['added']} | Skipped: {stats['skipped']}")


if __name__ == '__main__':
    load_dork_results()
