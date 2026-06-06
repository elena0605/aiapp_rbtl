"""Chat endpoints for GraphRAG with chat history persistence."""

from datetime import datetime
import json
import logging
import threading
from typing import Optional, List, Dict, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Query  # pyright: ignore[reportMissingImports]
from pydantic import BaseModel

from backend.app.services.chat_sessions import (
    append_chat_metadata,
    ensure_allowed_username,
    fetch_chat_history,
    fetch_recent_messages,
    list_test_users,
    delete_chat_message,
    maybe_prune_chat_session,
    set_message_favorite,
    set_message_feedback,
    get_favorite_messages,
)
from backend.app.services.chat_message_payloads import save_pending_payloads
from utils.user_facing_errors import (
    GENERIC_CHAT_FAILURE,
    assistant_content,
    sanitize_user_error,
)

router = APIRouter()


def _save_payloads_safe(
    username: str, pending: List[tuple[str, Dict[str, Any]]]
) -> None:
    """Persist heavy retrieval fields after the HTTP response has been sent."""
    try:
        save_pending_payloads(username, pending)
    except Exception as exc:
        logging.error("Failed to save chat payloads for %s: %s", username, exc)


def _maybe_prune_session_safe(username: str) -> None:
    """Shrink oversized session docs without blocking the chat response."""
    try:
        maybe_prune_chat_session(username)
    except Exception as exc:
        logging.error("Failed to prune chat session for %s: %s", username, exc)


def _schedule_daemon(target, *args: Any) -> None:
    """Fire-and-forget background work without blocking uvicorn reload/shutdown."""
    threading.Thread(target=target, args=args, daemon=True).start()


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
    visualization: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: datetime
    is_favorite: bool = False
    timings: Optional[Dict[str, float]] = None
    feedback: Optional[str] = None
    retrieval_trace: Optional[Dict[str, Any]] = None
    research_notes: Optional[List[str]] = None
    status: Optional[str] = None
    deduped_by_influencer: Optional[bool] = None
    per_platform: Optional[Dict[str, Any]] = None
    stage1: Optional[Dict[str, Any]] = None
    candidate_counts: Optional[Dict[str, int]] = None
    hybrid_audit: Optional[Dict[str, Any]] = None


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
    retrieval_trace: Optional[Dict[str, Any]] = None
    research_notes: Optional[List[str]] = None
    status: Optional[str] = None
    deduped_by_influencer: Optional[bool] = None
    per_platform: Optional[Dict[str, Any]] = None
    stage1: Optional[Dict[str, Any]] = None
    candidate_counts: Optional[Dict[str, int]] = None
    hybrid_audit: Optional[Dict[str, Any]] = None


class FavoriteRequest(BaseModel):
    is_favorite: bool = True


class FeedbackSubmitRequest(BaseModel):
    username: str
    message_id: str
    rating: str  # "up" or "down"
    comment: Optional[str] = None
    question: Optional[str] = None
    answer: Optional[str] = None
    cypher: Optional[str] = None
    route_type: Optional[str] = None


@router.get("/chat/users")
async def list_chat_users():
    """Return available tester usernames."""
    return {"users": list_test_users()}


@router.get("/chat/history/{username}", response_model=ChatHistoryResponse)
async def get_chat_history(
    username: str,
    limit: int = Query(120, ge=1, le=500, description="Max messages to return (most recent)"),
):
    """Return stored chat history for a tester."""
    try:
        normalized = ensure_allowed_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    history = fetch_chat_history(normalized, limit=limit)
    for msg in history.get("messages", []):
        timings = msg.get("timings")
        if isinstance(timings, dict):
            for k, v in list(timings.items()):
                if isinstance(v, list):
                    timings[k] = sum(v)
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


@router.post("/chat/feedback")
async def submit_feedback(request: FeedbackSubmitRequest):
    """Store user feedback (thumbs up/down + optional comment) and send email notification."""
    from backend.app.services.feedback import store_feedback, send_feedback_email
    from backend.app.services.chat_message_payloads import get_merged_assistant_message

    if request.rating not in ("up", "down"):
        raise HTTPException(status_code=400, detail="rating must be 'up' or 'down'")

    try:
        normalized = ensure_allowed_username(request.username)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    merged = get_merged_assistant_message(normalized, request.message_id)
    retrieval_results = merged.get("results") if merged else None
    per_platform = merged.get("per_platform") if merged else None
    stage1 = merged.get("stage1") if merged else None
    route_type = request.route_type or (merged.get("route_type") if merged else None)

    store_feedback(
        message_id=request.message_id,
        username=normalized,
        rating=request.rating,
        comment=request.comment,
        question=request.question,
        answer=request.answer,
        cypher=request.cypher,
        route_type=route_type,
        retrieval_results=retrieval_results,
        per_platform=per_platform,
        stage1=stage1,
    )

    set_message_feedback(normalized, request.message_id, request.rating)

    await send_feedback_email(
        rating=request.rating,
        username=normalized,
        question=request.question,
        answer=request.answer,
        cypher=request.cypher,
        comment=request.comment,
        route_type=route_type,
        retrieval_results=retrieval_results,
        per_platform=per_platform,
        stage1=stage1,
    )

    return {"message": "Feedback submitted successfully"}


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
    pending_payloads: List[tuple[str, Dict[str, Any]]] = []

    try:
        result = await _get_graphrag_service().process_question(
            question=request.question,
            execute_cypher=request.execute_cypher,
            output_mode=request.output_mode,
            conversation_history=recent_history,
        )

        raw_error = result.get("error")
        if raw_error:
            logging.warning("Chat API: internal error in result (sanitized for user): %s", raw_error)
        error_msg = sanitize_user_error(
            raw_error,
            summary=result.get("summary"),
            route_type=result.get("route_type"),
        )
        content = assistant_content(
            error=raw_error,
            summary=result.get("summary"),
            route_type=result.get("route_type"),
        )

        assistant_message = {
            "id": str(uuid4()),
            "role": "assistant",
            "content": content,
            "route_type": result.get("route_type"),
            "cypher": result.get("cypher"),
            "tool_name": result.get("tool_name"),
            "tool_inputs": result.get("tool_inputs"),
            "results": result.get("results"),
            "summary": result.get("summary"),
            "examples": result.get("examples_used"),
            "visualization": result.get("visualization"),
            "error": error_msg,
            "timestamp": datetime.utcnow(),
            "is_favorite": False,
            "timings": result.get("timings"),
            "retrieval_trace": result.get("retrieval_trace"),
            "research_notes": result.get("research_notes"),
            "status": result.get("status"),
            "deduped_by_influencer": result.get("deduped_by_influencer"),
            "per_platform": result.get("per_platform"),
            "stage1": result.get("stage1"),
            "candidate_counts": result.get("candidate_counts"),
            "hybrid_audit": result.get("hybrid_audit"),
        }
        history_messages.append(assistant_message)
        pending_payloads = append_chat_metadata(username, history_messages)

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
                "retrieval_trace": result.get("retrieval_trace"),
                "research_notes": result.get("research_notes"),
                "status": result.get("status"),
                "deduped_by_influencer": result.get("deduped_by_influencer"),
                "per_platform": result.get("per_platform"),
                "stage1": result.get("stage1"),
                "candidate_counts": result.get("candidate_counts"),
                "hybrid_audit": result.get("hybrid_audit"),
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
            "content": GENERIC_CHAT_FAILURE,
            "error": None,
            "timestamp": datetime.utcnow(),
            "is_favorite": False,
        }
        history_messages.append(error_message)
        pending_payloads = append_chat_metadata(username, history_messages)
        return ChatResponse(
            username=username,
            question=request.question,
            summary=GENERIC_CHAT_FAILURE,
            message_id=error_message["id"],
        )
    finally:
        if pending_payloads:
            _schedule_daemon(_save_payloads_safe, username, pending_payloads)
        if pending_payloads or history_messages:
            _schedule_daemon(_maybe_prune_session_safe, username)


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

