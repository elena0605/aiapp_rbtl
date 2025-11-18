#!/bin/bash
# Test script for frontend

cd "$(dirname "$0")/frontend"

echo "Installing frontend dependencies (if needed)..."
npm install

echo ""
echo "Creating .env.local if it doesn't exist..."
if [ ! -f .env.local ]; then
    echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
    echo "Created .env.local"
fi

echo ""
echo "Starting Next.js frontend..."
echo "Frontend will be available at: http://localhost:3002"
echo ""
echo "Press Ctrl+C to stop"
echo ""

npm run dev

