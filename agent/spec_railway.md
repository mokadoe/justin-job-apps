# Railway Deployment Spec

> Deployment configuration for running the Claude Agent Chat on Railway. See [spec.md](spec.md) for the application spec.

## Live URL

**https://justin-job-apps-production.up.railway.app**

## Project Structure

```
Railway Project: job-flow
├── Service: justin-job-apps
│   ├── Environment: production
│   ├── Root Directory: /agent
│   ├── Builder: Dockerfile
│   └── Variables: ANTHROPIC_API_KEY, DATABASE_URL
│
└── Service: Postgres
    ├── Type: Managed PostgreSQL
    ├── Volume: postgres-volume (persistent)
    ├── Internal: postgres.railway.internal:5432
    └── Public: turntable.proxy.rlwy.net:41317
```

## Deployment Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Python 3.12 container, installs deps, runs uvicorn |
| `railway.toml` | Railway build config + health check |
| `.dockerignore` | Excludes `__pycache__`, `.env`, etc. |

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
```

### railway.toml

```toml
[build]
builder = "dockerfile"

[deploy]
healthcheckPath = "/health"
healthcheckTimeout = 30
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 3
```

## Environment Variables

| Variable | Required | Set By | Purpose |
|----------|----------|--------|---------|
| `ANTHROPIC_API_KEY` | Yes | User | Claude API access |
| `DATABASE_URL` | Yes | Railway | PostgreSQL connection (linked from Postgres service) |
| `PORT` | No | Railway | Server port (auto-set) |
| `RAILWAY_ENVIRONMENT` | No | Railway | Auto-detected to select database |
| `RAILWAY_*` | No | Railway | Various Railway metadata |

**Variable Linking:** `DATABASE_URL=${{Postgres.DATABASE_URL}}` resolves at runtime to the internal PostgreSQL connection string.

## Health Check

Railway monitors `/health` endpoint:

```
GET /health → {"status": "ok"}
```

## Deployment Workflow

### Automatic (GitHub Integration)

1. Push to `main` branch
2. Railway detects changes in `/agent` directory
3. Builds Docker image
4. Deploys with zero-downtime

### Manual (CLI)

```bash
cd agent
railway up
```

## Root Directory Configuration

This repo contains multiple projects. Railway is configured to only deploy from `/agent`:

- **Root Directory:** `agent`
- Only changes in `agent/` trigger deploys
- `railway.toml` lives inside `agent/`

## Local vs Production

| Aspect | Local | Railway |
|--------|-------|---------|
| Command | `uvicorn main:app --reload --port 8000` | Auto via Dockerfile |
| Port | 8000 (default) | `$PORT` (Railway sets) |
| URL | `http://localhost:8000` | `https://justin-job-apps-production.up.railway.app` |
| Database | SQLite (`data/chat.db`) | PostgreSQL (persistent) |
| SDK Connections | In-memory (lost on restart) | In-memory (lost on redeploy) |

## Limitations (Current)

- **No auth** - Public endpoint
- **Single instance** - No horizontal scaling
- **SDK context resets** - Chat history persists in PostgreSQL, but Claude's internal conversation context resets on redeploy (SDK limitation)

## Future Improvements

- [x] PostgreSQL for chat persistence (implemented)
- [ ] SDK session resumption (cross-restart context persistence)
- [ ] Add API key authentication
- [ ] Custom domain setup

## Useful Commands

```bash
# Check status
railway status

# View logs
railway logs

# List services
railway service list

# Open dashboard
railway open
```

## References

- [Railway Docs](https://docs.railway.com/)
- [Railway CLI](https://docs.railway.com/guides/cli)
- [Application Spec](spec.md)
