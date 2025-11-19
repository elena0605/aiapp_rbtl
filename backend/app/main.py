"""FastAPI backend for GraphRAG chat interface."""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import os
import sys
from pathlib import Path
from typing import Optional
import json

# Add project root to path (go up from backend/app/main.py to project root)
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Add backend directory to path for relative imports
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.app.api import chat, health, knowledge_base, graph_info
from backend.app.services.graphrag import GraphRAGService

# Load environment variables
from dotenv import load_dotenv
load_dotenv(dotenv_path=str(ROOT / ".env"))

app = FastAPI(
    title="GraphRAG API",
    description="Natural language interface to Neo4j graph databases",
    version="1.0.0",
)

# CORS configuration
allowed_origins = os.environ.get("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize GraphRAG service
graphrag_service = GraphRAGService()

# Include routers
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(knowledge_base.router, prefix="/api", tags=["knowledge-base"])
app.include_router(graph_info.router, prefix="/api", tags=["graph-info"])

@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "GraphRAG API", "version": "1.0.0"}

