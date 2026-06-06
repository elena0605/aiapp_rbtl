"""Session document size helpers (metadata-only messages).

Heavy fields live in ``chat_message_payloads`` — see ``chat_message_payloads.py``.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Dict, List

from backend.app.services.chat_message_payloads import PAYLOAD_FIELD_NAMES

logger = logging.getLogger(__name__)

# Cosmos DB document limit is 2 MB; keep headroom for BSON overhead.
COSMOS_MAX_SESSION_BYTES = 1_900_000


def _json_size(obj: Any) -> int:
    try:
        return len(json.dumps(obj, default=str))
    except (TypeError, ValueError):
        return 0


def slim_message_for_storage(message: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure no heavy payload fields remain on the session row (defensive)."""
    if not message:
        return dict(message)
    slim = dict(message)
    if slim.get("role") == "assistant":
        for key in PAYLOAD_FIELD_NAMES:
            slim.pop(key, None)
    return slim


def slim_messages_for_storage(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [slim_message_for_storage(m) for m in messages]


def estimate_session_bytes(username: str, messages: List[Dict[str, Any]]) -> int:
    return _json_size({"username": username, "messages": messages})


def prune_session_messages(
    messages: List[Dict[str, Any]], *, max_bytes: int = COSMOS_MAX_SESSION_BYTES
) -> List[Dict[str, Any]]:
    """Drop bulky metadata from oldest assistant messages until under size budget.

    Payload collection is unchanged; only inline legacy fields on session rows are cleared.
    """
    pruned = [copy.deepcopy(m) for m in messages]
    while pruned and estimate_session_bytes("", pruned) > max_bytes:
        removed = False
        for msg in pruned:
            if msg.get("role") != "assistant":
                continue
            for key in ("cypher", "tool_inputs", "research_notes", "timings"):
                if msg.get(key):
                    msg[key] = None
                    removed = True
                    break
            if removed:
                break
            if msg.get("content") and len(str(msg["content"])) > 2000:
                msg["content"] = (msg["content"] or "")[:2000] + "…"
                msg["storage_note"] = "Content truncated in session metadata to fit database limit."
                removed = True
                break
        if not removed:
            break
    return pruned
