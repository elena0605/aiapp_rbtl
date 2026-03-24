"""Feedback storage and email notification service."""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from backend.app.services.mongodb import get_feedback_collection

logger = logging.getLogger(__name__)


def store_feedback(
    message_id: str,
    username: str,
    rating: str,
    comment: Optional[str] = None,
    question: Optional[str] = None,
    answer: Optional[str] = None,
    cypher: Optional[str] = None,
    route_type: Optional[str] = None,
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
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    result = collection.insert_one(doc)
    logger.info("Feedback stored: message_id=%s rating=%s", message_id, rating)
    return str(result.inserted_id)


def _build_email_body(
    rating: str,
    username: str,
    question: Optional[str],
    answer: Optional[str],
    cypher: Optional[str],
    comment: Optional[str],
    route_type: Optional[str],
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
        f"--- Answer ---",
        answer or "(not provided)",
    ]
    if cypher:
        lines += ["", "--- Generated Cypher ---", cypher]
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
) -> None:
    """Send a feedback notification email asynchronously (fire-and-forget)."""
    icon = "👍" if rating == "up" else "👎"
    subject = f"[GraphRAG Feedback] {icon} {rating.upper()} from {username}"
    body = _build_email_body(rating, username, question, answer, cypher, comment, route_type)

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _send_email_sync, subject, body)
    except Exception as exc:
        logger.warning("Failed to send feedback email: %s", exc)
