"""Chat endpoints for GraphRAG with chat history persistence."""

from datetime import datetime
import json
import logging
from typing import Optional, List, Dict, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException  # pyright: ignore[reportMissingImports]
from pydantic import BaseModel

from backend.app.services.chat_sessions import (
    append_chat_messages,
    ensure_allowed_username,
    fetch_chat_history,
    fetch_recent_messages,
    list_test_users,
    delete_chat_message,
    set_message_favorite,
    get_favorite_messages,
)
router = APIRouter()


def _get_graphrag_service():
    """Get the shared GraphRAGService instance from the main app (warmed up at startup)."""
    from backend.app.main import graphrag_service
    return graphrag_service


class ChatMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    route_type: Optional[str] = None  # "analytics" or "cypher"
    cypher: Optional[str] = None
    tool_name: Optional[str] = None  # For analytics results
    tool_inputs: Optional[Dict[str, Any]] = None  # For analytics results
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
    route_type: Optional[str] = None  # "analytics", "cypher", "visualization", "off_topic", "chitchat", "guardrail"
    intent: Optional[str] = None
    intent_confidence: Optional[float] = None
    rewritten_question: Optional[str] = None
    cypher: Optional[str] = None
    tool_name: Optional[str] = None
    tool_inputs: Optional[Dict[str, Any]] = None
    results: Optional[List[Dict[str, Any]]] = None
    summary: Optional[str] = None
    examples_used: Optional[List[Dict[str, Any]]] = None
    visualization: Optional[Dict[str, Any]] = None  # Chart spec for frontend rendering
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

    # Fetch recent conversation history for intent routing context
    recent_history = fetch_recent_messages(username, n=10)

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
        result = await _get_graphrag_service().process_question(
            question=request.question,
            execute_cypher=request.execute_cypher,
            output_mode=request.output_mode,
            conversation_history=recent_history,
        )

        error_msg = result.get("error")
        if error_msg:
            logging.warning(f"Chat API: Error in result: {error_msg}")
            content = error_msg
            result["summary"] = None
        else:
            content = result.get("summary") or "Query executed successfully"

        assistant_message = {
            "id": str(uuid4()),
            "role": "assistant",
            "content": content,
            "route_type": None if error_msg else result.get("route_type"),
            "cypher": result.get("cypher"),
            "tool_name": None if error_msg else result.get("tool_name"),
            "tool_inputs": None if error_msg else result.get("tool_inputs"),
            "results": None if error_msg else result.get("results"),
            "summary": None if error_msg else result.get("summary"),
            "examples": None if error_msg else result.get("examples_used"),
            "visualization": None if error_msg else result.get("visualization"),
            "error": error_msg,
            "timestamp": datetime.utcnow(),
            "is_favorite": False,
            "timings": None if error_msg else result.get("timings"),
        }
        history_messages.append(assistant_message)

        if error_msg:
            response_data = {
                "username": username,
                "question": request.question,
                "error": error_msg,
                "cypher": result.get("cypher"),
                "intent": result.get("intent"),
                "intent_confidence": result.get("intent_confidence"),
                "message_id": assistant_message["id"],
            }
        else:
            response_data = {
                "username": username,
                "question": request.question,
                "route_type": result.get("route_type"),
                "intent": result.get("intent"),
                "intent_confidence": result.get("intent_confidence"),
                "rewritten_question": result.get("rewritten_question"),
                "cypher": result.get("cypher"),
                "tool_name": result.get("tool_name"),
                "tool_inputs": result.get("tool_inputs"),
                "results": result.get("results"),
                "summary": result.get("summary"),
                "examples_used": result.get("examples_used"),
                "visualization": result.get("visualization"),
                "error": None,
                "timings": result.get("timings"),
                "message_id": assistant_message["id"],
            }
        return ChatResponse(**response_data)
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logging.error(f"Chat API: Exception occurred: {e}\n{error_trace}")
        error_message = {
            "id": str(uuid4()),
            "role": "assistant",
            "content": f"Error: {str(e)}",
            "error": str(e),
            "timestamp": datetime.utcnow(),
            "is_favorite": False,
        }
        history_messages.append(error_message)
        # Return error response instead of raising HTTPException to show error in UI
        return ChatResponse(
            username=username,
            question=request.question,
            error=str(e),
            message_id=error_message["id"],
        )
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
                normalized_ws_user = ensure_allowed_username(username)
            except ValueError as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                continue

            recent_history = fetch_recent_messages(normalized_ws_user, n=10)

            await websocket.send_json(
                {"type": "status", "message": "Processing question..."}
            )

            async for chunk in _get_graphrag_service().process_question_stream(
                question=question,
                execute_cypher=message.get("execute_cypher", True),
                output_mode=message.get("output_mode", "chat"),
                conversation_history=recent_history,
            ):
                await websocket.send_json(chunk)

            await websocket.send_json({"type": "complete"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({"type": "error", "message": str(e)})


@router.get("/chat/analytics-tools")
async def list_analytics_tools():
    """Return available graph analytics tools and example questions."""
    try:
        from ai.agent import GraphAnalyticsAgent
        
        # Create a temporary agent to get tool configs (doesn't connect to MCP)
        agent = GraphAnalyticsAgent(use_llm_selector=False)  # Don't need LLM for listing
        tools = agent.list_tools()
        
        tools_info = []
        for tool in tools:
            tools_info.append({
                "name": tool.name,
                "description": tool.description,
                "keywords": list(tool.keywords),
                "defaults": tool.defaults,
            })
        
        return {
            "tools": tools_info,
            "note": "These tools are available for graph analytics questions. Ask questions naturally and the system will route to the appropriate tool."
        }
    except Exception as e:
        return {
            "tools": [],
            "error": str(e),
            "note": "Failed to load analytics tools. Ensure the agent is properly configured."
        }

