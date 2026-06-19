# Deployment Guide

This document covers production configuration and secrets management for The SQL Alchemist.

## Environment modes

| `APP_ENV` | Purpose |
|-----------|---------|
| `development` (default) | Local development; relaxed checks |
| `production` | Stricter validation before boot |

Set in `.env`, `.env.production`, or your orchestrator's environment block.

## Quick start (Docker)

```bash
cp .env.production.example .env.production
# edit .env.production with real values
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

## Secrets management

Never commit real secrets. Use one of these patterns:

### 1. Environment file (single host)

```bash
cp .env.production.example .env.production
# fill OLLAMA_HOST, OLLAMA_API_KEY, etc.
export $(grep -v '^#' .env.production | xargs)
python -m src.health --startup
```

`docker-compose.prod.yml` loads `.env.production` via `env_file`.

### 2. Docker Compose secrets (file-based)

Create secret files outside the repo:

```bash
mkdir -p /etc/sql-alchemist
echo "https://ollama.internal.example.com" > /etc/sql-alchemist/ollama_host
echo "your-api-key" > /etc/sql-alchemist/ollama_api_key
```

Mount or inject them through your orchestration layer and map to environment variables at runtime.

### 3. GitHub Actions

Store values in **Settings → Secrets and variables → Actions**, then reference them in a deploy workflow:

```yaml
env:
  OLLAMA_HOST: ${{ secrets.OLLAMA_HOST }}
  OLLAMA_API_KEY: ${{ secrets.OLLAMA_API_KEY }}
  DEPLOYMENT_SECRETS_READY: "true"
  APP_ENV: production
```

### 4. Kubernetes

```yaml
envFrom:
  - secretRef:
      name: sql-alchemist-secrets
env:
  - name: APP_ENV
    value: production
  - name: DEPLOYMENT_SECRETS_READY
    value: "true"
```

## Production validation

When `APP_ENV=production`, `validate_config()` enforces:

- `OLLAMA_HOST` must not point to `localhost` or `127.0.0.1`
- `DEPLOYMENT_SECRETS_READY=true` must be set after secrets are injected

Boot-time check:

```bash
APP_ENV=production DEPLOYMENT_SECRETS_READY=true python -m src.health --startup
```

## Health checks

| Check | Command |
|-------|---------|
| Config + dataset | `python -m src.health --startup` |
| Streamlit HTTP | `python -m src.health --http` |
| Ollama reachability | `python -m src.health --ollama` |

Docker Compose runs `--startup` in the entrypoint and `--http` in the app healthcheck.

## Logs and exports

| Path | Purpose |
|------|---------|
| `logs/sql_alchemist.log` | Application logs |
| `exports/` | CSV exports from CLI and Streamlit |

Mount both as volumes in production (see `docker-compose.yml`).

## See also

- [GITHUB_SETUP.md](GITHUB_SETUP.md) — CI and push troubleshooting
- [.env.production.example](../.env.production.example) — production variable template
- [.env.example](../.env.example) — local development template
