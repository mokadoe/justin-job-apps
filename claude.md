# Claude Instructions for Mokadoe Workspace

> **Purpose:** This document provides instructions for Claude Code sessions working in the Mokadoe workspace. Read this first when starting any new session.

---

## Workspace Overview

**Mokadoe** is an incubator for AI-forward apps and tools. This workspace contains multiple projects:

### Projects

1. **`justin-job-apps/`** - Job Application Automation Pipeline
   - **Type:** Python/SQLite application
   - **Purpose:** Automated job discovery, filtering, and contact discovery for new grad SWE positions
   - **Status:** Active development (MVP in progress)
   - **README:** `justin-job-apps/README.md` (comprehensive)

2. **`mokadoe.github.io/`** - Company Landing Page
   - **Type:** React/TypeScript static site
   - **Purpose:** Landing page for Mokadoe.ai
   - **Status:** Deployed
   - **README:** `mokadoe.github.io/README.md`

3. **`docs/`** - Workspace Documentation
   - **Type:** Shared documentation
   - **Status:** Currently empty

---

## Working in This Workspace

### First Steps When Starting a New Session

1. **Identify the project** - Which directory is the user working in?
   - `justin-job-apps/` → Python automation project
   - `mokadoe.github.io/` → React website
   - Root level → Workspace-level task

2. **Read the project README** - ALWAYS read `<project>/README.md` first
   - Contains architecture, current status, key decisions
   - Provides context for what you're working on
   - Lists common tasks and commands

3. **Check project-specific docs**
   - `justin-job-apps/docs/` - MVP design, learnings, principles
   - Look for additional documentation in the project

4. **Understand current state**
   - Run status commands (e.g., `make targets` for justin-job-apps)
   - Check git status if needed
   - Identify what's in progress vs. complete

### Project-Specific Guidelines

#### For `justin-job-apps/`

**Required Reading:**
1. `justin-job-apps/README.md` - Complete project overview
2. `justin-job-apps/docs/learnings.md` - Decision-making principles
3. `justin-job-apps/docs/mvp_design.md` - Original design document

**Key Points:**
- Uses Python 3.13, SQLite, Claude API
- Organized by function: `src/scrapers/`, `src/filters/`, `src/discovery/`, `src/utils/`
- Environment managed by `direnv` with `env/` directory (NOT `venv/`)
- All commands available via Makefile: `make help`
- Development follows "Think Smart" principles (see learnings.md)

**Before Making Changes:**
- Read relevant source files in `src/`
- Understand the database schema in `schemas/jobs.sql`
- Check constants in `src/utils/constants.py`
- Test changes with `make <command>`

#### For `mokadoe.github.io/`

**Key Points:**
- React 19 + TypeScript + Vite
- Single-page application
- Deployed to GitHub Pages (docs/ folder)
- Domain: mokadoe.ai

---

## File Organization Standards

All projects in this workspace follow these principles:

### Directory Structure
```
project-name/
├── README.md              # Comprehensive project overview (REQUIRED)
├── src/                   # Source code organized by function
│   ├── module1/          # Logical grouping (scrapers, filters, etc.)
│   ├── module2/
│   └── utils/            # Shared utilities
├── data/                  # Data files (gitignored if sensitive)
├── docs/                  # Project documentation
├── schemas/               # Database schemas (if applicable)
├── tests/                 # Test files
└── env/                   # Python virtual environment (gitignored)
```

### Key Principles

1. **README-Driven**
   - Every project MUST have a comprehensive README.md
   - README should be the single source of truth for:
     - What the project does
     - How to get started
     - Architecture and key decisions
     - Current status and next steps
     - Common commands and workflows

2. **Logical Organization**
   - Group files by function, not type
   - `src/scrapers/` not `src/scraper1.py`, `src/scraper2.py` at root
   - Keep root level clean - only config files and docs

3. **Self-Documenting**
   - Code should be clear and well-commented
   - Key decisions documented in `docs/` directory
   - Use descriptive file and variable names

4. **Environment Consistency**
   - Python projects use `env/` (NOT `venv/`)
   - Managed by `direnv` with `.envrc`
   - API keys in `.env` (gitignored)

---

## Development Philosophy

From `justin-job-apps/docs/learnings.md` - applies to all projects:

### Core Principles

**Think Smart**
- Identify bottlenecks - Optimize the constraint, not what's easy
- Impact > Effort - Prioritize high-impact low-effort work
- Critical path - Do blocking work first, parallelize the rest

**Build Pragmatically**
- Simple first - Complexity must be earned
- Modular design - Independent components
- Time-box everything - Set budgets, reassess when exceeded

**Validate Early**
- Test assumptions before building on them
- Real feedback > theoretical analysis
- Make decisions reversible

**Avoid Traps**
- Planning theater - Ship working solutions
- Solving hypothetical problems - Only solve encountered issues
- Premature optimization - Optimize for iteration speed first

### When Making Changes

**Before Starting:**
1. Read the README
2. Understand the current state
3. Identify the bottleneck or critical path
4. Justify why this change matters

**During Development:**
1. Keep it simple - don't over-engineer
2. Make changes modular and testable
3. Update documentation as you go
4. Test thoroughly before marking complete

**After Completion:**
1. Update README if architecture changed
2. Document key decisions in `docs/`
3. Clean up any temporary files or caches
4. Verify all commands still work

---

## Environment & Shell Configuration

### Important Notes

**Shell:** zsh with `rm` aliased to `trash`
- Files deleted with `rm` go to trash (safer)
- Use `/bin/rm` for permanent deletion
- This prevents accidental data loss

**Python Virtual Environments:**
- Always use `env/` directory name (NOT `venv/`)
- Managed by `direnv` - `.envrc` auto-activates
- Each project has its own isolated environment

**Environment Variables:**
- Stored in `.env` file (gitignored)
- Loaded via `python-dotenv` in Python projects
- Never commit API keys or secrets

---

## Common Workflows

### Starting Work on a Project

```bash
# Navigate to project
cd justin-job-apps  # or mokadoe.github.io

# Read the README
cat README.md | less

# Check current status
git status
make help  # See available commands

# Run status command (project-specific)
make targets  # for justin-job-apps
npm run dev   # for mokadoe.github.io
```

### Making Changes

```bash
# Read relevant code first
cat src/module/file.py

# Make changes with clear understanding
# Edit files...

# Test changes
make test  # or project-specific command

# Update documentation if needed
# Edit README.md or docs/ files

# Clean up
# Remove temp files, update .gitignore
```

### Adding New Features

1. **Read** the relevant README and docs
2. **Understand** the current architecture
3. **Plan** the approach (simple, modular, testable)
4. **Implement** with clear code and comments
5. **Test** thoroughly
6. **Document** in README and code comments
7. **Clean up** temp files and caches

---

## Project Status Reference

### justin-job-apps (Current as of 2025-12-30)

**Phase:** MVP Development (Day 5/7)

**Completed:**
- ✅ Job scraping (7,124 jobs from 305 companies)
- ✅ AI filtering (16 pending new grad jobs)
- ✅ Contact discovery implementation
- ✅ Database & viewing tools

**In Progress:**
- 🔄 Testing contact discovery

**Next:**
- ⏳ Message generation (Day 6)
- ⏳ First outreach (Day 7)

**Key Commands:**
```bash
make init       # Initialize database
make load       # Load jobs
make filter     # AI filtering
make targets    # View results
make inspect    # Database overview
```

### mokadoe.github.io (Current as of 2025-12-21)

**Phase:** Deployed

**Status:**
- ✅ Landing page live at mokadoe.ai
- ✅ React + TypeScript + Vite setup
- ✅ Responsive design

**Key Commands:**
```bash
npm run dev     # Local development
npm run build   # Build for production
npm run deploy  # Deploy to GitHub Pages
```

---

## For Future Claude Sessions

### What to Read First

1. **This file** (`claude.md`) - Workspace overview and standards
2. **Project README** (`<project>/README.md`) - Specific project context
3. **Project docs** (`<project>/docs/`) - Design decisions and principles

### Quick Reference

**justin-job-apps:**
- README: `justin-job-apps/README.md` (comprehensive, read this!)
- Learnings: `justin-job-apps/docs/learnings.md` (decision frameworks)
- Status: Run `make targets` to see current data

**mokadoe.github.io:**
- README: `mokadoe.github.io/README.md`
- Status: Website deployed at mokadoe.ai

### Common Mistakes to Avoid

1. **Not reading the README first** - Always start here
2. **Using `venv/` instead of `env/`** - Standard is `env/`
3. **Making changes without understanding context** - Read code first
4. **Over-engineering** - Keep it simple, iterate
5. **Forgetting to update docs** - Document as you go
6. **Not testing before marking complete** - Always verify

---

## Questions to Ask Yourself

Before starting any work:

1. **Have I read the README?** - Do I understand the project?
2. **What problem am I solving?** - Why does this matter?
3. **What's the current state?** - Where are we in the timeline?
4. **What's the simplest approach?** - How can I avoid over-engineering?
5. **How will I test this?** - What's the verification plan?
6. **What documentation needs updating?** - README, docs, code comments?

---

## Workspace Conventions

### File Naming

- `README.md` - Project overview (required)
- `claude.md` - Instructions for Claude (this file)
- `Makefile` - Command shortcuts for projects
- `.env` - Environment variables (gitignored)
- `.envrc` - direnv configuration

### Code Organization

- `src/` - Source code (organized by function)
- `docs/` - Documentation
- `tests/` - Test files
- `data/` - Data files
- `schemas/` - Database schemas

### Documentation Standards

- Every project has comprehensive README.md
- Key decisions documented in `docs/`
- Code comments explain "why", not "what"
- Keep documentation up-to-date with code

---

**Last Updated:** 2025-12-30

**Workspace Owner:** Justin Chu

**Projects:** 2 active (justin-job-apps, mokadoe.github.io)
