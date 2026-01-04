# Agent Chat Interface

> Claude Agent SDK chat interface with job pipeline commands.
>
> **Live:** https://justin-job-apps-production.up.railway.app

## Key Files

| File | Purpose |
|------|---------|
| [spec.md](spec.md) | Technical architecture |
| [db_setup.md](db_setup.md) | Database schemas (chat + jobs) |
| [commands/COMMANDS.md](commands/COMMANDS.md) | How to add new commands |

## Running Locally

```bash
cd agent
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Claude API access |
| `DATABASE_URL` | Railway Postgres (optional) |
| `USE_REMOTE_DB` | Set to `true` for Railway DB |
