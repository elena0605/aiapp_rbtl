# GraphRAG Backend API

FastAPI backend for the GraphRAG chat interface.

## Setup

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Environment Variables

Ensure your `.env` file in the project root has all required variables (see main README).

### 3. Run Locally

```bash
# From project root
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Or from backend directory:
```bash
cd backend
uvicorn app.main:app --reload
```

### 4. Test API

```bash
# Health check
curl http://localhost:8000/api/health

# Chat endpoint
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "How many TikTok users have over 1 million followers?"}'
```

## API Endpoints

- `GET /api/health` - Health check
- `POST /api/chat` - Send question, get response
- `WS /api/chat/stream` - WebSocket for streaming responses

## Docker Build

```bash
# From project root
docker build -f backend/Dockerfile -t graphrag-api .
docker run -p 8000:8000 --env-file .env graphrag-api
```

## Deployment to Azure

See `FRONTEND_ARCHITECTURE.md` for Azure deployment instructions.

