# Local Testing Guide

## Prerequisites

1. ✅ Ensure all environment variables are set in `.env` file (see main README)
2. ✅ Python 3.13+ with virtual environment activated
3. ✅ Node.js 18+ installed
4. ✅ Neo4j running and accessible
5. ✅ Langfuse running (if using prompts from Langfuse)

## Quick Start (Using Scripts)

### Option 1: Use Test Scripts

**Terminal 1 - Backend:**
```bash
source venv/bin/activate
./test_backend.sh
```

**Terminal 2 - Frontend:**
```bash
./test_frontend.sh
```

### Option 2: Manual Start

## Step 1: Activate Virtual Environment

```bash
source venv/bin/activate
```

## Step 2: Install Backend Dependencies (if not done)

```bash
pip install -r backend/requirements.txt
```

## Step 3: Start Backend (Terminal 1)

```bash
# From project root with venv activated
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
INFO:     API docs available at http://localhost:8000/docs
```

## Step 4: Install Frontend Dependencies (if not done)

```bash
cd frontend
npm install
```

## Step 5: Create Frontend Environment File

Create `frontend/.env.local`:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Step 6: Start Frontend (Terminal 2)

```bash
cd frontend
npm run dev
```

You should see:
```
  ▲ Next.js 14.1.0
  - Local:        http://localhost:3002
```

## Step 7: Test the Application

1. **Open browser**: http://localhost:3002
2. **Test health endpoint**: http://localhost:8000/api/health
3. **View API docs**: http://localhost:8000/docs
4. **Try a question**: "How many TikTok users have over 1 million followers?"

## Troubleshooting

### Backend won't start
- Check all environment variables are set in `.env`
- Verify Neo4j is accessible
- Check Python dependencies are installed

### Frontend can't connect to backend
- Verify backend is running on port 8000
- Check `NEXT_PUBLIC_API_URL` in `frontend/.env.local`
- Check CORS settings in `backend/app/main.py`

### API errors
- Check backend logs for detailed error messages
- Verify all required env vars are set
- Test backend directly with curl first

