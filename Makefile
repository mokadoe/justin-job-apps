.PHONY: help init load inspect targets analyze filter purge test clean

PYTHON := . env/bin/activate && python3

help:
	@echo "Available commands:"
	@echo "  make init      - Initialize database with schema"
	@echo "  make load      - Load jobs from ALL ATS platforms (Ashby, Lever, Greenhouse)"
	@echo "  make inspect   - Display all database contents"
	@echo "  make targets   - Show filtered jobs statistics and company breakdown"
	@echo "  make analyze   - Analyze jobs (locations, titles, keywords)"
	@echo "  make filter    - Filter jobs with Claude API (two-stage: Haiku + Sonnet)"
	@echo "  make purge     - Delete all data from tables (keeps schema)"
	@echo "  make clean     - Delete database file completely"
	@echo "  make test      - Run all tests"
	@echo ""
	@echo "Advanced: python3 src/utils/view.py targets --help"

init:
	@echo "Initializing database..."
	$(PYTHON) src/utils/init_db.py

load:
	@echo "Loading jobs from ALL ATS platforms (Ashby, Lever, Greenhouse)..."
	$(PYTHON) src/scrapers/load_all_jobs.py

inspect:
	@echo "Inspecting database..."
	$(PYTHON) src/utils/view.py db

analyze:
	@echo "Analyzing jobs..."
	$(PYTHON) src/utils/view.py analyze

filter:
	@echo "Filtering jobs with two-stage AI (Haiku + Sonnet)..."
	$(PYTHON) src/filters/filter_jobs.py

targets:
	@echo "Viewing target jobs statistics..."
	$(PYTHON) src/utils/view.py targets

purge:
	@echo "⚠️  WARNING: This will delete ALL data from the database!"
	@read -p "Are you sure? Type 'yes' to continue: " confirm && \
	if [ "$$confirm" = "yes" ]; then \
		$(PYTHON) -c "import sqlite3; conn = sqlite3.connect('data/jobs.db'); conn.execute('DELETE FROM target_jobs'); conn.execute('DELETE FROM jobs'); conn.execute('DELETE FROM companies'); conn.commit(); conn.close(); print('✓ All data purged')"; \
	else \
		echo "Purge cancelled"; \
	fi

clean:
	@echo "⚠️  WARNING: This will delete the entire database file!"
	@read -p "Are you sure? Type 'yes' to continue: " confirm && \
	if [ "$$confirm" = "yes" ]; then \
		rm -f data/jobs.db; \
		echo "✓ Database file deleted"; \
	else \
		echo "Clean cancelled"; \
	fi

test:
	@echo "Running tests..."
	$(PYTHON) tests/test_database.py
	@echo ""
	$(PYTHON) tests/test_ats_mapper.py
