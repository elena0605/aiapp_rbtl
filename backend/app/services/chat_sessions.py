"""Chat session persistence helpers."""

from __future__ import annotations

from datetime import datetime
from typing import List, Dict, Any, Optional

from backend.app.services.mongodb import get_chat_sessions_collection

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


def fetch_chat_history(username: str) -> Dict[str, Any]:
    """Fetch existing chat history for a user (empty list if none)."""
    normalized = ensure_allowed_username(username)
    collection = get_chat_sessions_collection()
    document = collection.find_one({"username": normalized}, {"_id": 0})
    if not document:
        return {"username": normalized, "messages": []}
    messages = document.get("messages", [])
    for message in messages:
        message.setdefault("is_favorite", False)
    document["messages"] = messages
    document["username"] = normalized
    return document


def append_chat_messages(username: str, messages: List[Dict[str, Any]]) -> None:
    """Append messages to the user's chat history."""
    if not messages:
        return
    normalized = ensure_allowed_username(username)
    now = datetime.utcnow()
    collection = get_chat_sessions_collection()
    collection.update_one(
        {"username": normalized},
        {
            "$setOnInsert": {"username": normalized, "created_at": now},
            "$push": {"messages": {"$each": [dict(msg, is_favorite=False) for msg in messages]}},
            "$set": {"updated_at": now},
        },
        upsert=True,
    )


def delete_chat_message(username: str, message_id: str) -> bool:
    """Delete a message from the user's chat history."""
    normalized = ensure_allowed_username(username)
    collection = get_chat_sessions_collection()
    doc = collection.find_one({"username": normalized}, {"messages": 1})
    if not doc or "messages" not in doc:
        return False

    messages = doc.get("messages", [])
    new_messages = [msg for msg in messages if msg.get("id") != message_id]
    if len(new_messages) == len(messages):
        return False

    collection.update_one(
        {"username": normalized},
        {
            "$set": {"messages": new_messages, "updated_at": datetime.utcnow()},
        },
    )
    return True


def set_message_favorite(username: str, message_id: str, is_favorite: bool) -> bool:
    normalized = ensure_allowed_username(username)
    collection = get_chat_sessions_collection()
    doc = collection.find_one({"username": normalized}, {"messages": 1})
    if not doc or "messages" not in doc:
        return False

    messages = doc.get("messages", [])
    updated = False
    for message in messages:
        if message.get("id") == message_id:
            if message.get("is_favorite") == is_favorite:
                return True
            message["is_favorite"] = is_favorite
            updated = True
            break

    if not updated:
        return False

    collection.update_one(
        {"username": normalized},
        {"$set": {"messages": messages, "updated_at": datetime.utcnow()}},
    )
    return True


def get_favorite_messages(username: str) -> List[Dict[str, Any]]:
    normalized = ensure_allowed_username(username)
    collection = get_chat_sessions_collection()
    doc = collection.find_one({"username": normalized}, {"messages": 1})
    if not doc or "messages" not in doc:
        return []

    messages = doc.get("messages", [])
    favorites: List[Dict[str, Any]] = []

    for idx, message in enumerate(messages):
        if not message.get("is_favorite"):
            continue
        question: Optional[Dict[str, Any]] = None
        # find closest previous user message
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

