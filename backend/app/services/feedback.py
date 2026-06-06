"""Feedback storage and email notification service."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from backend.app.services.mongodb import get_feedback_collection

logger = logging.getLogger(__name__)

# Keep SMTP bodies within practical limits; full rows are still stored in MongoDB feedback doc.
MAX_EMAIL_RETRIEVAL_JSON_CHARS = 400_000


def store_feedback(
    message_id: str,
    username: str,
    rating: str,
    comment: Optional[str] = None,
    question: Optional[str] = None,
    answer: Optional[str] = None,
    cypher: Optional[str] = None,
    route_type: Optional[str] = None,
    retrieval_results: Optional[List[Dict[str, Any]]] = None,
    per_platform: Optional[Dict[str, Any]] = None,
    stage1: Optional[Dict[str, Any]] = None,
) -> str:
    """Persist a feedback document in MongoDB and return its id."""
    collection = get_feedback_collection()
    doc = {
        "message_id": message_id,
        "username": username,
        "rating": rating,
        "comment": comment,
        "question": question,
        "answer": answer,
        "cypher": cypher,
        "route_type": route_type,
        "retrieval_results": retrieval_results,
        "per_platform": per_platform,
        "stage1": stage1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    result = collection.insert_one(doc)
    logger.info("Feedback stored: message_id=%s rating=%s", message_id, rating)
    return str(result.inserted_id)


def _format_retrieval_results_for_email(
    results: Optional[List[Dict[str, Any]]],
    *,
    per_platform: Optional[Dict[str, Any]] = None,
    stage1: Optional[Dict[str, Any]] = None,
) -> str:
    """Serialize full retrieval rows for the feedback email body."""
    sections: List[str] = []
    if results:
        try:
            body = json.dumps(results, indent=2, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            body = repr(results)
        if len(body) > MAX_EMAIL_RETRIEVAL_JSON_CHARS:
            body = (
                body[:MAX_EMAIL_RETRIEVAL_JSON_CHARS]
                + f"\n\n… truncated ({len(results)} rows; email size limit)"
            )
        sections.append(f"--- Retrieval results ({len(results)} rows) ---\n{body}")

    if per_platform:
        try:
            plat = json.dumps(per_platform, indent=2, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            plat = repr(per_platform)
        if len(plat) > MAX_EMAIL_RETRIEVAL_JSON_CHARS // 2:
            plat = plat[: MAX_EMAIL_RETRIEVAL_JSON_CHARS // 2] + "\n… truncated"
        sections.append(f"--- Per-platform ---\n{plat}")

    if stage1:
        try:
            s1 = json.dumps(stage1, indent=2, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            s1 = repr(stage1)
        if len(s1) > MAX_EMAIL_RETRIEVAL_JSON_CHARS // 2:
            s1 = s1[: MAX_EMAIL_RETRIEVAL_JSON_CHARS // 2] + "\n… truncated"
        sections.append(f"--- Stage 1 (hybrid) ---\n{s1}")

    return "\n\n".join(sections) if sections else "(no retrieval rows stored for this message)"


def _build_email_body(
    rating: str,
    username: str,
    question: Optional[str],
    answer: Optional[str],
    cypher: Optional[str],
    comment: Optional[str],
    route_type: Optional[str],
    retrieval_results: Optional[List[Dict[str, Any]]] = None,
    per_platform: Optional[Dict[str, Any]] = None,
    stage1: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a plain-text email body from feedback fields."""
    icon = "👍" if rating == "up" else "👎"
    lines = [
        f"New feedback received {icon}",
        f"",
        f"Rating:     {rating.upper()}",
        f"User:       {username}",
        f"Route:      {route_type or 'N/A'}",
        f"",
        f"--- Question ---",
        question or "(not provided)",
        f"",
        f"--- Answer (summary) ---",
        answer or "(not provided)",
    ]
    if cypher:
        lines += ["", "--- Generated Cypher ---", cypher]

    retrieval_block = _format_retrieval_results_for_email(
        retrieval_results, per_platform=per_platform, stage1=stage1
    )
    if route_type in ("media_retrieval", "hybrid_media") or retrieval_results:
        lines += ["", retrieval_block]

    if comment:
        lines += ["", "--- User Comment ---", comment]
    return "\n".join(lines)


def _send_email_sync(
    subject: str,
    body: str,
) -> None:
    """Send an email via SMTP (blocking). Called inside run_in_executor."""
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    sender = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    recipient = os.getenv("FEEDBACK_EMAIL_TO", "bojan.2110@gmail.com")

    if not sender or not password:
        logger.warning("SMTP credentials not configured; skipping email notification")
        return

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)

    logger.info("Feedback email sent to %s", recipient)


async def send_feedback_email(
    rating: str,
    username: str,
    question: Optional[str] = None,
    answer: Optional[str] = None,
    cypher: Optional[str] = None,
    comment: Optional[str] = None,
    route_type: Optional[str] = None,
    retrieval_results: Optional[List[Dict[str, Any]]] = None,
    per_platform: Optional[Dict[str, Any]] = None,
    stage1: Optional[Dict[str, Any]] = None,
) -> None:
    """Send a feedback notification email asynchronously (fire-and-forget)."""
    icon = "👍" if rating == "up" else "👎"
    subject = f"[GraphRAG Feedback] {icon} {rating.upper()} from {username}"
    body = _build_email_body(
        rating,
        username,
        question,
        answer,
        cypher,
        comment,
        route_type,
        retrieval_results=retrieval_results,
        per_platform=per_platform,
        stage1=stage1,
    )

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _send_email_sync, subject, body)
    except Exception as exc:
        logger.warning("Failed to send feedback email: %s", exc)
