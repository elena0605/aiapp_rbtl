#!/bin/bash
# Test script for backend

cd "$(dirname "$0")"
source venv/bin/activate

echo "Starting FastAPI backend..."
echo "Backend will be available at: http://localhost:8000"
echo "API docs at: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop"
echo ""

uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

