# Deployment & Environments

This guide covers deploying the dockerized RBTL GraphRAG application across different environments.

## Environment Matrix

| Target | Backend | Frontend | Neo4j | MongoDB | Langfuse |
|--------|---------|----------|-------|---------|----------|
| **Local** | Docker Container | Docker Container | Aura/self-hosted | Atlas/local | docker-compose |
| **Staging** | Docker (Azure Container Apps) | Docker (Azure Container Apps) | Managed Aura | Managed Atlas | Self-hosted or Cloud |
| **Prod** | Docker (Azure Container Apps) | Docker (Azure Container Apps) | Aura Enterprise | Atlas/DocumentDB | Langfuse Cloud |

**All environments use Docker containers** for consistency and easy deployment.

## Dockerized Deployment

The application is **fully containerized** using Docker for all environments. This ensures consistency between local development, staging, and production.

### Container Architecture

**Backend Container** (`backend/Dockerfile`):
- Python 3.13-slim base image
- All dependencies from `backend/requirements.txt`
- Exposes port 8000
- Includes health check support
- Multi-stage build for optimization

**Frontend Container** (`frontend/Dockerfile`):
- Node.js 18-alpine base image
- Multi-stage build for optimization
- Next.js standalone output mode
- Exposes port 3000
- Production-ready static assets

### Local Docker Setup

**Quick Start:**
```bash
# Production mode (optimized, no hot-reload)
docker-compose up --build

# Development mode (with hot-reload for active coding)
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

**Access:**
- Frontend: http://localhost:3003
- Backend: http://localhost:8001
- API Docs: http://localhost:8001/docs

See [Docker Deployment Guide](../DOCKER_DEPLOYMENT.md) for detailed instructions, troubleshooting, and cloud deployment options.

## Secrets & Config

- Store `.env` values in a secret manager (AWS Secrets Manager, Doppler, 1Password).
- Rotate OpenAI/Langfuse keys regularly; the backend reads them on startup.
- When running analytics agent, ensure both the backend and the MCP server agree on Neo4j credentials.

### Environment Switching

The application supports switching between development and production environments using the `ENVIRONMENT` variable:

- **Production**: Set `ENVIRONMENT=production` (or omit it). Uses standard variables (`NEO4J_URI`, `MONGODB_URI`, etc.)
- **Development**: Set `ENVIRONMENT=development`. Uses `_DEV` suffixed variables (`NEO4J_URI_DEV`, `MONGODB_URI_DEV`, etc.)

This allows you to:
- Use local databases for development while keeping production credentials
- Switch environments without changing code
- Fallback to production values if `_DEV` variables are not set

See [Docker Deployment Guide](../DOCKER_DEPLOYMENT.md#environment-switching) for detailed configuration examples.

## Observability & Health Checks

- `GET /health` for FastAPI readiness.
- Langfuse dashboards for LLM traces; configure alerting on latency, failure rate.
- Add metrics/structured logs (planned).

## GitHub Pages + MkDocs

- `mkdocs build` produces static docs for GitHub Pages.
- `mkdocs gh-deploy --force` publishes to `gh-pages`.
- Recommended GitHub Action (to be added) runs on pushes to `main` and pull requests for validation.

