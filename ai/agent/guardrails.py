"""Lightweight guardrails for the GraphRAG chat pipeline.

Runs *before* intent classification to catch obvious safety issues
cheaply (no LLM call needed).  More sophisticated checks can be added
later (e.g., LLM-based prompt-injection detection).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("Guardrails")

_MAX_QUESTION_LENGTH = 2000

_PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)", re.I),
    re.compile(r"disregard\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)", re.I),
    re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.I),
    re.compile(r"pretend\s+you\s+are\s+", re.I),
    re.compile(r"system\s*:\s*", re.I),
    re.compile(r"\brole\s*:\s*(system|admin)", re.I),
    re.compile(r"(WRITE|CREATE|DELETE|MERGE|SET|REMOVE|DROP)\s+", re.I),
]

_SENSITIVE_DATA_PATTERNS = [
    re.compile(r"\bUserID\b", re.I),
    re.compile(r"\bpassword\b", re.I),
    re.compile(r"\bcredential\b", re.I),
    re.compile(r"\bapi[_\s]?key\b", re.I),
    re.compile(r"\bsecret\b", re.I),
]


@dataclass
class GuardrailResult:
    """Outcome of a guardrail check."""

    passed: bool
    reason: Optional[str] = None
    category: Optional[str] = None  # "injection", "length", "sensitive_data"


def check(question: str) -> GuardrailResult:
    """Run all guardrail checks against a user message.

    Returns a ``GuardrailResult`` — when ``passed`` is ``False`` the
    caller should return a refusal message and skip further processing.
    """
    if not question or not question.strip():
        return GuardrailResult(
            passed=False,
            reason="Please enter a question.",
            category="empty",
        )

    if len(question) > _MAX_QUESTION_LENGTH:
        logger.warning(
            "Guardrail: question too long (%d chars, max %d)",
            len(question),
            _MAX_QUESTION_LENGTH,
        )
        return GuardrailResult(
            passed=False,
            reason=(
                f"Your message is too long ({len(question)} characters). "
                f"Please keep it under {_MAX_QUESTION_LENGTH} characters."
            ),
            category="length",
        )

    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(question):
            logger.warning(
                "Guardrail: prompt injection pattern detected: %s",
                pattern.pattern,
            )
            return GuardrailResult(
                passed=False,
                reason=(
                    "Your message was flagged by our safety system. "
                    "Please rephrase your question about the knowledge graph data."
                ),
                category="injection",
            )

    for pattern in _SENSITIVE_DATA_PATTERNS:
        if pattern.search(question):
            logger.info(
                "Guardrail: sensitive data request detected: %s",
                pattern.pattern,
            )
            return GuardrailResult(
                passed=False,
                reason=(
                    "For privacy reasons, queries about sensitive personal "
                    "identifiers (UserID, passwords, etc.) are not allowed."
                ),
                category="sensitive_data",
            )

    return GuardrailResult(passed=True)
