#!/usr/bin/env python3
"""Test database functionality."""

import sqlite3
from pathlib import Path
import uuid

DB_PATH = Path(__file__).parent.parent / "data" / "jobs.db"

# Add src to path for imports if needed
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def cleanup_test_data(conn, test_urls):
    """Clean up test data from previous runs."""
    cursor = conn.cursor()
    for url in test_urls:
        cursor.execute('DELETE FROM jobs WHERE job_url = ?', (url,))
    conn.commit()

def test_insert_and_query():
    """Test inserting a job and querying it back."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Use unique identifiers to avoid conflicts
    test_company_name = f'Test Company {uuid.uuid4()}'
    test_url = f'https://jobs.lever.co/test-company/test-job-{uuid.uuid4()}'

    # Insert test company first
    cursor.execute('''
        INSERT INTO companies (name, ats_platform, ats_url)
        VALUES (?, ?, ?)
    ''', (test_company_name, 'lever', 'https://jobs.lever.co/test-company'))
    company_id = cursor.lastrowid
    conn.commit()

    # Insert test job
    cursor.execute('''
        INSERT INTO jobs (company_id, job_url, job_title, job_description, location)
        VALUES (?, ?, ?, ?, ?)
    ''', (company_id, test_url, 'Software Engineer', 'Test description', 'San Francisco, CA'))
    conn.commit()

    # Query it back
    cursor.execute('''
        SELECT j.*, c.name as company_name
        FROM jobs j
        JOIN companies c ON j.company_id = c.id
        WHERE j.job_url = ?
    ''', (test_url,))
    result = cursor.fetchone()

    # Cleanup
    cursor.execute('DELETE FROM jobs WHERE job_url = ?', (test_url,))
    cursor.execute('DELETE FROM companies WHERE id = ?', (company_id,))
    conn.commit()
    conn.close()

    # Verify
    assert result is not None, "Job not found in database"
    print("✓ Insert test passed")
    print(f"  Job ID: {result[0]}")
    print(f"  Company ID: {result[1]}")
    print(f"  Job Title: {result[3]}")
    print(f"  URL: {result[2]}")

def test_duplicate_prevention():
    """Test that duplicate URLs are rejected."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Use unique identifiers
    test_company_name = f'Duplicate Test Co {uuid.uuid4()}'
    test_url = f'https://jobs.lever.co/duplicate-test/job-{uuid.uuid4()}'

    # Insert test company
    cursor.execute('''
        INSERT INTO companies (name, ats_platform, ats_url)
        VALUES (?, ?, ?)
    ''', (test_company_name, 'lever', 'https://jobs.lever.co/duplicate-test'))
    company_id = cursor.lastrowid
    conn.commit()

    # Insert first time
    cursor.execute('''
        INSERT INTO jobs (company_id, job_url, job_title)
        VALUES (?, ?, ?)
    ''', (company_id, test_url, 'Engineer'))
    conn.commit()

    # Try to insert duplicate
    try:
        cursor.execute('''
            INSERT INTO jobs (company_id, job_url, job_title)
            VALUES (?, ?, ?)
        ''', (company_id, test_url, 'Engineer'))
        conn.commit()
        assert False, "Duplicate insert should have failed"
    except sqlite3.IntegrityError:
        print("✓ Duplicate prevention test passed")
        print(f"  Correctly rejected duplicate URL")

    # Cleanup
    cursor.execute('DELETE FROM jobs WHERE job_url = ?', (test_url,))
    cursor.execute('DELETE FROM companies WHERE id = ?', (company_id,))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    print("Running database tests...\n")
    test_insert_and_query()
    print()
    test_duplicate_prevention()
    print("\n✓ All tests passed!")
