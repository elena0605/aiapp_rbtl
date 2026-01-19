# Getting Started

Follow this guide to run GraphRAG locally with Neo4j, Langfuse, and the optional MongoDB-based knowledge base. The steps mirror the root `README.md` so that the canonical instructions live inside the docs site.

## Prerequisites

- Python 3.11+
- Node.js 18+ (for the Next.js frontend)
- Docker (for Langfuse stack)
- Access to a Neo4j Aura instance or self-hosted database
- OpenAI API key (or compatible LLM provider)

## 1. Clone & Bootstrap

```bash
git clone https://github.com/bojansimoski/rbtl_graphrag.git
cd rbtl_graphrag
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 2. Configure Environment

Create `.env` in the project root. Use the template below and adjust credentials as needed:

```bash
# Environment Selection
ENVIRONMENT=production  # Set to "development" for local development

# Neo4j (Production)
NEO4J_URI=neo4j+s://your-db.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=***

# Neo4j (Development - Optional)
# Uncomment and set when ENVIRONMENT=development
# NEO4J_URI_DEV=neo4j://127.0.0.1:7687
# NEO4J_USER_DEV=neo4j
# NEO4J_PASSWORD_DEV=local-password

# Langfuse (Production)
LANGFUSE_HOST=http://localhost:3001
LANGFUSE_PUBLIC_KEY=pk-***
LANGFUSE_SECRET_KEY=sk-***

# Langfuse (Development - Optional)
# Uncomment and set when ENVIRONMENT=development
# LANGFUSE_HOST_DEV=http://localhost:3001
# LANGFUSE_PUBLIC_KEY_DEV=pk-dev-***
# LANGFUSE_SECRET_KEY_DEV=sk-dev-***

# MongoDB (Production)
MONGODB_URI=mongodb+srv://...
MONGODB_DATABASE=graphrag

# MongoDB (Development - Optional)
# Uncomment and set when ENVIRONMENT=development
# MONGODB_URI_DEV=mongodb://localhost:27017
# MONGODB_DATABASE_DEV=social_media

# OpenAI
OPENAI_API_KEY=sk-***
OPENAI_MODEL=gpt-4o

# Optional
ENABLE_ANALYTICS_AGENT=false
PROMPT_LABEL=production
```

### Environment Switching

The application supports switching between **development** and **production** environments:

- **Production (default)**: Uses standard variables (`NEO4J_URI`, `MONGODB_URI`, `LANGFUSE_HOST`, etc.)
- **Development**: Set `ENVIRONMENT=development` to use `_DEV` suffixed variables

**Benefits:**
- Use local databases (Neo4j, MongoDB) for development
- Use local Langfuse instance for development
- Keep production credentials separate
- Fallback to production if `_DEV` variables are not set

**Example for local development:**
```bash
ENVIRONMENT=development
NEO4J_URI_DEV=neo4j://127.0.0.1:7687
MONGODB_URI_DEV=mongodb://localhost:27017
MONGODB_DATABASE_DEV=social_media
LANGFUSE_HOST_DEV=http://localhost:3001
# Production variables remain for reference but won't be used
```

**Switching Environments with Docker:**

When using Docker, you need to recreate containers after changing the `ENVIRONMENT` variable. See the [Docker Deployment Guide](DOCKER_DEPLOYMENT.md#switching-between-environments) for detailed step-by-step instructions on how to switch between environments and update Docker containers.

See `README.md` for the full list of optional knobs (`OUTPUT_MODE`, `DEBUG_PROMPT`, etc.).

## 3. Launch Supporting Services

```bash
docker-compose -f docker-compose.langfuse.yml up -d
```

Wait ~30 seconds and verify:

- Langfuse UI: http://localhost:3001
- PostgreSQL: localhost:5433
- ClickHouse: localhost:8123

Use `docker-compose ... logs -f` for troubleshooting.

## 4. Smoke Tests

```bash
# Dry-run Cypher generation
python ai/text_to_cypher.py "Return 5 Person nodes"

# Execute against Neo4j and return JSON
EXECUTE_CYPHER=true OUTPUT_MODE=json python ai/text_to_cypher.py "Return 5 Person nodes"

# Include conversational summary
EXECUTE_CYPHER=true OUTPUT_MODE=chat python ai/text_to_cypher.py "Return 5 Person nodes"
```

Additional scripts (`ai/fewshots/generate_examples.py`, `ai/fewshots/generate_query_categories.py`) provide curated prompt data; run `DEBUG_PROMPT=true ...` to inspect the rendered templates.

## 5. Run the App

### Recommended: Docker (Production-Ready)

The application is fully dockerized. Use Docker for consistent, production-like environments:

```bash
# Production mode (optimized build, no hot-reload)
docker-compose up --build

# Development mode (with hot-reload for active coding)
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

**Access the application:**
- Frontend: http://localhost:3003
- Backend API: http://localhost:8001
- API Docs: http://localhost:8001/docs

**Benefits:**
- ✅ Consistent environment across local, staging, and production
- ✅ No need to manage Python/Node versions locally
- ✅ Matches cloud deployment exactly
- ✅ Easy to share with team members

See [Docker Deployment Guide](DOCKER_DEPLOYMENT.md) for detailed instructions and troubleshooting.

### Alternative: Local Development (For Active Coding)

If you prefer running services directly (useful for debugging):

**Backend (FastAPI):**
```bash
source venv/bin/activate
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend (Next.js):**
```bash
cd frontend
npm install
npm run dev
```

With both servers running, open http://localhost:3002 to try the conversational interface.

**Note:** Local development uses different ports (8000 for backend, 3002 for frontend) to avoid conflicts with Docker.

## Next Steps

- Enable the experimental analytics agent by setting `ENABLE_ANALYTICS_AGENT=true` once you have the Neo4j GDS Agent running.
- Review the [Architecture Overview](architecture/system-overview.md) to understand how each service fits together.
- Dive into the [Testing Strategy](operations/testing.md) before making code changes.

