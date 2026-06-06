"""Chat session persistence helpers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from pymongo.errors import WriteError

from backend.app.services.mongodb import get_chat_sessions_collection
from backend.app.services.chat_message_storage import (
    COSMOS_MAX_SESSION_BYTES,
    estimate_session_bytes,
    prune_session_messages,
    slim_message_for_storage,
)
from backend.app.services.chat_message_payloads import (
    attach_payloads_to_messages,
    delete_message_payload,
    save_message_payload,
    save_pending_payloads,
    slim_payload_for_storage,
    split_message_for_storage,
    _json_size,
    COSMOS_MAX_PAYLOAD_BYTES,
)

logger = logging.getLogger(__name__)

TEST_USERNAMES = ["bojan", "roel", "famke", "scarlett"]
_ALLOWED_USERNAMES = {name.lower() for name in TEST_USERNAMES}


def normalize_username(username: str) -> str:
    """Normalize incoming username strings."""
    if not username:
        raise ValueError("Username is required")
    return username.strip().lower()


def ensure_allowed_username(username: str) -> str:
    """Validate that the username is in the tester allowlist."""
    normalized = normalize_username(username)
    if normalized not in _ALLOWED_USERNAMES:
        raise ValueError(f"Username '{username}' is not authorized")
    return normalized


def list_test_users() -> List[str]:
    """Return the allowed tester usernames (original casing)."""
    return TEST_USERNAMES


def _prepare_messages_for_session(
    username: str, messages: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Split payloads into their collection; return metadata rows for the session doc."""
    session_rows: List[Dict[str, Any]] = []
    for msg in messages:
        meta, payload = split_message_for_storage(msg)
        row = dict(slim_message_for_storage(meta), is_favorite=msg.get("is_favorite", False))
        if payload and msg.get("id"):
            ok = save_message_payload(username, msg["id"], payload)
            if not ok:
                row["payload_storage_note"] = (
                    "Full retrieval results could not be saved (document size limit)."
                )
        session_rows.append(row)
    return session_rows


def _save_messages(collection, normalized: str, messages: List[Dict[str, Any]]) -> None:
    """Persist messages, pruning if the session document exceeds Cosmos DB size."""
    if estimate_session_bytes(normalized, messages) > COSMOS_MAX_SESSION_BYTES:
        logger.warning(
            "Chat session for %s exceeds size budget; pruning older metadata fields",
            normalized,
        )
        messages = prune_session_messages(messages)
    try:
        collection.update_one(
            {"username": normalized},
            {"$set": {"messages": messages, "updated_at": datetime.utcnow()}},
        )
    except WriteError as exc:
        if "too large" in str(exc).lower() or getattr(exc, "code", None) == 16:
            logger.warning(
                "Cosmos DB rejected chat session write for %s; aggressive prune retry",
                normalized,
            )
            messages = prune_session_messages(messages)
            collection.update_one(
                {"username": normalized},
                {"$set": {"messages": messages, "updated_at": datetime.utcnow()}},
            )
            return
        raise


def fetch_chat_history(
    username: str,
    *,
    merge_payloads: bool = True,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Fetch chat history for a user; optionally merge full payloads for the UI."""
    normalized = ensure_allowed_username(username)
    collection = get_chat_sessions_collection()
    projection: Dict[str, Any] = {"_id": 0}
    if limit is not None and limit > 0:
        projection["messages"] = {"$slice": -int(limit)}
    document = collection.find_one({"username": normalized}, projection)
    if not document:
        return {"username": normalized, "messages": []}
    messages = list(document.get("messages") or [])
    for message in messages:
        message.setdefault("is_favorite", False)
    if merge_payloads and messages:
        messages = attach_payloads_to_messages(normalized, messages)
    return {"username": normalized, "messages": messages}


def fetch_recent_messages(username: str, n: int = 10) -> List[Dict[str, Any]]:
    """Return the last *n* messages (metadata only — no payload merge for LLM context)."""
    history = fetch_chat_history(username, merge_payloads=False, limit=n)
    return history.get("messages", [])


def _session_rows_and_pending_payloads(
    username: str, messages: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Tuple[str, Dict[str, Any]]]]:
    """Build session metadata rows and deferred payload writes."""
    session_rows: List[Dict[str, Any]] = []
    pending: List[Tuple[str, Dict[str, Any]]] = []
    for msg in messages:
        meta, payload = split_message_for_storage(msg)
        row = dict(slim_message_for_storage(meta), is_favorite=msg.get("is_favorite", False))
        if payload and msg.get("id"):
            slim = slim_payload_for_storage(payload)
            size = _json_size(slim)
            if size <= COSMOS_MAX_PAYLOAD_BYTES:
                row["has_payload"] = True
                pending.append((msg["id"], slim))
            else:
                logger.error(
                    "Payload for %s message %s still too large after slimming (%d bytes); "
                    "keeping answer fields inline on session row",
                    username,
                    msg["id"],
                    size,
                )
                row["has_payload"] = False
                row["payload_storage_note"] = (
                    "Full retrieval results could not be saved (document size limit)."
                )
                for key in ("results", "retrieval_trace"):
                    if slim.get(key) is not None:
                        row[key] = slim[key]
        session_rows.append(row)
    return session_rows, pending


def append_chat_metadata(username: str, messages: List[Dict[str, Any]]) -> List[Tuple[str, Dict[str, Any]]]:
    """Persist user + assistant rows before the HTTP response ends (fast $push only).

    Returns payload pairs to save asynchronously. Session pruning runs separately
    so we never rewrite the full history document on the hot path.
    """
    if not messages:
        return []
    normalized = ensure_allowed_username(username)
    now = datetime.utcnow()
    collection = get_chat_sessions_collection()

    to_push, pending = _session_rows_and_pending_payloads(normalized, messages)

    collection.update_one(
        {"username": normalized},
        {
            "$setOnInsert": {"username": normalized, "created_at": now},
            "$push": {"messages": {"$each": to_push}},
            "$set": {"updated_at": now},
        },
        upsert=True,
    )
    return pending


def maybe_prune_chat_session(username: str) -> None:
    """Trim session metadata when the document exceeds the Cosmos size budget."""
    normalized = ensure_allowed_username(username)
    collection = get_chat_sessions_collection()
    doc = collection.find_one({"username": normalized}, {"messages": 1})
    if not doc:
        return
    messages = list(doc.get("messages") or [])
    if estimate_session_bytes(normalized, messages) <= COSMOS_MAX_SESSION_BYTES:
        return
    logger.warning(
        "Chat session for %s exceeds size budget; pruning older metadata fields",
        normalized,
    )
    _save_messages(collection, normalized, prune_session_messages(messages))


def append_chat_messages(username: str, messages: List[Dict[str, Any]]) -> None:
    """Append messages and payloads in one shot (metadata + payload collection)."""
    pending = append_chat_metadata(username, messages)
    if pending:
        save_pending_payloads(ensure_allowed_username(username), pending)


def delete_chat_message(username: str, message_id: str) -> bool:
    """Delete a message from the user's chat history and its payload document."""
    normalized = ensure_allowed_username(username)
    collection = get_chat_sessions_collection()
    doc = collection.find_one({"username": normalized}, {"messages": 1})
    if not doc or "messages" not in doc:
        return False

    messages = doc.get("messages", [])
    new_messages = [msg for msg in messages if msg.get("id") != message_id]
    if len(new_messages) == len(messages):
        return False

    delete_message_payload(normalized, message_id)
    _save_messages(collection, normalized, new_messages)
    return True


def set_message_favorite(username: str, message_id: str, is_favorite: bool) -> bool:
    """Toggle favorite on one message without rewriting the full session document."""
    normalized = ensure_allowed_username(username)
    collection = get_chat_sessions_collection()
    result = collection.update_one(
        {"username": normalized, "messages.id": message_id},
        {
            "$set": {
                "messages.$.is_favorite": is_favorite,
                "updated_at": datetime.utcnow(),
            }
        },
    )
    return result.matched_count > 0


def set_message_feedback(username: str, message_id: str, rating: str) -> bool:
    """Persist a feedback rating ('up'/'down') on one message in chat history."""
    normalized = ensure_allowed_username(username)
    collection = get_chat_sessions_collection()
    result = collection.update_one(
        {"username": normalized, "messages.id": message_id},
        {
            "$set": {
                "messages.$.feedback": rating,
                "updated_at": datetime.utcnow(),
            }
        },
    )
    return result.matched_count > 0


def get_favorite_messages(username: str) -> List[Dict[str, Any]]:
    normalized = ensure_allowed_username(username)
    collection = get_chat_sessions_collection()
    doc = collection.find_one({"username": normalized}, {"messages": 1})
    if not doc or "messages" not in doc:
        return []

    from backend.app.services.chat_message_payloads import (
        fetch_payloads_by_message_ids,
        merge_payload_into_message,
    )

    messages = list(doc.get("messages", []))
    favorite_indices = [
        idx for idx, message in enumerate(messages) if message.get("is_favorite")
    ]
    if not favorite_indices:
        return []

    favorite_ids = [
        messages[idx]["id"]
        for idx in favorite_indices
        if messages[idx].get("id")
    ]
    payloads = fetch_payloads_by_message_ids(normalized, favorite_ids)

    favorites: List[Dict[str, Any]] = []
    for idx in favorite_indices:
        message = dict(messages[idx])
        mid = message.get("id")
        if mid and mid in payloads:
            message = merge_payload_into_message(message, payloads[mid])
        question: Optional[Dict[str, Any]] = None
        for prev in range(idx - 1, -1, -1):
            if messages[prev].get("role") == "user":
                question = messages[prev]
                break

        favorites.append(
            {
                "message": {k: v for k, v in message.items() if k != "_id"},
                "question": question["content"] if question else None,
                "question_id": question["id"] if question else None,
            }
        )

    return favorites
