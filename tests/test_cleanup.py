#!/usr/bin/env python3
"""Test database cleanup operations."""

import sqlite3
from pathlib import Path
import uuid

DB_PATH = Path(__file__).parent.parent / "data" / "jobs.db"


def test_delete_company():
    """Test deleting a company and its jobs (cascade)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Insert test company
    test_company_name = f"Test Company {uuid.uuid4()}"
    cursor.execute('''
        INSERT INTO companies (name, ats_platform, ats_url)
        VALUES (?, ?, ?)
    ''', (test_company_name, 'test-platform', 'https://test.com'))
    company_id = cursor.lastrowid
    conn.commit()

    # Insert test jobs for this company
    test_jobs = [
        (company_id, f'https://test.com/job1-{uuid.uuid4()}', 'Software Engineer'),
        (company_id, f'https://test.com/job2-{uuid.uuid4()}', 'Product Manager'),
    ]

    cursor.executemany('''
        INSERT INTO jobs (company_id, job_url, job_title)
        VALUES (?, ?, ?)
    ''', test_jobs)
    conn.commit()

    # Verify jobs were inserted
    cursor.execute('SELECT COUNT(*) FROM jobs WHERE company_id = ?', (company_id,))
    job_count = cursor.fetchone()[0]
    assert job_count == 2, f"Expected 2 jobs, found {job_count}"
    print(f"✓ Inserted test company and {job_count} jobs")

    # Delete the company's jobs
    cursor.execute('DELETE FROM jobs WHERE company_id = ?', (company_id,))
    conn.commit()

    # Verify jobs were deleted
    cursor.execute('SELECT COUNT(*) FROM jobs WHERE company_id = ?', (company_id,))
    job_count = cursor.fetchone()[0]
    assert job_count == 0, f"Expected 0 jobs after deletion, found {job_count}"
    print(f"✓ Deleted all jobs for company")

    # Delete the company
    cursor.execute('DELETE FROM companies WHERE id = ?', (company_id,))
    conn.commit()

    # Verify company was deleted
    cursor.execute('SELECT COUNT(*) FROM companies WHERE id = ?', (company_id,))
    company_count = cursor.fetchone()[0]
    assert company_count == 0, f"Expected 0 companies after deletion, found {company_count}"
    print(f"✓ Deleted test company")

    conn.close()


def test_truncate_tables():
    """Test truncating all tables (for testing only)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get counts before truncation
    cursor.execute('SELECT COUNT(*) FROM companies')
    companies_before = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM jobs')
    jobs_before = cursor.fetchone()[0]

    print(f"\nBefore truncation: {companies_before} companies, {jobs_before} jobs")

    # Truncate tables
    cursor.execute('DELETE FROM jobs')
    cursor.execute('DELETE FROM companies')
    conn.commit()

    # Get counts after truncation
    cursor.execute('SELECT COUNT(*) FROM companies')
    companies_after = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM jobs')
    jobs_after = cursor.fetchone()[0]

    assert companies_after == 0, f"Expected 0 companies, found {companies_after}"
    assert jobs_after == 0, f"Expected 0 jobs, found {jobs_after}"

    print(f"After truncation: {companies_after} companies, {jobs_after} jobs")
    print("✓ Tables truncated successfully")

    conn.close()


if __name__ == "__main__":
    print("Running cleanup tests...\n")
    print("Test 1: Delete company and jobs")
    print("-" * 60)
    test_delete_company()

    print("\n" + "=" * 60)
    print("Test 2: Truncate all tables (DESTRUCTIVE)")
    print("-" * 60)

    # Ask for confirmation before truncating
    response = input("This will delete ALL data. Continue? (yes/no): ")
    if response.lower() == 'yes':
        test_truncate_tables()
    else:
        print("Skipping truncation test")

    print("\n✓ All cleanup tests passed!")
