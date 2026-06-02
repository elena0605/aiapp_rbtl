"""HybridMediaHandler — combines semantic candidate generation with structural Cypher.

Answers questions like:

- "In Rotterdam Centrum, how many creators talk about vaping?"
- "Among 15-year-olds, which creators have audiences discussing gambling?"
- "In Feijenoord, how many videos are about energy drinks?"

Two stages:

1. **Stage 1 (semantic)**: ``MediaRetrievalAgent.run(question, mode='candidates')``
   picks the best ranked retriever, runs it with a wider ``top_n``, and
   returns ``candidate_keys`` (channel_ids / tiktok_usernames / video_ids).
2. **Stage 2 (structural)**: An LLM call against
   ``graph.structural_filter_cypher`` produces read-only Cypher that
   applies the user's structural filter (area / age / gender / follower
   demographics) over those candidate keys. The Cypher passes through
   ``utils.cypher_validator.validate_cypher`` with ``enforce_read_only=True``
   and is then executed with the candidate keys as parameters.

This deliberately does NOT let the LLM invent new vector searches or do
``CONTAINS`` matching on topic/content text — Stage 1 owns the semantic
match, Stage 2 owns the structural narrowing.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # type: ignore

from utils.neo4j import get_session  # type: ignore
from utils.cypher_validator import (  # type: ignore
    CypherValidationError,
    ReadOnlyViolationError,
    validate_cypher,
)

from ai.llmops.langfuse_client import create_completion, get_prompt_from_langfuse  # type: ignore
from ai.schema.schema_utils import load_cached_schema  # type: ignore
from ai.terminology.loader import load as load_terminology  # type: ignore
from ai.terminology.loader import as_text as terminology_as_text  # type: ignore

from .media_retrieval_agent import (
    MediaRetrievalAgent,
    MediaRetrievalAgentError,
    MediaRetrievalResult,
)
from .presentation import present_hybrid_result

logger = logging.getLogger("HybridMediaHandler")

PROMPTS_DIR = ROOT / "ai" / "prompts"
PROMPT_VAR_PATTERN = re.compile(r"{{\s*(\w+)\s*}}")

MAX_CORRECTION_RETRIES = 2


def _escape_cypher_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _extract_geo_from_question(question: str) -> tuple[Optional[str], Optional[str]]:
    """Return (area_name, municipality_name) using canonical terminology names."""
    data = load_terminology("v1") or {}
    geo = data.get("geography") or {}
    areas = list(geo.get("area_names") or [])
    munis = list(geo.get("municipality_names") or [])
    q_lower = question.lower()

    matched_area: Optional[str] = None
    for name in sorted(areas, key=len, reverse=True):
        if name.lower() in q_lower:
            matched_area = name
            break

    matched_muni: Optional[str] = None
    for name in sorted(munis, key=len, reverse=True):
        if name.lower() not in q_lower:
            continue
        if matched_area and name.lower() != matched_area.lower():
            if name.lower() in matched_area.lower():
                continue
        matched_muni = name
        break

    return matched_area, matched_muni


def _account_id_filter(has_yt: bool, has_tt: bool) -> str:
    parts: List[str] = []
    if has_yt:
        parts.append(
            "(acc:YouTubeChannel AND acc.channel_id IN $youtube_channel_ids)"
        )
    if has_tt:
        parts.append("(acc:TikTokUser AND acc.username IN $tiktok_usernames)")
    if not parts:
        return "false"
    return " OR ".join(parts)


def _build_template_structural_cypher(
    *,
    question: str,
    output_kind: str,
    candidate_counts: Dict[str, int],
) -> Optional[str]:
    """Deterministic fallback for common geo + creator hybrid queries."""
    area_name, municipality_name = _extract_geo_from_question(question)
    if not area_name and not municipality_name:
        return None

    has_yt = candidate_counts.get("youtube_channel_ids", 0) > 0
    has_tt = candidate_counts.get("tiktok_usernames", 0) > 0
    if not (has_yt or has_tt):
        return None

    if output_kind not in {"count_creators", "creators"}:
        return None

    if area_name:
        geo_match = (
            "MATCH (p:Person)-[:LIVES_IN_AREA]->"
            f"(:Area {{area_name: '{_escape_cypher_literal(area_name)}'}})\n"
        )
    else:
        geo_match = (
            "MATCH (p:Person)-[:LIVES_IN_MUNICIPALITY]->"
            f"(:Municipality {{municipality_name: "
            f"'{_escape_cypher_literal(municipality_name or '')}'}})\n"
        )

    account_filter = _account_id_filter(has_yt, has_tt)
    wants_count = (
        output_kind == "count_creators"
        or re.search(r"\bhow many\b", question, re.IGNORECASE) is not None
    )
    if wants_count:
        return (
            geo_match
            + "MATCH (p)-[:FOLLOWS]->(inf:Influencer)-[:HAS_ACCOUNT]->(acc)\n"
            + f"WHERE {account_filter}\n"
            + "RETURN count(DISTINCT inf) AS creator_count"
        )

    return (
        geo_match
        + "MATCH (p)-[:FOLLOWS]->(inf:Influencer)-[:HAS_ACCOUNT]->(acc)\n"
        + f"WHERE {account_filter}\n"
        + "RETURN DISTINCT inf.name AS influencer_name, "
        + "labels(acc)[0] AS platform, "
        + "coalesce(acc.channel_id, acc.username) AS account_id\n"
        + "LIMIT 20"
    )


@dataclass
class HybridMediaResult:
    """Final result envelope returned by ``HybridMediaHandler.handle``."""

    retriever_name: str  # e.g. "youtube.top_creators+structural_cypher"
    platform: str
    inputs: Dict[str, Any]
    stage1: Dict[str, Any]  # MediaRetrievalResult dict
    stage2_cypher: Optional[str]
    candidate_counts: Dict[str, int]
    results: List[Dict[str, Any]]
    summary: str
    status: str = "ok"  # "ok" | "empty" | "soft_failure"
    error: Optional[str] = None
    timings: Dict[str, float] = field(default_factory=dict)
    retrieval_trace: Dict[str, Any] = field(default_factory=dict)
    research_notes: List[str] = field(default_factory=list)


class _LocalPrompt:
    """Local YAML prompt wrapper that matches the Langfuse interface."""

    def __init__(self, template: str, params: Optional[Dict[str, Any]] = None):
        self._template = template
        self.config = params or {}

    def compile(self, **kwargs: Any) -> str:
        def _replace(match: re.Match) -> str:
            key = match.group(1)
            value = kwargs.get(key, "")
            if value is None:
                return ""
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return str(value)

        return PROMPT_VAR_PATTERN.sub(_replace, self._template)


@lru_cache(maxsize=4)
def _load_local_prompt(prompt_id: str) -> _LocalPrompt:
    for path in PROMPTS_DIR.glob("*.yaml"):
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("id") != prompt_id:
            continue
        template = data.get("template")
        if not template:
            raise RuntimeError(f"Prompt file {path} has no template.")
        return _LocalPrompt(template, data.get("params") or {})
    raise RuntimeError(f"Prompt {prompt_id!r} not found in {PROMPTS_DIR}")


class HybridMediaHandler:
    """Orchestrates the two-stage hybrid_media route."""

    def __init__(
        self,
        *,
        agent: Optional[MediaRetrievalAgent] = None,
        llm_model: Optional[str] = None,
    ) -> None:
        self._agent = agent
        self._llm_model = (
            llm_model
            or os.environ.get("MEDIA_HYBRID_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or os.environ.get("OPEN_AI_MODEL")
            or "gpt-4o-mini"
        )
        self._min_candidates = int(os.environ.get("MEDIA_HYBRID_MIN_CANDIDATES", "5"))
        self._prompt: Optional[Any] = None
        self._schema: Optional[str] = None
        self._terminology: Optional[str] = None

    def _get_agent(self) -> MediaRetrievalAgent:
        if self._agent is None:
            self._agent = MediaRetrievalAgent()
        return self._agent

    def _get_prompt(self):
        if self._prompt is not None:
            return self._prompt
        prompt_label = os.environ.get("PROMPT_LABEL")
        try:
            self._prompt = get_prompt_from_langfuse(
                "graph.structural_filter_cypher",
                langfuse_client=None,
                label=prompt_label,
            )
        except Exception as err:
            logger.warning(
                "Langfuse prompt fetch for structural_filter_cypher failed (%s); using local YAML",
                err,
            )
            self._prompt = _load_local_prompt("graph.structural_filter_cypher")
        return self._prompt

    def _get_schema(self) -> str:
        if self._schema is None:
            self._schema = load_cached_schema() or "Graph schema not available."
        return self._schema

    def _get_terminology(self) -> str:
        if self._terminology is None:
            terminology_dict = load_terminology("v1")
            self._terminology = terminology_as_text(terminology_dict)
        return self._terminology

    # ── Entry point ─────────────────────────────────────────────────────────

    async def handle(self, question: str) -> HybridMediaResult:
        """Run Stage 1 (candidates) + Stage 2 (structural Cypher)."""
        if not question or not question.strip():
            return present_hybrid_result(
                HybridMediaResult(
                    retriever_name="hybrid_media",
                    platform="all",
                    inputs={"theme": "", "top_n": 0},
                    stage1={},
                    stage2_cypher=None,
                    candidate_counts={},
                    results=[],
                    summary="Empty question.",
                    status="empty",
                    error="Empty question.",
                ),
                question=question,
            )

        timings: Dict[str, float] = {}

        # ── Stage 1 ──────────────────────────────────────────────────────────
        stage1_start = time.perf_counter()
        agent = self._get_agent()
        try:
            stage1 = await agent.run(question, mode="candidates")
        except MediaRetrievalAgentError as exc:
            timings["stage1"] = round(time.perf_counter() - stage1_start, 3)
            return self._finalize(
                HybridMediaResult(
                    retriever_name="hybrid_media",
                    platform="all",
                    inputs={"theme": "", "top_n": 0},
                    stage1={},
                    stage2_cypher=None,
                    candidate_counts={},
                    results=[],
                    summary=(
                        "Could not extract a clear theme from the question. "
                        "Try rephrasing the semantic part (e.g. 'vaping', 'gaming') "
                        "and the structural filter (e.g. 'in Rotterdam Centrum') separately."
                    ),
                    status="empty",
                    error=str(exc),
                    timings=timings,
                ),
                question,
            )
        timings["stage1"] = round(time.perf_counter() - stage1_start, 3)

        candidate_counts = self._candidate_counts(stage1.candidate_keys)
        total_candidates = sum(candidate_counts.values())

        if total_candidates < self._min_candidates:
            return self._finalize(
                HybridMediaResult(
                    retriever_name=f"{stage1.retriever_name}+structural_cypher",
                    platform=stage1.platform,
                    inputs={
                        **stage1.inputs,
                        "candidate_counts": candidate_counts,
                        "min_candidates": self._min_candidates,
                    },
                    stage1=self._stage1_to_dict(stage1),
                    stage2_cypher=None,
                    candidate_counts=candidate_counts,
                    results=[],
                    summary=(
                        f"The semantic search found only {total_candidates} candidates "
                        f"for theme '{stage1.inputs.get('theme', '?')}', "
                        f"below the minimum {self._min_candidates} needed to apply a "
                        "structural filter reliably. Try broadening the theme or "
                        "lowering MEDIA_RETRIEVER_MIN_SCORE."
                    ),
                    status="soft_failure",
                    timings=timings,
                ),
                question,
            )

        # ── Stage 2 ──────────────────────────────────────────────────────────
        chosen_cfg = agent.list_retrievers()
        # The Stage 1 result encodes the retriever output kind via inputs.signal
        # + the retriever name; we look up the canonical config for the prompt.
        sig_lookup = {c.name: c for c in chosen_cfg}
        # Strip the "all." prefix for lookup, fall back to youtube/tiktok variant.
        base_name = stage1.retriever_name
        if base_name.startswith("all."):
            base_name = "youtube." + base_name[len("all."):]
        cfg = sig_lookup.get(base_name)
        output_kind = cfg.output_kind if cfg else (stage1.inputs.get("output_kind") or "creators")

        return self._finalize(
            await self._stage2(
                stage1=stage1,
                question=question,
                output_kind=output_kind,
                candidate_counts=candidate_counts,
                timings=timings,
            ),
            question,
        )

    def _finalize(self, result: HybridMediaResult, question: str) -> HybridMediaResult:
        return present_hybrid_result(result, question=question)

    # ── Stage 2 helpers ─────────────────────────────────────────────────────

    async def _stage2(
        self,
        *,
        stage1: MediaRetrievalResult,
        question: str,
        output_kind: str,
        candidate_counts: Dict[str, int],
        timings: Dict[str, float],
    ) -> HybridMediaResult:
        import asyncio
        from functools import partial

        prompt_obj = self._get_prompt()
        schema = self._get_schema()
        terminology = self._get_terminology()

        candidate_summary = ", ".join(
            f"{count} {kind}" for kind, count in candidate_counts.items() if count
        ) or "no candidates"
        stage2_params = self._candidate_params(stage1.candidate_keys)

        # Loop with correction retries.
        loop = asyncio.get_event_loop()
        last_cypher: Optional[str] = None
        last_error: Optional[str] = None
        for attempt in range(MAX_CORRECTION_RETRIES + 1):
            rendered = prompt_obj.compile(
                schema=schema,
                terminology=terminology,
                question=question,
                theme=stage1.inputs.get("theme", ""),
                tool_name=stage1.retriever_name,
                candidate_keys_summary=candidate_summary,
                candidate_output_kind=output_kind,
            )
            if attempt > 0 and last_cypher and last_error:
                rendered += (
                    "\n\nThe previous Cypher you produced failed validation/execution.\n"
                    f"Previous Cypher:\n{last_cypher}\n"
                    f"Error: {last_error}\n"
                    "Produce a corrected Cypher statement only."
                )
                if "CALL" in last_cypher.upper() or "UNION" in last_cypher.upper():
                    rendered += (
                        "\nDo NOT use CALL { }, UNION, or subqueries. Use one MATCH chain "
                        "with OR in WHERE to combine YouTube and TikTok account filters."
                    )

            llm_start = time.perf_counter()
            try:
                cypher = await loop.run_in_executor(
                    None,
                    partial(
                        create_completion,
                        rendered.strip(),
                        model=self._llm_model,
                        temperature=0.0,
                        max_tokens=16000,
                        system_message=(
                            "You are a Cypher query generator for the hybrid_media route. "
                            "Apply the structural filter from the user question over the "
                            "candidate IDs provided. Read-only Cypher only. Never embed, "
                            "never CONTAINS-match topic/content text — the semantic step "
                            "is already done."
                        ),
                    ),
                )
            except Exception as exc:
                logger.warning("Stage 2 LLM call failed: %s", exc)
                last_error = str(exc)
                last_cypher = None
                continue
            timings[f"stage2_llm_attempt_{attempt}"] = round(
                time.perf_counter() - llm_start, 3
            )

            cypher = (cypher or "").strip()
            if cypher.startswith("```"):
                lines_ = cypher.split("\n")
                if len(lines_) >= 2:
                    cypher = "\n".join(lines_[1:-1] if lines_[-1].startswith("```") else lines_[1:])
            cypher = cypher.strip()
            if not cypher:
                # LLM signalled "no structural filter needed" — fall back.
                logger.info(
                    "Stage 2 returned empty Cypher; falling back to Stage 1 results"
                )
                return self._fallback_to_stage1(
                    stage1=stage1,
                    question=question,
                    candidate_counts=candidate_counts,
                    timings=timings,
                    note=(
                        "The structural-filter LLM produced no Cypher (likely no "
                        "structural filter detected in the question). Returning the "
                        "semantic results without further filtering."
                    ),
                )

            # Validate.
            try:
                is_valid, details = validate_cypher(
                    cypher,
                    strict=True,
                    enforce_read_only=True,
                    parameters=stage2_params,
                )
                if not is_valid:
                    raise CypherValidationError(
                        "Stage 2 Cypher validation failed", details
                    )
            except ReadOnlyViolationError as exc:
                logger.warning("Stage 2 read-only violation: %s", exc)
                last_error = f"read-only violation: {exc}"
                last_cypher = cypher
                continue
            except CypherValidationError as exc:
                logger.warning("Stage 2 validation error: %s", exc)
                last_error = str(exc)
                last_cypher = cypher
                if attempt < MAX_CORRECTION_RETRIES:
                    continue
                template_result = self._try_template_stage2(
                    stage1=stage1,
                    question=question,
                    output_kind=output_kind,
                    candidate_counts=candidate_counts,
                    timings=timings,
                )
                if template_result is not None:
                    return template_result
                return HybridMediaResult(
                    retriever_name=f"{stage1.retriever_name}+structural_cypher",
                    platform=stage1.platform,
                    inputs={**stage1.inputs, "candidate_counts": candidate_counts},
                    stage1=self._stage1_to_dict(stage1),
                    stage2_cypher=cypher,
                    candidate_counts=candidate_counts,
                    results=[],
                    summary="Structural Cypher could not be validated after retries.",
                    status="empty",
                    error=last_error,
                    timings=timings,
                )

            # Execute.
            exec_start = time.perf_counter()
            try:
                with get_session() as session:
                    rows = [dict(r) for r in session.run(cypher, **stage2_params)]
            except Exception as exc:
                logger.warning("Stage 2 execution failed: %s", exc)
                last_error = f"execution: {exc}"
                last_cypher = cypher
                if attempt < MAX_CORRECTION_RETRIES:
                    continue
                template_result = self._try_template_stage2(
                    stage1=stage1,
                    question=question,
                    output_kind=output_kind,
                    candidate_counts=candidate_counts,
                    timings=timings,
                )
                if template_result is not None:
                    return template_result
                return HybridMediaResult(
                    retriever_name=f"{stage1.retriever_name}+structural_cypher",
                    platform=stage1.platform,
                    inputs={**stage1.inputs, "candidate_counts": candidate_counts},
                    stage1=self._stage1_to_dict(stage1),
                    stage2_cypher=cypher,
                    candidate_counts=candidate_counts,
                    results=[],
                    summary="Structural Cypher failed to execute after retries.",
                    status="empty",
                    error=last_error,
                    timings=timings,
                )
            timings[f"stage2_exec_attempt_{attempt}"] = round(
                time.perf_counter() - exec_start, 3
            )

            summary = self._summarize_stage2(stage1, rows, candidate_counts)
            return HybridMediaResult(
                retriever_name=f"{stage1.retriever_name}+structural_cypher",
                platform=stage1.platform,
                inputs={
                    **stage1.inputs,
                    "candidate_counts": candidate_counts,
                    "stage1_retriever": stage1.retriever_name,
                },
                stage1=self._stage1_to_dict(stage1),
                stage2_cypher=cypher,
                candidate_counts=candidate_counts,
                results=rows,
                summary=summary,
                status="ok" if rows else "empty",
                timings=timings,
            )

        template_result = self._try_template_stage2(
            stage1=stage1,
            question=question,
            output_kind=output_kind,
            candidate_counts=candidate_counts,
            timings=timings,
        )
        if template_result is not None:
            return template_result

        return HybridMediaResult(
            retriever_name=f"{stage1.retriever_name}+structural_cypher",
            platform=stage1.platform,
            inputs={**stage1.inputs, "candidate_counts": candidate_counts},
            stage1=self._stage1_to_dict(stage1),
            stage2_cypher=last_cypher,
            candidate_counts=candidate_counts,
            results=[],
            summary="Hybrid retrieval exhausted retries without producing valid Cypher.",
            status="empty",
            error=last_error,
            timings=timings,
        )

    def _try_template_stage2(
        self,
        *,
        stage1: MediaRetrievalResult,
        question: str,
        output_kind: str,
        candidate_counts: Dict[str, int],
        timings: Dict[str, float],
    ) -> Optional[HybridMediaResult]:
        """Run a deterministic geo+creator Cypher when the LLM output fails."""
        cypher = _build_template_structural_cypher(
            question=question,
            output_kind=output_kind,
            candidate_counts=candidate_counts,
        )
        if not cypher:
            return None

        logger.info("Stage 2 using template structural Cypher fallback")
        stage2_params = self._candidate_params(stage1.candidate_keys)
        try:
            is_valid, _details = validate_cypher(
                cypher,
                strict=True,
                enforce_read_only=True,
                parameters=stage2_params,
            )
            if not is_valid:
                return None
        except (CypherValidationError, ReadOnlyViolationError) as exc:
            logger.warning("Template Stage 2 Cypher validation failed: %s", exc)
            return None

        exec_start = time.perf_counter()
        try:
            with get_session() as session:
                rows = [dict(r) for r in session.run(cypher, **stage2_params)]
        except Exception as exc:
            logger.warning("Template Stage 2 execution failed: %s", exc)
            return None
        timings["stage2_template_exec"] = round(time.perf_counter() - exec_start, 3)

        summary = self._summarize_stage2(stage1, rows, candidate_counts)
        return HybridMediaResult(
            retriever_name=f"{stage1.retriever_name}+structural_cypher",
            platform=stage1.platform,
            inputs={
                **stage1.inputs,
                "candidate_counts": candidate_counts,
                "stage1_retriever": stage1.retriever_name,
                "stage2_template": True,
            },
            stage1=self._stage1_to_dict(stage1),
            stage2_cypher=cypher,
            candidate_counts=candidate_counts,
            results=rows,
            summary=summary,
            status="ok" if rows else "empty",
            timings=timings,
        )

    def _fallback_to_stage1(
        self,
        *,
        stage1: MediaRetrievalResult,
        question: str,
        candidate_counts: Dict[str, int],
        timings: Dict[str, float],
        note: str,
    ) -> HybridMediaResult:
        return HybridMediaResult(
            retriever_name=stage1.retriever_name,
            platform=stage1.platform,
            inputs={**stage1.inputs, "candidate_counts": candidate_counts},
            stage1=self._stage1_to_dict(stage1),
            stage2_cypher=None,
            candidate_counts=candidate_counts,
            results=stage1.raw_result,
            summary=stage1.summary + " " + note,
            status="ok" if stage1.raw_result else "empty",
            timings=timings,
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _candidate_counts(candidate_keys: Dict[str, List[Any]]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for key, values in (candidate_keys or {}).items():
            counts[key] = len(values) if values else 0
        return counts

    @staticmethod
    def _candidate_params(candidate_keys: Dict[str, List[Any]]) -> Dict[str, Any]:
        return {
            "youtube_channel_ids": candidate_keys.get("youtube_channel_ids") or [],
            "tiktok_usernames": candidate_keys.get("tiktok_usernames") or [],
            "video_ids": candidate_keys.get("video_ids") or [],
        }

    def _stage1_to_dict(self, stage1: MediaRetrievalResult) -> Dict[str, Any]:
        return {
            "retriever_name": stage1.retriever_name,
            "platform": stage1.platform,
            "inputs": stage1.inputs,
            "results": stage1.raw_result or [],
            "results_preview": stage1.raw_result or [],
            "candidate_keys": stage1.candidate_keys,
            "status": stage1.status,
            "summary": stage1.summary,
            "deduped_by_influencer": stage1.deduped_by_influencer,
            "retrieval_trace": stage1.retrieval_trace,
            "research_notes": stage1.research_notes,
        }

    @staticmethod
    def _summarize_stage2(
        stage1: MediaRetrievalResult,
        rows: List[Dict[str, Any]],
        candidate_counts: Dict[str, int],
    ) -> str:
        theme = stage1.inputs.get("theme", "?")
        if not rows:
            return (
                f"No items matched both the semantic theme '{theme}' "
                f"and the structural filter (candidates: "
                f"{', '.join(f'{c} {k}' for k, c in candidate_counts.items())})."
            )
        # If a single-row count, surface it directly.
        if len(rows) == 1 and any(
            isinstance(rows[0].get(k), int)
            for k in ("creator_count", "video_count", "count")
        ):
            count_value = next(
                (rows[0][k] for k in ("creator_count", "video_count", "count") if k in rows[0]),
                None,
            )
            return (
                f"{count_value} items matched the semantic theme '{theme}' "
                f"and the structural filter from your question."
            )
        return (
            f"{len(rows)} items matched theme '{theme}' and the structural filter "
            f"(seed: {', '.join(f'{c} {k}' for k, c in candidate_counts.items())})."
        )
