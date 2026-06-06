"""Heavy chat message fields stored outside the per-user session document.

Cosmos DB caps each document at ~2 MB. Media retrieval answers can be large;
this collection holds full archival payloads keyed by (username, message_id).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pymongo.errors import WriteError

from backend.app.services.mongodb import get_chat_message_payloads_collection

logger = logging.getLogger(__name__)

COSMOS_MAX_PAYLOAD_BYTES = 1_900_000

# Fields stored in chat_message_payloads (full fidelity, not trimmed).
PAYLOAD_FIELD_NAMES: Tuple[str, ...] = (
    "results",
    "per_platform",
    "stage1",
    "retrieval_trace",
    "hybrid_audit",
    "visualization",
    "examples",
)


def _json_size(obj: Any) -> int:
    try:
        return len(json.dumps(obj, default=str))
    except (TypeError, ValueError):
        return 0


def slim_payload_for_storage(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop archival bloat before Cosmos write; keep hybrid audit IDs for debugging."""
    slim = {k: payload[k] for k in PAYLOAD_FIELD_NAMES if k in payload}
    stage1 = slim.pop("stage1", None)
    if slim.get("hybrid_audit"):
        # Full stage1 rows are large; candidate IDs live in hybrid_audit.candidate_keys.
        return slim
    if isinstance(stage1, dict):
        keys = stage1.get("candidate_keys") or {}
        if keys:
            slim["stage1_audit"] = {
                "retriever_name": stage1.get("retriever_name"),
                "status": stage1.get("status"),
                "candidate_counts": {
                    kind: len(vals) if isinstance(vals, list) else vals
                    for kind, vals in keys.items()
                },
            }
    return slim


def extract_payload_fields(message: Dict[str, Any]) -> Dict[str, Any]:
    """Return payload fields present on an assistant message."""
    if not message or message.get("role") != "assistant":
        return {}
    return {k: message[k] for k in PAYLOAD_FIELD_NAMES if message.get(k) is not None}


def has_payload_fields(message: Dict[str, Any]) -> bool:
    return bool(extract_payload_fields(message))


def split_message_for_storage(message: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Split into session metadata row and optional payload document."""
    if not message:
        return {}, None
    if message.get("role") != "assistant" or not has_payload_fields(message):
        return dict(message), None

    meta = dict(message)
    payload = extract_payload_fields(message)
    for key in PAYLOAD_FIELD_NAMES:
        meta.pop(key, None)
    meta["has_payload"] = True
    return meta, payload


def merge_payload_into_message(
    message: Dict[str, Any], payload_doc: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Overlay stored payload onto a session metadata message."""
    if not payload_doc:
        return message
    merged = dict(message)
    for key in PAYLOAD_FIELD_NAMES:
        if key in payload_doc and payload_doc[key] is not None:
            merged[key] = payload_doc[key]
    return merged


def save_message_payload(
    username: str,
    message_id: str,
    payload: Dict[str, Any],
) -> bool:
    """Upsert full payload for one assistant message. Returns False if too large for Cosmos."""
    if not payload or not message_id:
        return True

    payload = slim_payload_for_storage(payload)
    size = _json_size(payload)
    if size > COSMOS_MAX_PAYLOAD_BYTES:
        logger.error(
            "Payload for %s message %s exceeds Cosmos limit (%d bytes)",
            username,
            message_id,
            size,
        )
        return False

    collection = get_chat_message_payloads_collection()
    doc = {
        "username": username,
        "message_id": message_id,
        **payload,
        "updated_at": datetime.utcnow(),
    }
    try:
        collection.replace_one(
            {"username": username, "message_id": message_id},
            doc,
            upsert=True,
        )
        return True
    except WriteError as exc:
        if "too large" in str(exc).lower() or getattr(exc, "code", None) == 16:
            logger.error(
                "Cosmos DB rejected payload write for %s message %s: %s",
                username,
                message_id,
                exc,
            )
            return False
        raise


def save_pending_payloads(
    username: str, pending: List[Tuple[str, Dict[str, Any]]]
) -> None:
    """Persist slimmed payload documents (safe to run in a background task)."""
    for message_id, payload in pending:
        if not save_message_payload(username, message_id, payload):
            logger.warning(
                "Could not persist payload for %s message %s", username, message_id
            )


def delete_message_payload(username: str, message_id: str) -> None:
    collection = get_chat_message_payloads_collection()
    collection.delete_one({"username": username, "message_id": message_id})


def fetch_payloads_by_message_ids(
    username: str, message_ids: List[str]
) -> Dict[str, Dict[str, Any]]:
    """Load payload documents keyed by message_id."""
    if not message_ids:
        return {}
    collection = get_chat_message_payloads_collection()
    cursor = collection.find(
        {"username": username, "message_id": {"$in": message_ids}},
        {"_id": 0},
    )
    out: Dict[str, Dict[str, Any]] = {}
    for doc in cursor:
        mid = doc.get("message_id")
        if mid:
            out[mid] = doc
    return out


def attach_payloads_to_messages(
    username: str, messages: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Merge external payloads into assistant messages for API/UI responses."""
    assistant_ids = [
        m["id"]
        for m in messages
        if m.get("role") == "assistant" and m.get("id")
    ]
    payloads = fetch_payloads_by_message_ids(username, assistant_ids)
    if not payloads:
        return messages

    merged: List[Dict[str, Any]] = []
    for msg in messages:
        mid = msg.get("id")
        if msg.get("role") == "assistant" and mid and mid in payloads:
            merged.append(merge_payload_into_message(msg, payloads[mid]))
        else:
            merged.append(msg)
    return merged


def get_merged_assistant_message(
    username: str, message_id: str
) -> Optional[Dict[str, Any]]:
    """Return session metadata + payload for one assistant message (feedback, email)."""
    from backend.app.services.mongodb import get_chat_sessions_collection

    collection = get_chat_sessions_collection()
    doc = collection.find_one({"username": username}, {"messages": 1, "_id": 0})
    if not doc:
        return None
    for msg in doc.get("messages") or []:
        if msg.get("id") == message_id and msg.get("role") == "assistant":
            payloads = fetch_payloads_by_message_ids(username, [message_id])
            return merge_payload_into_message(msg, payloads.get(message_id))
    return None
