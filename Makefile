.PHONY: help init load inspect targets analyze filter validate review purge test clean simplify costs duplicates

PYTHON := . env/bin/activate && python3

help:
	@echo "Available commands:"
	@echo "  make init      - Initialize database with schema"
	@echo "  make load      - Load jobs from ALL ATS platforms (Ashby, Lever, Greenhouse)"
	@echo "  make simplify  - Extract prospective companies from Simplify Jobs GitHub"
	@echo "  make inspect   - Display all database contents"
	@echo "  make targets   - Show filtered jobs statistics and company breakdown"
	@echo "  make analyze   - Analyze jobs (locations, titles, keywords)"
	@echo "  make filter    - Filter jobs with Claude API (description-based analysis)"
	@echo "  make review    - Review jobs marked as REVIEW (interactive)"
	@echo "  make validate  - Re-validate pending jobs with strict criteria"
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

simplify:
	@echo "Extracting companies from Simplify Jobs GitHub repo..."
	$(PYTHON) src/scrapers/simplify_scraper.py

inspect:
	@echo "Inspecting database..."
	$(PYTHON) src/utils/view.py db

analyze:
	@echo "Analyzing jobs..."
	$(PYTHON) src/utils/view.py analyze

filter:
	@echo "Filtering jobs with Claude Haiku (description-based analysis)..."
	$(PYTHON) src/filters/filter_jobs.py

review:
	@echo "Starting interactive review of REVIEW jobs..."
	$(PYTHON) src/filters/review_jobs.py

validate:
	@echo "Re-validating pending jobs with strict new grad criteria..."
	$(PYTHON) src/filters/validate_targets.py

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
