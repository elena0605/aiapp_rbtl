"""Map internal pipeline failures to safe user-facing chat copy."""

from __future__ import annotations

from typing import Optional

_INTERNAL_MARKERS = (
    "cypher query syntax validation failed",
    "syntax validation error",
    "cypher query validation failed",
    "cypher validation failed",
    "stage 2 cypher validation failed",
    "neo.clienterror",
    "read-only violation",
    "validation_details",
    "type mismatch:",
    "execution:",
    "structural cypher could not be validated",
    "structural cypher failed to execute",
)

QUERY_FAILURE = (
    "We couldn't answer that question right now. "
    "Try rephrasing it or broadening the area or topic you're asking about."
)

HYBRID_STRUCTURAL_FAILURE = (
    "We found creators discussing that topic, but couldn't apply the location "
    "or audience filter you asked for. Try rephrasing the area or demographic."
)

GENERIC_CHAT_FAILURE = (
    "Something went wrong while processing your question. Please try again."
)


def is_internal_error_message(message: Optional[str]) -> bool:
    if not message or not message.strip():
        return False
    lower = message.strip().lower()
    return any(marker in lower for marker in _INTERNAL_MARKERS)


def _friendly_fallback(route_type: Optional[str]) -> str:
    if route_type == "hybrid_media":
        return HYBRID_STRUCTURAL_FAILURE
    return QUERY_FAILURE


def assistant_content(
    *,
    error: Optional[str] = None,
    summary: Optional[str] = None,
    route_type: Optional[str] = None,
    fallback: str = "Query executed successfully",
) -> str:
    """Primary assistant message text — never raw validation/Neo4j errors."""
    if summary and summary.strip():
        return summary.strip()
    if error and error.strip() and not is_internal_error_message(error):
        return error.strip()
    if error and is_internal_error_message(error):
        return _friendly_fallback(route_type)
    return fallback


def sanitize_user_error(
    raw_error: Optional[str],
    *,
    summary: Optional[str] = None,
    route_type: Optional[str] = None,
) -> Optional[str]:
    """``error`` field for API/history — None keeps the message out of error UI state."""
    if summary and summary.strip():
        return None
    if not raw_error or not raw_error.strip():
        return None
    if is_internal_error_message(raw_error):
        return None
    return raw_error.strip()
