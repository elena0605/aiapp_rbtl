"""Chat endpoints for GraphRAG with chat history persistence."""

from datetime import datetime
import json
from typing import Optional, List, Dict, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel

from backend.app.services.chat_sessions import (
    append_chat_messages,
    ensure_allowed_username,
    fetch_chat_history,
    list_test_users,
    delete_chat_message,
    set_message_favorite,
    get_favorite_messages,
)
from backend.app.services.graphrag import GraphRAGService


router = APIRouter()
graphrag_service = GraphRAGService()


class ChatMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    cypher: Optional[str] = None
    results: Optional[List[Dict[str, Any]]] = None
    summary: Optional[str] = None
    examples: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None
    timestamp: datetime
    is_favorite: bool = False
    timings: Optional[Dict[str, float]] = None


class ChatHistoryResponse(BaseModel):
    username: str
    messages: List[ChatMessage]


class FavoriteMessageResponse(BaseModel):
    message: ChatMessage
    question: Optional[str] = None
    question_id: Optional[str] = None


class FavoritesResponse(BaseModel):
    username: str
    favorites: List[FavoriteMessageResponse]


class ChatRequest(BaseModel):
    username: str
    question: str
    execute_cypher: bool = True
    output_mode: str = "chat"  # json, chat, or both


class ChatResponse(BaseModel):
    username: str
    question: str
    cypher: Optional[str] = None
    results: Optional[List[Dict[str, Any]]] = None
    summary: Optional[str] = None
    examples_used: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None
    timings: Optional[Dict[str, float]] = None
    message_id: Optional[str] = None


class FavoriteRequest(BaseModel):
    is_favorite: bool = True


@router.get("/chat/users")
async def list_chat_users():
    """Return available tester usernames."""
    return {"users": list_test_users()}


@router.get("/chat/history/{username}", response_model=ChatHistoryResponse)
async def get_chat_history(username: str):
    """Return stored chat history for a tester."""
    try:
        normalized = ensure_allowed_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    history = fetch_chat_history(normalized)
    return ChatHistoryResponse(**history)


@router.delete("/chat/history/{username}/{message_id}")
async def delete_chat_message_route(username: str, message_id: str):
    """Delete a specific message from a user's chat history."""
    try:
        normalized = ensure_allowed_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    deleted = delete_chat_message(normalized, message_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"message": "Message deleted"}


@router.post("/chat/favorites/{username}/{message_id}")
async def set_chat_favorite(username: str, message_id: str, request: FavoriteRequest):
    try:
        normalized = ensure_allowed_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    updated = set_message_favorite(normalized, message_id, request.is_favorite)
    if not updated:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"message": "Favorite updated"}


@router.get("/chat/favorites/{username}", response_model=FavoritesResponse)
async def list_favorites(username: str):
    try:
        normalized = ensure_allowed_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    favorites = get_favorite_messages(normalized)

    formatted: List[FavoriteMessageResponse] = []
    for item in favorites:
        message_data = item.get("message", {})
        if isinstance(message_data.get("timestamp"), str):
            message_data["timestamp"] = datetime.fromisoformat(message_data["timestamp"])
        message = ChatMessage(**message_data)
        formatted.append(
            FavoriteMessageResponse(
                message=message,
                question=item.get("question"),
                question_id=item.get("question_id"),
            )
        )

    return FavoritesResponse(username=normalized, favorites=formatted)

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Process a chat question and return Cypher query with results."""
    try:
        username = ensure_allowed_username(request.username)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    history_messages: List[Dict[str, Any]] = [
        {
            "id": str(uuid4()),
            "role": "user",
            "content": request.question,
            "timestamp": datetime.utcnow(),
            "is_favorite": False,
        }
    ]

    try:
        result = await graphrag_service.process_question(
            question=request.question,
            execute_cypher=request.execute_cypher,
            output_mode=request.output_mode,
        )

        assistant_message = {
            "id": str(uuid4()),
            "role": "assistant",
            "content": result.get("summary") or "Query executed successfully",
            "cypher": result.get("cypher"),
            "results": result.get("results"),
            "summary": result.get("summary"),
            "examples": result.get("examples_used"),
            "error": result.get("error"),
            "timestamp": datetime.utcnow(),
            "is_favorite": False,
            "timings": result.get("timings"),
        }
        history_messages.append(assistant_message)

        result["username"] = username
        result["message_id"] = assistant_message["id"]
        return ChatResponse(**result)
    except Exception as e:
        error_message = {
            "id": str(uuid4()),
            "role": "assistant",
            "content": f"Error: {str(e)}",
            "error": str(e),
            "timestamp": datetime.utcnow(),
            "is_favorite": False,
        }
        history_messages.append(error_message)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        append_chat_messages(username, history_messages)


@router.websocket("/chat/stream")
async def chat_stream(websocket: WebSocket):
    """WebSocket endpoint for streaming chat responses."""
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            question = message.get("question")
            username = message.get("username")

            if not question:
                await websocket.send_json(
                    {"type": "error", "message": "Question is required"}
                )
                continue

            if not username:
                await websocket.send_json(
                    {"type": "error", "message": "Username is required"}
                )
                continue

            try:
                ensure_allowed_username(username)
            except ValueError as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                continue

            await websocket.send_json(
                {"type": "status", "message": "Processing question..."}
            )

            async for chunk in graphrag_service.process_question_stream(
                question=question,
                execute_cypher=message.get("execute_cypher", True),
                output_mode=message.get("output_mode", "chat"),
            ):
                await websocket.send_json(chunk)

            await websocket.send_json({"type": "complete"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({"type": "error", "message": str(e)})

