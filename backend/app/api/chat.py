"""Chat endpoints for GraphRAG."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import json

from backend.app.services.graphrag import GraphRAGService

router = APIRouter()
graphrag_service = GraphRAGService()

class ChatRequest(BaseModel):
    question: str
    execute_cypher: bool = True
    output_mode: str = "chat"  # json, chat, or both

class ChatResponse(BaseModel):
    question: str
    cypher: Optional[str] = None
    results: Optional[List[Dict[str, Any]]] = None
    summary: Optional[str] = None
    examples_used: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Process a chat question and return Cypher query with results."""
    try:
        result = await graphrag_service.process_question(
            question=request.question,
            execute_cypher=request.execute_cypher,
            output_mode=request.output_mode,
        )
        return ChatResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.websocket("/chat/stream")
async def chat_stream(websocket: WebSocket):
    """WebSocket endpoint for streaming chat responses."""
    await websocket.accept()
    
    try:
        while True:
            # Receive question from client
            data = await websocket.receive_text()
            message = json.loads(data)
            question = message.get("question")
            
            if not question:
                await websocket.send_json({
                    "type": "error",
                    "message": "Question is required"
                })
                continue
            
            # Send initial acknowledgment
            await websocket.send_json({
                "type": "status",
                "message": "Processing question..."
            })
            
            # Process question with streaming
            async for chunk in graphrag_service.process_question_stream(
                question=question,
                execute_cypher=message.get("execute_cypher", True),
                output_mode=message.get("output_mode", "chat"),
            ):
                await websocket.send_json(chunk)
            
            # Send completion
            await websocket.send_json({
                "type": "complete"
            })
            
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "message": str(e)
        })

