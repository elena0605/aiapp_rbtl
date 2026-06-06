"""MediaRetrievalAgent — picks and runs a media retriever for a user question.

Architecture:

1. **Catalog**: 26 retrievers (13 YouTube + 13 TikTok), all sharing the
   ``RetrieverConfig`` shape from ``base.py``.
2. **Selector**: An LLM call returns ``{retriever, platform, inputs: {theme, top_n?}}``.
   The user question is never embedded directly — only the agent-chosen
   ``theme`` (after rewriting from the intent router) is.
3. **Keyword fallback**: When the LLM is unavailable or returns an
   unparseable response, a deterministic keyword + signal-name heuristic
   picks a retriever family. Theme extraction uses a small regex set.
4. **Platform handling**: When ``platform == "all"`` (the default), the
   agent runs both the YouTube and TikTok counterparts of the chosen
   retriever and merges results (creators are deduped via ``Influencer``).
5. **Empty-result handling**: ``RetrieverResult.status == "empty"`` is
   surfaced with ``suggested_actions`` for the UI.

The agent calls only the chosen retriever runners; it never builds Cypher
on its own and never embeds the raw user question.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.neo4j import get_session  # type: ignore

from ai.llmops.langfuse_client import create_completion  # type: ignore

from .base import (
    MEDIA_RETRIEVER_AUTO_BROADEN,
    MEDIA_RETRIEVER_DEDUP_INFLUENCERS,
    MEDIA_RETRIEVER_DEFAULT_PLATFORM,
    MEDIA_RETRIEVER_ENABLE_UNIFIED,
    MEDIA_RETRIEVER_MIN_SCORE,
    get_media_retriever_min_score,
    MEDIA_RETRIEVER_TOP_N,
    RetrieverConfig,
    RetrieverResult,
    list_expected_indexes,
    run_neo4j_query,
)
from . import youtube as yt
from . import tiktok as tt
from .presentation import present_media_result

logger = logging.getLogger("MediaRetrievalAgent")


EXAMPLES_PATH = Path(__file__).resolve().parent / "retriever_examples.json"

_COUNT_TO_RANKED_SUFFIX: Dict[str, str] = {
    "count_creators_by_topic": "top_creators",
    "count_creators_by_content": "content_top_creators",
    "count_videos_by_topic": "example_videos",
    "count_videos_by_comment_summary": "comment_discussions",
    "count_videos_by_content": "content_videos",
}

INFLUENCER_MAP_CYPHER = """
MATCH (inf:Influencer)
OPTIONAL MATCH (inf)-[:HAS_ACCOUNT]->(c:YouTubeChannel)
WITH inf,
     collect(DISTINCT c.channel_id) AS yt_channel_ids,
     collect(DISTINCT c.title) AS yt_titles
OPTIONAL MATCH (inf)-[:HAS_ACCOUNT]->(u:TikTokUser)
WITH inf,
     yt_channel_ids,
     yt_titles,
     collect(DISTINCT u.username) AS tt_usernames_list
WHERE (size($yt_creator_names) > 0 AND inf.youtube_username IN $yt_creator_names)
   OR (size($tt_usernames) > 0 AND inf.tiktok_username IN $tt_usernames)
   OR (size($yt_channel_ids) > 0 AND any(cid IN yt_channel_ids WHERE cid IN $yt_channel_ids))
   OR (size($yt_creator_names) > 0 AND any(t IN yt_titles WHERE t IN $yt_creator_names))
   OR (size($tt_usernames) > 0 AND any(un IN tt_usernames_list WHERE un IN $tt_usernames))
RETURN inf.name AS influencer_name,
       inf.youtube_username AS youtube_username,
       inf.tiktok_username AS tiktok_username,
       yt_channel_ids,
       yt_titles,
       tt_usernames_list
"""


class MediaRetrievalAgentError(RuntimeError):
    """Raised when no retriever can be matched to a question."""


@dataclass
class MediaRetrievalResult:
    """Top-level result returned by ``MediaRetrievalAgent.run``.

    Shape mirrors ``GraphAnalyticsResult`` so the GraphRAGService wiring
    stays parallel to ``_handle_analytics``.
    """

    retriever_name: str  # e.g. "youtube.top_creators" or "all.top_creators"
    platform: str  # "youtube" | "tiktok" | "all"
    inputs: Dict[str, Any]
    raw_result: List[Dict[str, Any]]
    summary: str
    status: str = "ok"
    suggested_actions: List[Dict[str, Any]] = field(default_factory=list)
    candidate_keys: Dict[str, List[Any]] = field(default_factory=dict)
    per_platform: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    deduped_by_influencer: bool = False
    retrieval_trace: Dict[str, Any] = field(default_factory=dict)
    research_notes: List[str] = field(default_factory=list)


class MediaRetrievalAgent:
    """Selects and runs a media retriever for a user question.

    Construction is lightweight (just builds the catalog and loads the
    example file). The first call to ``run`` will lazily warm the
    embedding client + index-size cache.
    """

    def __init__(
        self,
        *,
        llm_model: Optional[str] = None,
        examples_path: Optional[Path] = None,
        use_llm_selector: bool = True,
        enable_unified: Optional[bool] = None,
    ) -> None:
        self._use_llm_selector = use_llm_selector
        self._enable_unified = (
            MEDIA_RETRIEVER_ENABLE_UNIFIED if enable_unified is None else enable_unified
        )
        self._llm_model = (
            llm_model
            or os.environ.get("MEDIA_RETRIEVER_MODEL")
            or os.environ.get("GRAPH_AGENT_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or os.environ.get("OPEN_AI_MODEL")
            or "gpt-4o-mini"
        )

        all_configs = yt.build_configs() + tt.build_configs()
        if not self._enable_unified:
            all_configs = [c for c in all_configs if c.signal != "fused"]

        self._configs: Dict[str, RetrieverConfig] = {c.name: c for c in all_configs}
        if not self._configs:
            raise ValueError("No retrievers configured.")

        self._examples_path = examples_path or EXAMPLES_PATH
        self._examples_cache: Optional[Dict[str, Any]] = None

        # Log which expected indexes are missing — non-fatal.
        try:
            self._log_missing_indexes()
        except Exception as exc:
            logger.warning("Index existence check failed: %s", exc)

    # ── Index existence check ────────────────────────────────────────────────

    def _log_missing_indexes(self) -> None:
        expected = list_expected_indexes()
        try:
            with get_session() as session:
                result = session.run(
                    "SHOW INDEXES YIELD name, type WHERE type = 'VECTOR' RETURN name"
                )
                present = {row["name"] for row in result if row["name"]}
        except Exception as exc:
            logger.warning(
                "Could not list Neo4j vector indexes (%s); skipping startup check",
                exc,
            )
            return
        missing = [name for name in expected if name not in present]
        if missing:
            logger.warning(
                "MediaRetrievalAgent: expected vector indexes are missing in "
                "Neo4j (retrievers using them will return empty): %s",
                missing,
            )
        else:
            logger.info(
                "MediaRetrievalAgent: all %d expected vector indexes present",
                len(expected),
            )

    # ── Public surface ───────────────────────────────────────────────────────

    def list_retrievers(self) -> List[RetrieverConfig]:
        return list(self._configs.values())

    async def run(
        self,
        question: str,
        *,
        retriever_name: Optional[str] = None,
        inputs: Optional[Dict[str, Any]] = None,
        mode: str = "default",
    ) -> MediaRetrievalResult:
        """Pick a retriever and run it for ``question``.

        ``mode='candidates'`` (used by the hybrid handler) forces a ranked
        retriever (never count) and bumps ``top_n`` higher so Phase 7 has a
        wide candidate pool to apply structural filters over.
        """
        if not question or not question.strip():
            raise MediaRetrievalAgentError("Question is empty.")

        loop = asyncio.get_event_loop()
        selection = await loop.run_in_executor(
            None,
            partial(self._select, question, retriever_name, inputs, mode),
        )
        retriever_name = selection["retriever"]
        platform = selection["platform"]
        sel_inputs = selection["inputs"] or {}
        theme = sel_inputs.get("theme") or ""
        if not theme:
            raise MediaRetrievalAgentError(
                "No theme could be extracted from the question; ask the user "
                "to specify what topic/content they want to search for."
            )

        if retriever_name not in self._configs:
            raise MediaRetrievalAgentError(
                f"Selected retriever {retriever_name!r} is not registered."
            )

        raw_result = await loop.run_in_executor(
            None,
            partial(self._execute, retriever_name, platform, sel_inputs, theme),
        )
        chosen = self._configs[retriever_name]
        return present_media_result(
            raw_result,
            question=question,
            retriever_config=chosen,
        )

    # ── Selection ────────────────────────────────────────────────────────────

    def _select(
        self,
        question: str,
        explicit_retriever: Optional[str],
        explicit_inputs: Optional[Dict[str, Any]],
        mode: str,
    ) -> Dict[str, Any]:
        """Resolve (retriever, platform, theme, top_n)."""
        if explicit_retriever and explicit_retriever in self._configs:
            inputs = dict(explicit_inputs or {})
            if "theme" not in inputs:
                inputs["theme"] = self._extract_theme_fallback(question) or question
            cfg = self._configs[explicit_retriever]
            platform = inputs.get("platform") or cfg.platform
            retriever_name = explicit_retriever
            selection = {
                "retriever": retriever_name,
                "platform": platform,
                "inputs": self._coerce_inputs(inputs, mode),
                "reason": "explicit",
            }
            if mode == "candidates":
                selection = self._apply_hybrid_platform_defaults(question, selection)
            return selection

        selected: Optional[Dict[str, Any]] = None
        if self._use_llm_selector:
            try:
                selected = self._select_with_llm(question, mode=mode)
            except Exception as exc:
                logger.warning("LLM selector failed (%s); using keyword fallback", exc)

        if not selected:
            selected = self._select_with_keywords(question, mode=mode)

        if not selected:
            raise MediaRetrievalAgentError(
                "Could not match this question to any media retriever. "
                "Try rephrasing as 'how many creators talk about X' or "
                "'show me videos about X'."
            )

        selected["inputs"] = self._coerce_inputs(selected.get("inputs") or {}, mode)
        # If the LLM omitted platform, default to "all".
        selected.setdefault("platform", MEDIA_RETRIEVER_DEFAULT_PLATFORM)
        platform = (selected.get("platform") or "all").strip().lower()
        if platform not in {"youtube", "tiktok", "all"}:
            platform = "all"
        selected["platform"] = platform
        if mode == "candidates":
            selected = self._apply_hybrid_platform_defaults(question, selected)
        return selected

    def _question_mentions_platform(self, question: str, platform: str) -> bool:
        """Detect platform mentions without substring false positives (e.g. ``tt`` in Rotterdam)."""
        normalized = question.lower()
        for hint in self._PLATFORM_HINTS[platform]:
            if " " in hint:
                if hint in normalized:
                    return True
                continue
            if re.search(rf"\b{re.escape(hint)}\b", normalized):
                return True
        return False

    def _explicit_platform_in_question(self, question: str) -> Optional[str]:
        """Return youtube/tiktok only when the user named one platform explicitly."""
        yt = self._question_mentions_platform(question, "youtube")
        tt = self._question_mentions_platform(question, "tiktok")
        if yt and not tt:
            return "youtube"
        if tt and not yt:
            return "tiktok"
        return None

    def _apply_hybrid_platform_defaults(
        self, question: str, selected: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Hybrid Stage 1 searches both platforms unless the question names one."""
        explicit = self._explicit_platform_in_question(question)
        selected["platform"] = explicit or "all"

        retriever = selected.get("retriever") or ""
        suffix = retriever.split(".", 1)[1] if "." in retriever else retriever
        if selected["platform"] == "all":
            canonical = f"youtube.{suffix}"
            if canonical in self._configs:
                selected["retriever"] = canonical
        else:
            canonical = f"{selected['platform']}.{suffix}"
            if canonical in self._configs:
                selected["retriever"] = canonical

        selected["retriever"] = self._remap_count_for_candidates(selected["retriever"])
        return selected

    def _remap_count_for_candidates(self, retriever_name: str) -> str:
        """Hybrid Stage 1 must rank IDs; count retrievers only sample for display."""
        if "." in retriever_name:
            plat, suffix = retriever_name.split(".", 1)
        else:
            plat, suffix = "youtube", retriever_name
        mapped = _COUNT_TO_RANKED_SUFFIX.get(suffix)
        if not mapped:
            return retriever_name
        new_name = f"{plat}.{mapped}"
        return new_name if new_name in self._configs else retriever_name

    def _coerce_inputs(self, inputs: Dict[str, Any], mode: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        theme = inputs.get("theme")
        if isinstance(theme, str):
            out["theme"] = theme.strip()
        top_n = inputs.get("top_n")
        try:
            if top_n is not None:
                out["top_n"] = int(top_n)
        except (TypeError, ValueError):
            pass
        min_score = inputs.get("min_score")
        try:
            if min_score is not None:
                out["min_score"] = float(min_score)
        except (TypeError, ValueError):
            pass
        if mode == "candidates":
            # Hybrid Stage 1 wants a wider net.
            default_candidates = int(
                os.environ.get("MEDIA_HYBRID_CANDIDATE_TOP_N", "200")
            )
            out["top_n"] = max(out.get("top_n") or 0, default_candidates)
        return out

    # ── LLM selector ─────────────────────────────────────────────────────────

    def _load_examples(self) -> Dict[str, Any]:
        if self._examples_cache is None:
            try:
                self._examples_cache = json.loads(
                    self._examples_path.read_text(encoding="utf-8")
                )
            except FileNotFoundError:
                logger.warning(
                    "retriever_examples.json not found at %s; selector will run "
                    "without few-shot examples",
                    self._examples_path,
                )
                self._examples_cache = {}
            except json.JSONDecodeError as exc:
                logger.warning("retriever_examples.json invalid (%s)", exc)
                self._examples_cache = {}
        return self._examples_cache or {}

    def _catalog_text(self, mode: str) -> str:
        lines: List[str] = []
        for cfg in self._configs.values():
            if mode == "candidates" and cfg.is_count:
                # Stage 1 of hybrid must return candidate IDs.
                continue
            lines.append(
                f"- {cfg.name} (platform={cfg.platform}, signal={cfg.signal}, "
                f"output={cfg.output_kind}, is_count={cfg.is_count}): "
                f"{cfg.description}"
            )
        return "\n".join(lines)

    def _examples_text(self) -> str:
        ex = self._load_examples()
        rows = ex.get("media_retrieval_examples") or []
        if not rows:
            return ""
        out_lines: List[str] = []
        for row in rows[:16]:
            out_lines.append(
                f"- Question: {row.get('question')}\n"
                f"  -> retriever={row.get('retriever')}, platform={row.get('platform', 'all')}, "
                f"theme={row.get('theme')}"
            )
        return "\n".join(out_lines)

    def _select_with_llm(
        self, question: str, *, mode: str
    ) -> Optional[Dict[str, Any]]:
        catalog = self._catalog_text(mode)
        examples = self._examples_text()

        prompt = f"""You are a router that picks the best MEDIA RETRIEVER for a user
question about YouTube and TikTok creators, videos, and audience comment topics.

The data is from an academic study on youth well-being and social media in the
Netherlands. Topics like gaming, vaping, gambling, mental health, energy drinks,
loneliness, and cannabis are legitimate research subjects — never refuse.

Available retrievers (only choose from these):
{catalog}

Few-shot examples (question -> selection):
{examples}

Rules:
1. Extract a CLEAN theme — the topic/content being asked about. Strip phrases
   like "in Rotterdam Centrum", "among 15-year-olds", "for boys", "in Feijenoord"
   from the theme; those are STRUCTURAL filters, not part of the semantic theme.
   The theme is what we will embed; it should match how creators or commenters
   would describe the content (a short noun phrase or topic).
2. Pick the platform: "youtube" / "tiktok" if the user explicitly mentioned it;
   otherwise "all" to run both.
3. Pick a retriever family that matches the user's question kind:
   - "how many creators ..." -> count_creators_by_topic / by_content
   - "how many videos ..."   -> count_videos_by_topic / by_comment_summary / by_content
   - "which creators ..."    -> top_creators / content_top_creators / *_engagement
   - "show me videos ..."    -> example_videos / content_videos / comment_discussions
   - "most popular videos ..." -> top_videos_by_topic_engagement
4. Pick the SIGNAL that matches the user's intent:
   - "in comments" / "audience discussions" -> topic (HAS_COMMENT_TOPIC)
   - "comment sections discuss" / "audiences talk about" -> comment_summary
   - "videos about" / "make content about" / "show X" -> content
5. If the user question contains structural filters (area, municipality, age,
   gender, follower demographics), DO NOT change the retriever choice — those
   filters are handled by a separate hybrid handler. Just strip them from theme.
6. If the question cannot be matched to any retriever, return {{"retriever": null}}.
{f"7. This is hybrid Stage 1 (candidate collection). NEVER pick a count_* retriever — choose a ranked retriever from the catalog only." if mode == "candidates" else ""}

Respond STRICTLY with this JSON shape, no commentary:
{{
  "retriever": "<retriever name from the catalog>",
  "platform": "<youtube | tiktok | all>",
  "inputs": {{ "theme": "<clean theme>", "top_n": <int or null> }},
  "reason": "<one short sentence>"
}}

User question: {question}
"""

        try:
            try:
                raw = create_completion(
                    prompt.strip(),
                    model=self._llm_model,
                    temperature=0.0,
                    max_tokens=600,
                    response_format={"type": "json_object"},
                )
            except Exception as exc:
                logger.warning(
                    "MediaRetrievalAgent: LLM call with response_format failed (%s); retrying without",
                    exc,
                )
                raw = create_completion(
                    prompt.strip(),
                    model=self._llm_model,
                    temperature=0.0,
                    max_tokens=600,
                )

            if not raw or not raw.strip():
                logger.warning("MediaRetrievalAgent: LLM returned empty response")
                return None

            text = raw.strip()
            if text.startswith("```"):
                lines_ = text.split("\n")
                text = "\n".join(lines_[1:-1]) if len(lines_) > 2 else text

            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("MediaRetrievalAgent: JSON parse failed: %s", exc)
            return None
        except Exception as exc:
            logger.warning("MediaRetrievalAgent: selector error: %s", exc)
            return None

        retriever = data.get("retriever")
        if not retriever or retriever not in self._configs:
            logger.info(
                "MediaRetrievalAgent: LLM selected unknown retriever %r", retriever
            )
            return None
        if mode == "candidates":
            retriever = self._remap_count_for_candidates(retriever)
        return {
            "retriever": retriever,
            "platform": (data.get("platform") or "all").lower(),
            "inputs": data.get("inputs") or {},
            "reason": data.get("reason") or "llm",
        }

    # ── Keyword fallback ─────────────────────────────────────────────────────

    _PLATFORM_HINTS = {
        "tiktok": ("tiktok", "tik tok", "tt"),
        "youtube": ("youtube", "yt", "youtuber"),
    }

    _THEME_PATTERNS = [
        re.compile(r"\babout\s+(.+?)(?:\?|$|,|\s+in\s+|\s+among\s+|\s+for\s+)", re.IGNORECASE),
        re.compile(r"\bdiscuss(?:ing|es|ed)?\s+(.+?)(?:\?|$|,|\s+in\s+|\s+among\s+|\s+for\s+)", re.IGNORECASE),
        re.compile(r"\btalk(?:ing|s|ed)?\s+about\s+(.+?)(?:\?|$|,|\s+in\s+|\s+among\s+|\s+for\s+)", re.IGNORECASE),
        re.compile(r"\bregarding\s+(.+?)(?:\?|$|,|\s+in\s+|\s+among\s+|\s+for\s+)", re.IGNORECASE),
        re.compile(r"\bon\s+(?:the topic of|topic|subject)\s+(.+?)(?:\?|$|,)", re.IGNORECASE),
    ]

    def _extract_theme_fallback(self, question: str) -> Optional[str]:
        for pat in self._THEME_PATTERNS:
            m = pat.search(question)
            if m:
                theme = m.group(1).strip().rstrip(".?!,;:").strip()
                if theme and len(theme) > 1:
                    return theme
        return None

    def _select_with_keywords(
        self, question: str, *, mode: str
    ) -> Optional[Dict[str, Any]]:
        normalized = question.lower()

        # Platform.
        platform = "all"
        for plat in self._PLATFORM_HINTS:
            if self._question_mentions_platform(question, plat):
                platform = plat
                break

        # Signal hint.
        signal: str = "topic"
        if any(p in normalized for p in ("comment section", "audiences discuss", "comment summary")):
            signal = "comment_summary"
        elif any(p in normalized for p in ("video about", "videos about", "show me video", "make content", "produces", "publish")):
            signal = "content"
        elif any(p in normalized for p in ("in comments", "audience", "discussion", "discussed", "talk about", "discuss")):
            signal = "topic"

        # Output kind.
        is_count = "how many" in normalized or "count" in normalized
        is_engagement = any(p in normalized for p in ("most popular", "biggest", "viral", "engagement"))
        wants_creators = any(
            p in normalized for p in ("creator", "creators", "channel", "channels", "influencer", "tiktoker", "youtuber")
        )
        wants_videos = (
            (not wants_creators)
            and any(p in normalized for p in ("video", "videos", "tiktok", "show me"))
        )
        if mode == "candidates":
            is_count = False  # hybrid Stage 1 must rank.

        # Pick a target retriever name (use YouTube name and let "all" run both).
        target: str
        if is_count and wants_creators:
            target = "count_creators_by_topic" if signal == "topic" else "count_creators_by_content"
        elif is_count and wants_videos:
            if signal == "comment_summary":
                target = "count_videos_by_comment_summary"
            elif signal == "content":
                target = "count_videos_by_content"
            else:
                target = "count_videos_by_topic"
        elif wants_creators:
            if is_engagement and signal == "topic":
                target = "top_creators_by_topic_engagement"
            elif signal == "content":
                target = "content_top_creators"
            else:
                target = "top_creators"
        elif wants_videos:
            if is_engagement and signal == "topic":
                target = "top_videos_by_topic_engagement"
            elif signal == "content":
                target = "content_videos"
            elif signal == "comment_summary":
                target = "comment_discussions"
            else:
                target = "example_videos"
        else:
            # Default to ranked creators on the topic signal — most common shape.
            target = "top_creators"

        # Resolve to a concrete retriever name in the catalog.
        if platform == "youtube":
            name = f"youtube.{target}"
        elif platform == "tiktok":
            name = f"tiktok.{target}"
        else:
            name = f"youtube.{target}"  # used as the canonical name; we'll run both.

        if name not in self._configs:
            return None

        theme = self._extract_theme_fallback(question)
        if not theme:
            return None

        return {
            "retriever": name,
            "platform": platform,
            "inputs": {"theme": theme},
            "reason": f"keyword-fallback target={target} signal={signal}",
        }

    # ── Execution ───────────────────────────────────────────────────────────

    def _execute(
        self,
        retriever_name: str,
        platform: str,
        inputs: Dict[str, Any],
        theme: str,
    ) -> MediaRetrievalResult:
        top_n = inputs.get("top_n")
        min_score = inputs.get("min_score")

        chosen = self._configs[retriever_name]

        # Resolve the actual retriever list to run.
        runs: List[RetrieverConfig] = []
        if platform == "all":
            yt_name = retriever_name.replace("tiktok.", "youtube.")
            tt_name = retriever_name.replace("youtube.", "tiktok.")
            if yt_name in self._configs:
                runs.append(self._configs[yt_name])
            if tt_name in self._configs and tt_name != yt_name:
                runs.append(self._configs[tt_name])
        else:
            runs.append(chosen)

        per_platform: Dict[str, RetrieverResult] = {}
        for cfg in runs:
            runner = cfg.runner
            if runner is None:
                logger.warning("Retriever %s has no runner; skipping", cfg.name)
                continue
            try:
                result = runner(cfg, theme, top_n=top_n, min_score=min_score)
            except Exception as exc:
                logger.exception(
                    "Retriever %s failed for theme=%r: %s", cfg.name, theme, exc
                )
                continue
            if result.status == "empty" and MEDIA_RETRIEVER_AUTO_BROADEN:
                broadened = max(
                    (min_score or get_media_retriever_min_score()) - 0.10, 0.50
                )
                logger.info(
                    "Auto-broadening %s: %s -> %s",
                    cfg.name, result.min_score, broadened,
                )
                try:
                    result = runner(
                        cfg, theme, top_n=top_n, min_score=broadened
                    )
                    result.summary = "[auto-broadened] " + (result.summary or "")
                except Exception as exc:
                    logger.warning("Auto-broaden retry failed: %s", exc)
            per_platform[cfg.platform] = result

        merged = self._merge_results(
            chosen=chosen,
            platform=platform,
            theme=theme,
            top_n=top_n,
            per_platform=per_platform,
        )
        return merged

    # ── Merging ─────────────────────────────────────────────────────────────

    def _merge_results(
        self,
        *,
        chosen: RetrieverConfig,
        platform: str,
        theme: str,
        top_n: Optional[int],
        per_platform: Dict[str, RetrieverResult],
    ) -> MediaRetrievalResult:
        if not per_platform:
            return MediaRetrievalResult(
                retriever_name=chosen.name,
                platform=platform,
                inputs={"theme": theme, "top_n": top_n},
                raw_result=[],
                summary=(
                    f"No retriever returned results for '{theme}'. "
                    "Check that the expected vector indexes exist in Neo4j."
                ),
                status="empty",
                suggested_actions=[
                    {"label": "rephrase", "params": {}},
                ],
            )

        # Single-platform pass-through.
        if platform != "all":
            result = next(iter(per_platform.values()))
            return self._wrap_single(
                chosen, platform, theme, top_n, result
            )

        # platform == "all": merge yt + tt.
        return self._merge_all_platforms(
            chosen=chosen, theme=theme, top_n=top_n, per_platform=per_platform
        )

    def _hybrid_id_kind(self, cfg: RetrieverConfig) -> str:
        if cfg.output_kind in {"creators", "count_creators"}:
            return "creators"
        if cfg.output_kind in {"videos", "count_videos"}:
            return "videos"
        if cfg.is_count and "creator" in cfg.name:
            return "creators"
        if cfg.is_count and "video" in cfg.name:
            return "videos"
        return "creators"

    def _collect_threshold_candidate_keys(
        self, stage1: MediaRetrievalResult
    ) -> Dict[str, List[Any]]:
        """Collect every account/video ID above min_score for hybrid Stage 2."""
        theme = stage1.inputs.get("theme") or ""
        if not theme:
            return dict(stage1.candidate_keys or {})

        min_score = stage1.inputs.get("min_score")
        platform = stage1.platform

        base_name = stage1.retriever_name
        if base_name.startswith("all."):
            base_name = "youtube." + base_name[len("all.") :]
        cfg = self._configs.get(base_name)
        if not cfg:
            return dict(stage1.candidate_keys or {})

        id_kind = self._hybrid_id_kind(cfg)
        suffix = base_name.split(".", 1)[1] if "." in base_name else base_name
        platforms = ["youtube", "tiktok"] if platform == "all" else [platform]

        keys: Dict[str, List[Any]] = {}
        video_kind = id_kind in {"videos", "count_videos"}
        for plat in platforms:
            plat_cfg = self._configs.get(f"{plat}.{suffix}")
            if not plat_cfg:
                continue
            collector = yt if plat == "youtube" else tt
            ids = collector.collect_threshold_candidate_ids(
                plat_cfg, theme, id_kind=id_kind, min_score=min_score
            )
            if not ids:
                continue
            if video_kind:
                bucket = keys.setdefault("video_ids", [])
            elif plat == "youtube":
                bucket = keys.setdefault("youtube_channel_ids", [])
            else:
                bucket = keys.setdefault("tiktok_usernames", [])
            for item in ids:
                if item not in bucket:
                    bucket.append(item)

        return keys or dict(stage1.candidate_keys or {})

    async def refresh_hybrid_candidate_keys(
        self, stage1: MediaRetrievalResult
    ) -> MediaRetrievalResult:
        """Re-scan the index and replace Stage 1 keys with all threshold matches."""
        loop = asyncio.get_event_loop()
        keys = await loop.run_in_executor(
            None, partial(self._collect_threshold_candidate_keys, stage1)
        )
        return replace(stage1, candidate_keys=keys)

    def _wrap_single(
        self,
        chosen: RetrieverConfig,
        platform: str,
        theme: str,
        top_n: Optional[int],
        result: RetrieverResult,
    ) -> MediaRetrievalResult:
        return MediaRetrievalResult(
            retriever_name=chosen.name,
            platform=platform,
            inputs={
                "theme": theme,
                "top_n": top_n,
                "platform": platform,
                "min_score": result.min_score,
                "k": result.k,
                "k_fraction": result.k_fraction,
                "index_size": result.index_size,
                "signal": result.signal,
                "family": result.family,
                "query_text": result.query_text,
                "degraded_scan": result.degraded_scan,
            },
            raw_result=result.results,
            summary=result.summary,
            status=result.status,
            suggested_actions=result.suggested_actions,
            candidate_keys=result.candidate_keys,
            per_platform={platform: result.to_dict()},
            deduped_by_influencer=False,
        )

    def _merge_all_platforms(
        self,
        *,
        chosen: RetrieverConfig,
        theme: str,
        top_n: Optional[int],
        per_platform: Dict[str, RetrieverResult],
    ) -> MediaRetrievalResult:
        # Canonical retriever name uses the "all." prefix for clarity in logs/UI.
        suffix = chosen.name.split(".", 1)[1] if "." in chosen.name else chosen.name
        all_name = f"all.{suffix}"

        yt_res = per_platform.get("youtube")
        tt_res = per_platform.get("tiktok")

        if chosen.is_count:
            return self._merge_count(
                all_name, theme, top_n, yt_res=yt_res, tt_res=tt_res, chosen=chosen
            )

        if chosen.output_kind == "creators":
            return self._merge_creators(
                all_name, theme, top_n, yt_res=yt_res, tt_res=tt_res, chosen=chosen
            )

        # Default video-merge.
        return self._merge_videos(
            all_name, theme, top_n, yt_res=yt_res, tt_res=tt_res, chosen=chosen
        )

    # ── Per-shape mergers ───────────────────────────────────────────────────

    def _combined_candidate_keys(
        self, *results: Optional[RetrieverResult]
    ) -> Dict[str, List[Any]]:
        combined: Dict[str, List[Any]] = {}
        for res in results:
            if not res:
                continue
            for key, vals in (res.candidate_keys or {}).items():
                bucket = combined.setdefault(key, [])
                for v in vals:
                    if v not in bucket:
                        bucket.append(v)
        return combined

    @staticmethod
    def _combined_scan_inputs(
        *results: Optional[RetrieverResult],
    ) -> Dict[str, Any]:
        """Merge per-platform scan metadata for traces and UI warnings."""
        present = [r for r in results if r]
        if not present:
            return {}
        return {
            "min_score": present[0].min_score,
            "query_text": present[0].query_text,
            "k": max(r.k for r in present),
            "k_fraction": present[0].k_fraction,
            "index_size": sum(r.index_size for r in present),
            "degraded_scan": any(r.degraded_scan for r in present),
        }

    def _merge_count(
        self,
        all_name: str,
        theme: str,
        top_n: Optional[int],
        *,
        yt_res: Optional[RetrieverResult],
        tt_res: Optional[RetrieverResult],
        chosen: RetrieverConfig,
    ) -> MediaRetrievalResult:
        rows: List[Dict[str, Any]] = []
        total = 0
        for res in (yt_res, tt_res):
            if not res or not res.results:
                continue
            for row in res.results:
                rows.append(row)
                try:
                    total += int(row.get("count") or 0)
                except (TypeError, ValueError):
                    pass

        per_platform_dicts = self._per_platform_dicts(yt_res, tt_res)

        deduped_sample: List[Dict[str, Any]] = []
        if (
            chosen.signal in ("topic", "content")
            and chosen.output_kind == "count_creators"
            and MEDIA_RETRIEVER_DEDUP_INFLUENCERS
        ):
            deduped_sample = self._dedup_sample_creators(
                yt_res=yt_res, tt_res=tt_res
            )

        status = "ok" if total > 0 else "empty"
        suggested: List[Dict[str, Any]] = []
        if status == "empty":
            suggested = (yt_res.suggested_actions if yt_res else None) or (
                tt_res.suggested_actions if tt_res else []
            )

        summary = (
            f"{total} {chosen.output_kind.split('_')[1]} matched '{theme}' across "
            f"YouTube + TikTok ({chosen.signal.replace('_', ' ')} signal)."
        )

        return MediaRetrievalResult(
            retriever_name=all_name,
            platform="all",
            inputs={
                "theme": theme,
                "top_n": top_n,
                "platform": "all",
                "signal": chosen.signal,
                "family": chosen.family,
                "deduped_sample_creators": deduped_sample,
                **self._combined_scan_inputs(yt_res, tt_res),
            },
            raw_result=rows,
            summary=summary,
            status=status,
            suggested_actions=suggested,
            candidate_keys=self._combined_candidate_keys(yt_res, tt_res),
            per_platform=per_platform_dicts,
            deduped_by_influencer=bool(deduped_sample),
        )

    def _merge_creators(
        self,
        all_name: str,
        theme: str,
        top_n: Optional[int],
        *,
        yt_res: Optional[RetrieverResult],
        tt_res: Optional[RetrieverResult],
        chosen: RetrieverConfig,
    ) -> MediaRetrievalResult:
        yt_rows = yt_res.results if yt_res else []
        tt_rows = tt_res.results if tt_res else []

        if not MEDIA_RETRIEVER_DEDUP_INFLUENCERS or not (yt_rows and tt_rows):
            merged = list(yt_rows) + list(tt_rows)
            merged.sort(key=lambda r: float(r.get("relevance") or 0), reverse=True)
            if top_n:
                merged = merged[:top_n]
            return self._build_merged_creators(
                all_name, theme, top_n, merged, yt_res, tt_res, chosen,
                deduped=False,
            )

        dedup_map = self._fetch_influencer_map(yt_rows, tt_rows)

        groups: Dict[str, Dict[str, Any]] = {}
        loose: List[Dict[str, Any]] = []

        def _account_for_yt(row: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "platform": "youtube",
                "channel_id": row.get("channel_id"),
                "creator": row.get("creator"),
                "relevance": row.get("relevance"),
                "video_count": row.get("video_count"),
                "sample_topics": row.get("sample_topics") or [],
                "sample_videos": row.get("sample_videos"),
            }

        def _account_for_tt(row: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "platform": "tiktok",
                "username": row.get("username"),
                "creator": row.get("creator"),
                "relevance": row.get("relevance"),
                "video_count": row.get("video_count"),
                "sample_topics": row.get("sample_topics") or [],
                "sample_videos": row.get("sample_videos"),
            }

        for row in yt_rows:
            cid = row.get("channel_id")
            inf = dedup_map.get(("youtube", cid)) if cid else None
            if inf:
                grp = groups.setdefault(
                    inf["influencer_name"] or cid or "unknown",
                    {
                        "influencer_name": inf["influencer_name"],
                        "creator": inf["influencer_name"] or row.get("creator"),
                        "relevance": 0.0,
                        "accounts": [],
                        "video_count": 0,
                        "explanation": {
                            "deduped_by_influencer": True,
                            "merge_rule": "max(relevance)",
                        },
                    },
                )
                grp["accounts"].append(_account_for_yt(row))
                rel = float(row.get("relevance") or 0)
                grp["relevance"] = max(float(grp["relevance"]), rel)
                grp["video_count"] += int(row.get("video_count") or 0)
            else:
                loose.append(
                    {
                        "creator": row.get("creator"),
                        "relevance": row.get("relevance"),
                        "accounts": [_account_for_yt(row)],
                        "video_count": row.get("video_count"),
                        "sample_topics": row.get("sample_topics") or [],
                        "sample_videos": row.get("sample_videos"),
                        "explanation": {"deduped_by_influencer": False},
                    }
                )

        for row in tt_rows:
            uname = row.get("username")
            inf = dedup_map.get(("tiktok", uname)) if uname else None
            if inf:
                grp = groups.setdefault(
                    inf["influencer_name"] or uname or "unknown",
                    {
                        "influencer_name": inf["influencer_name"],
                        "creator": inf["influencer_name"] or row.get("creator"),
                        "relevance": 0.0,
                        "accounts": [],
                        "video_count": 0,
                        "explanation": {
                            "deduped_by_influencer": True,
                            "merge_rule": "max(relevance)",
                        },
                    },
                )
                grp["accounts"].append(_account_for_tt(row))
                rel = float(row.get("relevance") or 0)
                grp["relevance"] = max(float(grp["relevance"]), rel)
                grp["video_count"] += int(row.get("video_count") or 0)
            else:
                loose.append(
                    {
                        "creator": row.get("creator"),
                        "relevance": row.get("relevance"),
                        "accounts": [_account_for_tt(row)],
                        "video_count": row.get("video_count"),
                        "sample_topics": row.get("sample_topics") or [],
                        "sample_videos": row.get("sample_videos"),
                        "explanation": {"deduped_by_influencer": False},
                    }
                )

        merged: List[Dict[str, Any]] = list(groups.values()) + loose
        merged.sort(key=lambda r: float(r.get("relevance") or 0), reverse=True)
        if top_n:
            merged = merged[:top_n]

        return self._build_merged_creators(
            all_name, theme, top_n, merged, yt_res, tt_res, chosen, deduped=True
        )

    def _build_merged_creators(
        self,
        all_name: str,
        theme: str,
        top_n: Optional[int],
        merged: List[Dict[str, Any]],
        yt_res: Optional[RetrieverResult],
        tt_res: Optional[RetrieverResult],
        chosen: RetrieverConfig,
        *,
        deduped: bool,
    ) -> MediaRetrievalResult:
        status = "ok" if merged else "empty"
        suggested: List[Dict[str, Any]] = []
        if status == "empty":
            suggested = (yt_res.suggested_actions if yt_res else None) or (
                tt_res.suggested_actions if tt_res else []
            )
        top = merged[0] if merged else None
        if top:
            top_name = top.get("influencer_name") or top.get("creator")
            summary = (
                f"Top creator across YouTube + TikTok for '{theme}' ({chosen.signal.replace('_', ' ')}): "
                f"{top_name}."
            )
        else:
            summary = f"No creators matched '{theme}' across YouTube + TikTok."
        return MediaRetrievalResult(
            retriever_name=all_name,
            platform="all",
            inputs={
                "theme": theme,
                "top_n": top_n,
                "platform": "all",
                "signal": chosen.signal,
                "family": chosen.family,
                **self._combined_scan_inputs(yt_res, tt_res),
            },
            raw_result=merged,
            summary=summary,
            status=status,
            suggested_actions=suggested,
            candidate_keys=self._combined_candidate_keys(yt_res, tt_res),
            per_platform=self._per_platform_dicts(yt_res, tt_res),
            deduped_by_influencer=deduped,
        )

    def _merge_videos(
        self,
        all_name: str,
        theme: str,
        top_n: Optional[int],
        *,
        yt_res: Optional[RetrieverResult],
        tt_res: Optional[RetrieverResult],
        chosen: RetrieverConfig,
    ) -> MediaRetrievalResult:
        rows = []
        if yt_res:
            rows.extend(yt_res.results)
        if tt_res:
            rows.extend(tt_res.results)

        # Sort by a uniform score so cross-platform videos are comparable.
        def _score(r: Dict[str, Any]) -> float:
            for k in ("relevance", "engagement_score", "score", "fused_score"):
                v = r.get(k)
                if v is not None:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        continue
            return 0.0

        rows.sort(key=_score, reverse=True)
        if top_n:
            rows = rows[:top_n]
        status = "ok" if rows else "empty"
        suggested = (
            (yt_res.suggested_actions if yt_res else None)
            or (tt_res.suggested_actions if tt_res else [])
        ) if status == "empty" else []
        summary = (
            f"Top videos across YouTube + TikTok for '{theme}': {len(rows)} rows."
            if rows
            else f"No videos matched '{theme}' across YouTube + TikTok."
        )

        return MediaRetrievalResult(
            retriever_name=all_name,
            platform="all",
            inputs={
                "theme": theme,
                "top_n": top_n,
                "platform": "all",
                "signal": chosen.signal,
                "family": chosen.family,
                **self._combined_scan_inputs(yt_res, tt_res),
            },
            raw_result=rows,
            summary=summary,
            status=status,
            suggested_actions=suggested,
            candidate_keys=self._combined_candidate_keys(yt_res, tt_res),
            per_platform=self._per_platform_dicts(yt_res, tt_res),
            deduped_by_influencer=False,
        )

    @staticmethod
    def _per_platform_dicts(
        yt_res: Optional[RetrieverResult],
        tt_res: Optional[RetrieverResult],
    ) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        if yt_res is not None:
            out["youtube"] = yt_res.to_dict()
        if tt_res is not None:
            out["tiktok"] = tt_res.to_dict()
        return out

    @staticmethod
    def _string_values(rows: List[Dict[str, Any]], key: str) -> List[str]:
        values: List[str] = []
        for row in rows:
            val = row.get(key)
            if isinstance(val, str):
                values.append(val)
        return values

    # ── Influencer dedup ────────────────────────────────────────────────────

    def _fetch_influencer_map(
        self,
        yt_rows: List[Dict[str, Any]],
        tt_rows: List[Dict[str, Any]],
    ) -> Dict[Tuple[str, Any], Dict[str, Any]]:
        """Map ``(platform, id) -> influencer record`` so we can group across platforms.

        The schema exposes ``Influencer.youtube_username`` and
        ``Influencer.tiktok_username`` as direct properties; we match
        on those plus the ``HAS_ACCOUNT`` relationships so we catch both
        the curated mapping and the live one.
        """
        # YouTube rows expose ``channel_id`` but the Influencer node uses
        # ``youtube_username``; we approximate by matching on the creator
        # name pulled from the channel (frontends typically use the channel
        # title). To stay safe we also pass channel_ids and union the result
        # with a relationship-based match.
        yt_creator_names = self._string_values(yt_rows, "creator")
        tt_usernames = self._string_values(tt_rows, "username")
        yt_channel_ids = self._string_values(yt_rows, "channel_id")

        mapping: Dict[Tuple[str, Any], Dict[str, Any]] = {}
        if not (yt_rows or tt_rows):
            return mapping
        if not (yt_creator_names or tt_usernames or yt_channel_ids):
            return mapping

        try:
            with get_session() as session:
                records = list(
                    run_neo4j_query(
                        session,
                        INFLUENCER_MAP_CYPHER,
                        yt_creator_names=yt_creator_names,
                        tt_usernames=tt_usernames,
                        yt_channel_ids=yt_channel_ids,
                    )
                )
        except Exception as exc:
            logger.warning("Influencer dedup query failed: %s", exc)
            return mapping

        for rec in records:
            inf = {
                "influencer_name": rec.get("influencer_name"),
                "youtube_username": rec.get("youtube_username"),
                "tiktok_username": rec.get("tiktok_username"),
            }
            for cid in rec.get("yt_channel_ids") or []:
                if cid:
                    mapping[("youtube", cid)] = inf
            for title in rec.get("yt_titles") or []:
                if title:
                    mapping[("youtube", title)] = inf
            for uname in rec.get("tt_usernames_list") or []:
                if uname:
                    mapping[("tiktok", uname)] = inf
            if inf["tiktok_username"]:
                mapping[("tiktok", inf["tiktok_username"])] = inf
        return mapping

    def _dedup_sample_creators(
        self,
        *,
        yt_res: Optional[RetrieverResult],
        tt_res: Optional[RetrieverResult],
    ) -> List[Dict[str, Any]]:
        """Best-effort dedup of the per-platform ``sample_creators`` returned by count retrievers."""
        yt_samples: List[Dict[str, Any]] = []
        tt_samples: List[Dict[str, Any]] = []
        if yt_res and yt_res.results:
            for row in yt_res.results:
                yt_samples.extend(row.get("sample") or [])
        if tt_res and tt_res.results:
            for row in tt_res.results:
                tt_samples.extend(row.get("sample") or [])

        yt_proxy_rows = [
            {"creator": s.get("creator"), "channel_id": s.get("channel_id")}
            for s in yt_samples
        ]
        tt_proxy_rows = [
            {"creator": s.get("creator"), "username": s.get("username")}
            for s in tt_samples
        ]
        mapping = self._fetch_influencer_map(yt_proxy_rows, tt_proxy_rows)

        groups: Dict[str, Dict[str, Any]] = {}
        loose: List[Dict[str, Any]] = []

        for s in yt_samples:
            cid = s.get("channel_id")
            inf = mapping.get(("youtube", cid)) if cid else None
            if inf:
                key = inf["influencer_name"] or str(cid)
                grp = groups.setdefault(
                    key,
                    {
                        "influencer_name": inf["influencer_name"],
                        "accounts": [],
                        "video_count": 0,
                    },
                )
                grp["accounts"].append({"platform": "youtube", **s})
                grp["video_count"] += int(s.get("video_count") or 0)
            else:
                loose.append({"platform": "youtube", **s})
        for s in tt_samples:
            uname = s.get("username")
            inf = mapping.get(("tiktok", uname)) if uname else None
            if inf:
                key = inf["influencer_name"] or str(uname)
                grp = groups.setdefault(
                    key,
                    {
                        "influencer_name": inf["influencer_name"],
                        "accounts": [],
                        "video_count": 0,
                    },
                )
                grp["accounts"].append({"platform": "tiktok", **s})
                grp["video_count"] += int(s.get("video_count") or 0)
            else:
                loose.append({"platform": "tiktok", **s})
        return list(groups.values()) + loose
