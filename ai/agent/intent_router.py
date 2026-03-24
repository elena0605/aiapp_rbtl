"""Intent classification and routing for the GraphRAG chat pipeline.

Classifies user messages into actionable intents (graph_query, analytics,
follow_up, off_topic, chitchat) and rewrites follow-up messages into
self-contained questions using conversation history.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai.llmops.langfuse_client import create_completion, get_prompt_from_langfuse

logger = logging.getLogger("IntentRouter")

ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = ROOT / "ai" / "prompts"

DOMAIN_DESCRIPTION = (
    "youth health and well-being survey data (Person nodes with behavioral, "
    "lifestyle, and school-safety attributes), social media influencer data "
    "(TikTok users, YouTube channels, videos, comments, hashtags), and "
    "geographic/demographic data (Areas and Municipalities in the Netherlands "
    "with socio-economic indicators). Persons follow Influencers and live in "
    "Areas/Municipalities."
)

# Low-confidence threshold — below this we fall back to graph_query
_CONFIDENCE_THRESHOLD = 0.5


@dataclass
class IntentResult:
    """Result of intent classification."""

    intent: str
    confidence: float
    rewritten_question: Optional[str]
    reasoning: str
    original_question: str
    is_follow_up: bool = False

    @property
    def effective_question(self) -> str:
        """The question to pass downstream (rewritten for follow-ups)."""
        if self.rewritten_question:
            return self.rewritten_question
        return self.original_question


class IntentRouter:
    """Classifies user intent and provides the effective question for routing."""

    def __init__(
        self,
        *,
        llm_model: Optional[str] = None,
        confidence_threshold: float = _CONFIDENCE_THRESHOLD,
    ) -> None:
        self._llm_model = (
            llm_model
            or os.environ.get("INTENT_ROUTER_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or os.environ.get("OPEN_AI_MODEL")
        )
        if not self._llm_model:
            raise RuntimeError(
                "No LLM model configured for IntentRouter. "
                "Set INTENT_ROUTER_MODEL or OPENAI_MODEL."
            )
        self._confidence_threshold = confidence_threshold
        self._prompt = None

    def _get_prompt(self):
        """Load the intent classifier prompt (Langfuse with local fallback)."""
        if self._prompt is not None:
            return self._prompt

        prompt_label = os.environ.get("PROMPT_LABEL")
        try:
            self._prompt = get_prompt_from_langfuse(
                "graph.intent_classifier",
                langfuse_client=None,
                label=prompt_label,
            )
        except Exception as err:
            logger.warning(
                "Langfuse prompt fetch for intent_classifier failed (%s). "
                "Using local YAML fallback.",
                err,
            )
            self._prompt = self._load_local_prompt()
        return self._prompt

    def _load_local_prompt(self):
        """Load intent classifier prompt from local YAML."""
        import yaml

        _PROMPT_VAR_PATTERN = re.compile(r"{{\s*(\w+)\s*}}")

        for path in PROMPTS_DIR.glob("*.yaml"):
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
            except Exception as exc:
                logger.debug("Skipping unparseable YAML file %s: %s", path, exc)
                continue
            if not isinstance(data, dict):
                continue
            if data.get("id") != "graph.intent_classifier":
                continue
            template = data.get("template")
            if not template:
                raise RuntimeError(f"Prompt file '{path}' has no template.")
            params = data.get("params") or {}

            class _Prompt:
                def __init__(self, tmpl, cfg):
                    self._template = tmpl
                    self.config = cfg

                def compile(self, **kwargs):
                    def _sub(m):
                        val = kwargs.get(m.group(1), "")
                        if val is None:
                            return ""
                        if isinstance(val, (dict, list)):
                            return json.dumps(val, ensure_ascii=False)
                        return str(val)

                    return _PROMPT_VAR_PATTERN.sub(_sub, self._template)

            return _Prompt(template, params)

        raise RuntimeError(
            "Prompt 'graph.intent_classifier' not found in local YAML files."
        )

    @staticmethod
    def format_history(messages: List[Dict[str, Any]], max_pairs: int = 5) -> str:
        """Format recent chat messages into a rich string for the prompt.

        Keeps the most recent *max_pairs* user/assistant exchanges.
        For assistant messages, includes the Cypher query and a compact
        summary of results when available, so the LLM can produce
        better follow-up rewrites.
        """
        if not messages:
            return "(no prior conversation)"

        relevant = [
            m for m in messages if m.get("role") in ("user", "assistant")
        ]
        tail = relevant[-(max_pairs * 2):]

        lines: list[str] = []
        for msg in tail:
            role = msg.get("role", "unknown").capitalize()
            content = msg.get("content", "")

            if role == "Assistant":
                parts: list[str] = []

                cypher = msg.get("cypher")
                if cypher:
                    parts.append(f"  [Cypher executed: {cypher.strip()}]")

                route = msg.get("route_type")
                if route:
                    parts.append(f"  [Route: {route}]")

                # Truncate long assistant text
                if len(content) > 300:
                    content = content[:300] + "..."
                parts.insert(0, f"Assistant: {content}")
                lines.append("\n".join(parts))
            else:
                lines.append(f"User: {content}")

        return "\n".join(lines)

    @staticmethod
    def format_history_with_budget(
        messages: List[Dict[str, Any]],
        max_chars: int = 3000,
        recent_full: int = 4,
    ) -> str:
        """Format history with a character budget.

        The most recent *recent_full* messages are kept in full detail.
        Older messages are compressed to a one-line summary each.
        The output is truncated to *max_chars* (keeping the most recent
        content) so the prompt doesn't blow up on long conversations.
        """
        if not messages:
            return "(no prior conversation)"

        relevant = [
            m for m in messages if m.get("role") in ("user", "assistant")
        ]
        if not relevant:
            return "(no prior conversation)"

        # Split into old (compressed) and recent (full)
        if len(relevant) > recent_full:
            old = relevant[:-recent_full]
            recent = relevant[-recent_full:]
        else:
            old = []
            recent = relevant

        lines: list[str] = []

        # Older turns — one line each
        if old:
            lines.append("--- Earlier in the conversation (summarized) ---")
            for msg in old:
                role = msg.get("role", "unknown").capitalize()
                content = msg.get("content", "")
                short = content[:80].replace("\n", " ")
                if len(content) > 80:
                    short += "..."
                lines.append(f"{role}: {short}")
            lines.append("--- Recent messages (full) ---")

        # Recent turns — full detail
        for msg in recent:
            role = msg.get("role", "unknown").capitalize()
            content = msg.get("content", "")

            if role == "Assistant":
                parts: list[str] = []
                cypher = msg.get("cypher")
                if cypher:
                    parts.append(f"  [Cypher: {cypher.strip()}]")
                route = msg.get("route_type")
                if route:
                    parts.append(f"  [Route: {route}]")
                if len(content) > 300:
                    content = content[:300] + "..."
                parts.insert(0, f"Assistant: {content}")
                lines.append("\n".join(parts))
            else:
                lines.append(f"User: {content}")

        text = "\n".join(lines)

        # Truncate from the front if over budget (keep most recent context)
        if len(text) > max_chars:
            text = "...(earlier messages truncated)...\n" + text[-max_chars:]

        return text

    @staticmethod
    def format_history_for_cypher(
        messages: List[Dict[str, Any]], max_pairs: int = 3
    ) -> str:
        """Format conversation history for the text-to-cypher prompt.

        More compact than ``format_history`` — focuses on the question,
        the Cypher that was generated, and whether results were returned.
        This gives the Cypher-generating LLM enough context to resolve
        references like "the same area" without bloating the prompt.
        """
        if not messages:
            return "(no prior conversation)"

        relevant = [
            m for m in messages if m.get("role") in ("user", "assistant")
        ]
        tail = relevant[-(max_pairs * 2):]

        lines: list[str] = []
        for msg in tail:
            role = msg.get("role", "unknown")
            if role == "user":
                lines.append(f"User asked: {msg.get('content', '')}")
            elif role == "assistant":
                cypher = msg.get("cypher")
                if cypher:
                    lines.append(f"System ran Cypher: {cypher.strip()}")
                summary = msg.get("content", "")
                if summary:
                    short = summary[:200] + "..." if len(summary) > 200 else summary
                    lines.append(f"Result summary: {short}")

        return "\n".join(lines) if lines else "(no prior conversation)"

    # Patterns that strongly suggest a follow-up referencing prior conversation
    _FOLLOW_UP_PATTERNS = [
        re.compile(r"^what\s+about\s+(.+?)\??$", re.IGNORECASE),
        re.compile(r"^how\s+about\s+(.+?)\??$", re.IGNORECASE),
        re.compile(r"^and\s+(?:for|in|with)\s+(.+?)\??$", re.IGNORECASE),
        re.compile(r"^same\s+(?:but\s+)?(?:for|in|with)\s+(.+?)\??$", re.IGNORECASE),
        re.compile(r"^(?:now\s+)?(?:for|in)\s+(.+?)\??$", re.IGNORECASE),
        re.compile(r"^(?:what|how)\s+(?:if|about)\s+(.+?)\??$", re.IGNORECASE),
    ]

    _CHITCHAT_PATTERNS = re.compile(
        r"^(?:hi|hello|hey|thanks?|thank\s+you|thx|bye|goodbye|see\s+you|good\s+(?:morning|afternoon|evening|night))[\s!.?]*$",
        re.IGNORECASE,
    )

    async def classify(
        self,
        question: str,
        conversation_history: List[Dict[str, Any]],
    ) -> IntentResult:
        """Classify the intent of a user message.

        Args:
            question: The raw user message.
            conversation_history: Recent messages (list of dicts with
                ``role`` and ``content`` keys).

        Returns:
            An ``IntentResult`` with the classified intent and, for
            follow-ups, a rewritten self-contained question.
        """
        prompt_obj = self._get_prompt()

        history_text = self.format_history_with_budget(conversation_history)
        logger.debug(
            "Intent classify: history_text length=%d, question=%r",
            len(history_text), question,
        )

        rendered = prompt_obj.compile(
            domain_description=DOMAIN_DESCRIPTION,
            conversation_history=history_text,
            question=question,
        )
        logger.debug("Intent classify: rendered prompt length=%d chars", len(rendered))

        raw = self._call_llm(rendered)

        logger.debug("Intent classify: raw LLM response (%d chars): %r", len(raw), raw[:500])

        if not raw.strip():
            logger.warning(
                "Intent classify: LLM returned empty, using rule-based fallback"
            )
            result = self._fallback_classify(question, conversation_history)
        else:
            result = self._parse_response(raw, question)

        logger.info(
            "Intent classified: intent=%s confidence=%.2f is_follow_up=%s question=%r rewritten=%r",
            result.intent,
            result.confidence,
            result.is_follow_up,
            question,
            result.rewritten_question,
        )
        return result

    def _fallback_classify(
        self,
        question: str,
        conversation_history: List[Dict[str, Any]],
    ) -> IntentResult:
        """Rule-based fallback when the LLM fails to return a response."""
        q = question.strip()

        # Chitchat
        if self._CHITCHAT_PATTERNS.match(q):
            return IntentResult(
                intent="chitchat",
                confidence=0.8,
                rewritten_question=None,
                reasoning="Rule-based fallback: detected greeting/pleasantry pattern.",
                original_question=question,
            )

        # Follow-up detection — only if there's conversation history
        user_messages = [
            m for m in (conversation_history or [])
            if m.get("role") == "user"
        ]
        assistant_messages = [
            m for m in (conversation_history or [])
            if m.get("role") == "assistant"
        ]

        if user_messages and assistant_messages:
            for pattern in self._FOLLOW_UP_PATTERNS:
                match = pattern.match(q)
                if match:
                    new_subject = match.group(1).strip().rstrip("?.")
                    last_user_q = user_messages[-1].get("content", "")
                    rewritten = self._simple_rewrite(last_user_q, new_subject)
                    if rewritten:
                        logger.info(
                            "Fallback follow-up rewrite: %r -> %r",
                            question, rewritten,
                        )
                        return IntentResult(
                            intent="graph_query",
                            confidence=0.6,
                            rewritten_question=rewritten,
                            reasoning=f"Rule-based fallback: follow-up pattern matched, substituted '{new_subject}' into previous question.",
                            original_question=question,
                            is_follow_up=True,
                        )

        # Default: treat as graph_query and let the Cypher pipeline handle it
        return IntentResult(
            intent="graph_query",
            confidence=0.3,
            rewritten_question=None,
            reasoning="Rule-based fallback: no pattern matched, defaulting to graph_query.",
            original_question=question,
        )

    @staticmethod
    def _simple_rewrite(previous_question: str, new_subject: str) -> Optional[str]:
        """Attempt a simple substitution of the new subject into the previous question.

        Looks for area names, municipality names, or the last noun phrase
        in the previous question and replaces it with *new_subject*.
        """
        if not previous_question:
            return None

        # Common area/location patterns in the prior question
        # Try to replace the last quoted or capitalized proper noun
        area_pattern = re.compile(
            r"(?:in|for|about|of)\s+([A-Z][a-zA-Z\s\-]+?)(?:\s*\?|$|,|\s+(?:area|municipality|district))",
            re.IGNORECASE,
        )
        match = area_pattern.search(previous_question)
        if match:
            old_subject = match.group(1).strip()
            return previous_question.replace(old_subject, new_subject)

        # Fallback: just replace the last significant proper noun
        # (capitalized word that isn't at the start of the sentence)
        words = previous_question.split()
        for i in range(len(words) - 1, 0, -1):
            word = words[i].strip("?,!.")
            if word and word[0].isupper() and len(word) > 2:
                return previous_question.replace(word, new_subject)

        return None

    def _call_llm(self, rendered: str) -> str:
        """Call the LLM with retries for empty responses and format issues."""
        # Attempt 1: with JSON response format
        try:
            raw = create_completion(
                rendered,
                model=self._llm_model,
                temperature=0.0,
                max_tokens=600,
                response_format={"type": "json_object"},
            )
            if raw.strip():
                return raw
            logger.warning(
                "Intent classifier: LLM returned empty with response_format; "
                "retrying without response_format"
            )
        except Exception as exc:
            logger.warning(
                "Intent classifier: LLM call with response_format failed (%s); "
                "retrying without response_format",
                exc,
            )

        # Attempt 2: without response_format
        try:
            raw = create_completion(
                rendered,
                model=self._llm_model,
                temperature=0.0,
                max_tokens=600,
            )
            if raw.strip():
                return raw
            logger.warning("Intent classifier: LLM returned empty on retry")
        except Exception as exc:
            logger.warning("Intent classifier: LLM retry also failed (%s)", exc)

        return ""

    def _parse_response(self, raw: str, original_question: str) -> IntentResult:
        """Parse the LLM JSON response into an IntentResult."""
        valid_intents = {"graph_query", "visualization", "analytics", "discussion", "follow_up", "off_topic", "chitchat"}

        try:
            text = raw.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Intent classifier JSON parse failed: %s", exc)
            return IntentResult(
                intent="graph_query",
                confidence=0.0,
                rewritten_question=None,
                reasoning="Failed to parse intent classifier output; defaulting to graph_query.",
                original_question=original_question,
            )

        intent = data.get("intent", "graph_query")
        if intent not in valid_intents:
            logger.warning("Unknown intent '%s'; defaulting to graph_query", intent)
            intent = "graph_query"

        confidence = float(data.get("confidence", 0.0))

        # If confidence is too low, default to graph_query so the user at
        # least gets a Cypher attempt rather than a confusing refusal.
        if confidence < self._confidence_threshold and intent not in ("chitchat",):
            logger.info(
                "Low confidence %.2f for intent '%s'; falling back to graph_query",
                confidence,
                intent,
            )
            intent = "graph_query"

        rewritten = data.get("rewritten_question")

        # For follow-ups, resolve the final intent of the rewritten question.
        # A follow-up like "show me more" about a graph_query should still
        # route to graph_query after rewriting.
        resolved_intent = intent
        if intent == "follow_up" and rewritten:
            resolved_intent = data.get("resolved_intent", "graph_query")
            if resolved_intent not in valid_intents:
                resolved_intent = "graph_query"

        return IntentResult(
            intent=resolved_intent if intent == "follow_up" else intent,
            confidence=confidence,
            rewritten_question=rewritten,
            reasoning=data.get("reasoning", ""),
            original_question=original_question,
            is_follow_up=intent == "follow_up",
        )
