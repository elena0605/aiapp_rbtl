# Frontend & Backend Setup Guide

## Quick Start

### Backend (FastAPI)

1. **Install dependencies:**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

2. **Run the server:**
   ```bash
   # From project root
   uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
   ```

3. **Test:**
   ```bash
   curl http://localhost:8000/api/health
   ```

### Frontend (Next.js)

1. **Install dependencies:**
   ```bash
   cd frontend
   npm install
   ```

2. **Create `.env.local`:**
   ```bash
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```

3. **Run development server:**
   ```bash
   npm run dev
   ```

4. **Open browser:**
   Navigate to http://localhost:3000

## Project Structure

```
rbtl_graphrag/
├── backend/              # FastAPI backend
│   ├── app/
│   │   ├── main.py      # FastAPI app
│   │   ├── api/         # API routes
│   │   └── services/    # Business logic
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/            # Next.js frontend
│   ├── app/            # Pages
│   ├── components/     # React components
│   ├── lib/            # Utilities
│   └── package.json
│
└── ai/                 # Existing GraphRAG logic (reused)
```

## API Endpoints

- `GET /api/health` - Health check
- `POST /api/chat` - Send question, get response
- `WS /api/chat/stream` - WebSocket for streaming

## Environment Variables

All environment variables must be set in `.env` file (see main README).

For frontend, also create `frontend/.env.local`:
```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Docker

### Backend
```bash
docker build -f backend/Dockerfile -t graphrag-api .
docker run -p 8000:8000 --env-file .env graphrag-api
```

## Next Steps

1. Test locally (backend + frontend)
2. Setup Azure resources
3. Deploy backend to Azure Container Apps
4. Deploy frontend to Azure Static Web Apps
5. Configure CORS and environment variables

