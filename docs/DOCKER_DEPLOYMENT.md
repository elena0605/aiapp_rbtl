# Docker Deployment Guide

This guide explains how to build and deploy the RBTL GraphRAG application using Docker.

## Architecture

The application consists of two Docker containers:

- **Backend**: FastAPI application (Python 3.13)
- **Frontend**: Next.js application (Node.js 18)

## Prerequisites

- Docker and Docker Compose installed
- `.env` file with all required environment variables

## Quick Start

### 1. Build and Run with Docker Compose

```bash
# Build and start all services
docker-compose up --build

# Or run in detached mode
docker-compose up -d --build
```

The application will be available at:
- Frontend: http://localhost:3003 (port 3003 to avoid conflicts)
- Backend API: http://localhost:8001 (port 8001 to avoid conflicts)
- API Docs: http://localhost:8001/docs

**Note:** Ports are mapped to avoid conflicts with:
- Local development (backend: 8000, frontend: 3002)
- Langfuse (3001)

### 2. Stop Services

```bash
docker-compose down
```

## Building Individual Images

### Backend Image

```bash
docker build -f backend/Dockerfile -t rbtl-graphrag-backend:latest .
```

### Frontend Image

```bash
docker build -f frontend/Dockerfile \
  --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 \
  -t rbtl-graphrag-frontend:latest .
```

## Environment Variables

Create a `.env` file in the project root with:

```bash
# Environment Selection
ENVIRONMENT=production  # Set to "development" for local development

# Neo4j (Production)
NEO4J_URI=bolt+s://your-db-id.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password
NEO4J_DATABASE=rbl

# Neo4j (Development - Optional)
# When ENVIRONMENT=development, these will be used instead
# For Docker: use host.docker.internal instead of localhost/127.0.0.1
# NEO4J_URI_DEV=bolt://host.docker.internal:7687
# NEO4J_USER_DEV=neo4j
# NEO4J_PASSWORD_DEV=local-password
# NEO4J_DATABASE_DEV=neo4j

# OpenAI
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-4o

# Langfuse (Production)
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
PROMPT_LABEL=production

# Langfuse (Development - Optional)
# When ENVIRONMENT=development, these will be used instead
# LANGFUSE_HOST_DEV=http://localhost:3001
# LANGFUSE_PUBLIC_KEY_DEV=pk-lf-dev-...
# LANGFUSE_SECRET_KEY_DEV=sk-lf-dev-...

# MongoDB (Production)
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB=rbl
# Alternative: MONGODB_DATABASE=rbl (both work)

# MongoDB (Development - Optional)
# When ENVIRONMENT=development, these will be used instead
# For Docker: use host.docker.internal instead of localhost
# MONGODB_URI_DEV=mongodb://airflow:tiktok@host.docker.internal:27017
# MONGODB_DB_DEV=social_media
# Alternative: MONGODB_DATABASE_DEV=social_media (both work)

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8000

# Optional
ENABLE_ANALYTICS_AGENT=false
```

### Environment Switching

The application supports switching between **development** and **production** environments using the `ENVIRONMENT` variable in your `.env` file.

**How it works:**
- Set `ENVIRONMENT=development` to use local databases and services
- Set `ENVIRONMENT=production` (or omit it) to use production credentials
- `_DEV` suffixed variables are optional - if not set, the app falls back to production values

**Example: Local Development Setup**
```bash
ENVIRONMENT=development

# Production (for reference, won't be used)
NEO4J_URI=neo4j+s://prod-db.databases.neo4j.io
MONGODB_URI=mongodb+srv://prod-cluster...

# Development (will be used)
# Note: Use host.docker.internal for Docker containers to access host services
NEO4J_URI_DEV=bolt://host.docker.internal:7687
NEO4J_USER_DEV=neo4j
NEO4J_PASSWORD_DEV=local-password
NEO4J_DATABASE_DEV=neo4j
MONGODB_URI_DEV=mongodb://airflow:tiktok@host.docker.internal:27017
MONGODB_DB_DEV=social_media
LANGFUSE_HOST_DEV=http://host.docker.internal:3000
```

**Docker Compose automatically passes all environment variables** from your `.env` file to the containers, so environment switching works seamlessly with Docker.

#### Switching Between Environments

To switch from one environment to another, follow these steps:

**Step 1: Update `.env` file**

Edit your `.env` file and change the `ENVIRONMENT` variable:

```bash
# To switch to development
ENVIRONMENT=development

# To switch to production
ENVIRONMENT=production
```

**Step 2: Restart the backend container**

After changing `ENVIRONMENT`, restart the backend container to load the new environment:

```bash
# Simple restart (works if container is already running)
docker-compose restart backend
```

**Or, if you want to ensure all environment variables are reloaded:**

```bash
# For production mode
docker-compose up -d --force-recreate backend

# For development mode
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --force-recreate backend
```

**Note:** You don't need to stop containers first. The `--force-recreate` flag will recreate the container with the new environment variables.

**Alternative: Full restart (if simple restart doesn't work)**

If you need to fully stop and recreate:

```bash
# If you started with production mode (docker-compose up)
docker-compose down
docker-compose up -d --force-recreate

# If you started with development mode (docker-compose -f docker-compose.yml -f docker-compose.dev.yml up)
docker-compose -f docker-compose.yml -f docker-compose.dev.yml down
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --force-recreate
```

**Step 3: Verify the switch**

Check that containers are using the correct environment:

```bash
# Check backend logs to see which environment is active
docker-compose logs backend | grep -i environment

# Or check environment variables in the container
docker-compose exec backend env | grep ENVIRONMENT
```

**Quick Reference: Switching Commands**

```bash
# Switch to Development
# 1. Edit .env: ENVIRONMENT=development
# 2. Run (simplest method):
docker-compose restart backend

# Or with force recreate (ensures env vars are reloaded):
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --force-recreate backend

# Switch to Production
# 1. Edit .env: ENVIRONMENT=production
# 2. Run (simplest method):
docker-compose restart backend

# Or with force recreate (ensures env vars are reloaded):
docker-compose up -d --force-recreate backend
```

#### Understanding the Two Concepts

There are **two independent concepts** that can be mixed and matched:

**1. `ENVIRONMENT` variable (in `.env` file)**
- Controls **which databases/credentials** to use
- `ENVIRONMENT=development` → uses `NEO4J_URI_DEV`, `MONGODB_URI_DEV`, `LANGFUSE_HOST_DEV`
- `ENVIRONMENT=production` → uses `NEO4J_URI`, `MONGODB_URI`, `LANGFUSE_HOST`

**2. Docker Compose files**
- Controls **how the code runs** (hot-reload, volume mounts, build mode)
- `docker-compose.yml` → Production Docker mode (no hot-reload, code baked into image)
- `docker-compose.yml + docker-compose.dev.yml` → Development Docker mode (hot-reload, volume mounts)

**Important:** Both modes can run **locally on your machine** or **on remote servers**. The difference is not about location, but about:
- **Production Docker mode**: Optimized for deployment (code baked in, no hot-reload, smaller images)
- **Development Docker mode**: Optimized for active coding (hot-reload, volume mounts, easier debugging)

**The Difference Between the Two Commands:**

```bash
# Command 1: Production Docker mode
docker-compose up -d --force-recreate
```
- Uses only `docker-compose.yml`
- Code is **baked into the Docker image** (no volume mounts)
- **No hot-reload** - changes require rebuild
- Backend runs: `uvicorn` (production command)
- Frontend runs: Next.js production build
- **BUT** still respects `ENVIRONMENT` variable for database selection

```bash
# Command 2: Development Docker mode
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --force-recreate
```
- Uses both `docker-compose.yml` + `docker-compose.dev.yml` (dev overrides)
- Code is **mounted as volumes** (live code from your filesystem)
- **Hot-reload enabled** - changes reflect immediately
- Backend runs: `uvicorn --reload` (auto-reloads on file changes)
- Frontend runs: `npm run dev` (Next.js dev server)
- **ALSO** respects `ENVIRONMENT` variable for database selection

**Possible Combinations:**

| ENVIRONMENT | Docker Mode | What Happens |
|------------|------------|--------------|
| `development` | Production (`docker-compose up`) | Uses dev databases, but no hot-reload |
| `development` | Development (`docker-compose -f ... -f docker-compose.dev.yml up`) | Uses dev databases + hot-reload |
| `production` | Production (`docker-compose up`) | Uses prod databases, no hot-reload |
| `production` | Development (`docker-compose -f ... -f docker-compose.dev.yml up`) | Uses prod databases + hot-reload (unusual) |

**Most Common Use Cases:**

- **Local development with hot-reload**: `ENVIRONMENT=development` + dev Docker mode
- **Testing against production databases**: `ENVIRONMENT=production` + dev Docker mode
- **Production deployment**: `ENVIRONMENT=production` + production Docker mode

**Important Notes:**
- ✅ **`docker-compose restart backend`** is the simplest method and usually works
- ✅ **`--force-recreate`** ensures environment variables are fully reloaded (use if restart doesn't work)
- ✅ Containers will automatically reconnect to the correct databases based on the `ENVIRONMENT` variable
- ✅ No code changes needed - just update `.env` and restart/recreate the container
- ✅ **Database names switch automatically:**
  - Development: Neo4j uses `neo4j` database, MongoDB uses `social_media` database
  - Production: Both Neo4j and MongoDB use `rbl` database

## Cloud Deployment

### Push to Container Registry

```bash
# Tag images
docker tag rbtl-graphrag-backend:latest your-registry/rbtl-graphrag-backend:latest
docker tag rbtl-graphrag-frontend:latest your-registry/rbtl-graphrag-frontend:latest

# Push to registry
docker push your-registry/rbtl-graphrag-backend:latest
docker push your-registry/rbtl-graphrag-frontend:latest
```

### Azure Container Apps

The images can be deployed to Azure Container Apps as described in the [Azure Deployment Guide](operations/azure-deployment.md).

### Kubernetes

Example deployment manifests:

```yaml
# backend-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rbtl-graphrag-backend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: rbtl-graphrag-backend
  template:
    metadata:
      labels:
        app: rbtl-graphrag-backend
    spec:
      containers:
      - name: backend
        image: your-registry/rbtl-graphrag-backend:latest
        ports:
        - containerPort: 8000
        envFrom:
        - secretRef:
            name: rbtl-graphrag-secrets
```

## Troubleshooting

### Backend won't start

- Check environment variables are set correctly
- Verify Neo4j connection: `docker-compose logs backend`
- Check health endpoint: `curl http://localhost:8000/api/health`

### Frontend can't connect to backend

- Verify `NEXT_PUBLIC_API_URL` is set correctly
- Check CORS settings in backend
- Ensure backend container is running: `docker-compose ps`

### Build fails

- Clear Docker cache: `docker-compose build --no-cache`
- Check Dockerfile paths are correct
- Verify all required files exist

## Development vs Production Docker Modes

**Important Clarification:** Both "Development Docker mode" and "Production Docker mode" can run **locally on your machine** or **on remote servers**. The difference is about **how the code runs**, not **where it runs**:

- **Production Docker mode** = Optimized for deployment (code baked into image, no hot-reload, smaller/faster)
- **Development Docker mode** = Optimized for active coding (hot-reload, volume mounts, easier debugging)

### Development Docker Mode (with Hot Reload)

For active development with automatic code reloading:

```bash
# Set ENVIRONMENT=development in .env file first
# Then start with development overrides (hot-reload enabled)
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

**Features:**
- ✅ Backend auto-reloads on Python file changes (via `--reload` flag)
- ✅ Frontend hot-reloads on React/TypeScript changes
- ✅ Source code mounted as volumes (no rebuild needed for code changes)
- ✅ Code changes reflect immediately without restarting containers
- ⚠️ Still need to rebuild if you change `requirements.txt` or `package.json`
- ⚠️ Larger container size (includes dev dependencies)
- ⚠️ Slower startup (runs dev servers)

**When to use:**
- Active coding and debugging
- Testing code changes quickly
- Local development (but can also run on remote servers)

**Environment Configuration:**
Make sure your `.env` file has:
```bash
ENVIRONMENT=development
NEO4J_URI_DEV=bolt://host.docker.internal:7687
NEO4J_USER_DEV=neo4j
NEO4J_PASSWORD_DEV=local-password
NEO4J_DATABASE_DEV=neo4j
MONGODB_URI_DEV=mongodb://airflow:tiktok@host.docker.internal:27017
MONGODB_DB_DEV=social_media
LANGFUSE_HOST_DEV=http://host.docker.internal:3000
# ... other _DEV variables
```

### Production Docker Mode

For optimized, production-ready containers:

```bash
# Set ENVIRONMENT=production in .env file (or omit it)
# Then start standard production build
docker-compose up --build
```

**Features:**
- ✅ Code baked into image (no volume mounts)
- ✅ Optimized builds (smaller images, faster startup)
- ✅ Production-ready configuration
- ✅ No dev dependencies in final image
- ⚠️ Code changes require rebuild (no hot-reload)
- ⚠️ Must rebuild image to see code changes

**When to use:**
- Production deployments
- Testing production-like environment locally
- CI/CD pipelines
- When you want optimized, stable containers

**Environment Configuration:**
Make sure your `.env` file has:
```bash
ENVIRONMENT=production  # or omit this line
NEO4J_URI=bolt+s://prod-db.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password
NEO4J_DATABASE=rbl
MONGODB_URI=mongodb+srv://prod-cluster...
MONGODB_DB=rbl
# ... production variables
```

**Summary:**
- Both modes can run **locally** or on **remote servers**
- Development mode = easier coding (hot-reload)
- Production mode = optimized deployment (no hot-reload, smaller images)
- The `ENVIRONMENT` variable (development/production) is separate and controls which databases to use

### Production Best Practices

- Use multi-stage builds (already configured)
- Set `NODE_ENV=production`
- Use production-ready base images
- Configure proper health checks
- Set up logging and monitoring

## Image Sizes

Expected image sizes:
- Backend: ~500-800 MB
- Frontend: ~200-400 MB

To reduce size:
- Use `.dockerignore` (already configured)
- Multi-stage builds (already configured)
- Alpine base images (frontend uses alpine)

