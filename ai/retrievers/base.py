"""Shared types and helpers for media retrievers.

This module centralizes:

- Env-driven defaults (``MEDIA_RETRIEVER_*``) so retrievers stay configurable
  without code changes.
- ``RetrieverConfig`` / ``RetrieverResult`` dataclasses — the uniform shape
  every retriever returns.
- An embedding helper that reuses the same OpenAI/Azure client pattern as
  ``ai/fewshots/vector_store.py`` and ``ai/agent/graph_analytics_agent.py``.
- A cached ``get_index_size`` plus ``compute_k`` so we can size vector
  ``top_k`` as a fraction of the actual indexed-node count (per the plan).
- Per-family query templates so the embedded text matches the embedding
  target distribution (e.g. ``audiences discussing {theme}`` vs
  ``videos about {theme}``).

None of the retriever Cypher lives here; this file is the small, reusable
scaffolding underneath ``youtube.py`` and ``tiktok.py``.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.neo4j import get_session  # type: ignore

try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv(dotenv_path=str(ROOT / ".env"))
except Exception:
    pass

logger = logging.getLogger("MediaRetrievers")


# ── Env-driven defaults ──────────────────────────────────────────────────────


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid float for %s=%r; using default %s", key, raw, default)
        return default


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid int for %s=%r; using default %s", key, raw, default)
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


# These are read once at import time and cached. Override via env at startup.
MEDIA_RETRIEVER_ENABLED = _env_bool("MEDIA_RETRIEVER_ENABLED", True)
MEDIA_RETRIEVER_DEFAULT_PLATFORM = os.environ.get(
    "MEDIA_RETRIEVER_DEFAULT_PLATFORM", "all"
).strip().lower() or "all"
MEDIA_RETRIEVER_MIN_SCORE = _env_float("MEDIA_RETRIEVER_MIN_SCORE", 0.7)


def get_media_retriever_min_score() -> float:
    """Read min_score from the environment on each call (Docker env reload safe)."""
    return _env_float("MEDIA_RETRIEVER_MIN_SCORE", 0.7)
MEDIA_RETRIEVER_K_FRACTION = _env_float("MEDIA_RETRIEVER_K_FRACTION", 0.20)
MEDIA_RETRIEVER_K_COUNT_FRACTION = _env_float(
    "MEDIA_RETRIEVER_K_COUNT_FRACTION", 1.0
)
# Hard floor so we never call queryNodes with k<=0 on an empty/small index.
MEDIA_RETRIEVER_K_FLOOR = _env_int("MEDIA_RETRIEVER_K_FLOOR", 50)
# Index-size cache TTL in seconds.
MEDIA_RETRIEVER_INDEX_SIZE_TTL = _env_int("MEDIA_RETRIEVER_INDEX_SIZE_TTL", 3600)
MEDIA_RETRIEVER_TOP_N = _env_int("MEDIA_RETRIEVER_TOP_N", 10)
MEDIA_RETRIEVER_USE_POSITION = _env_bool("MEDIA_RETRIEVER_USE_POSITION", False)
MEDIA_RETRIEVER_ENABLE_UNIFIED = _env_bool("MEDIA_RETRIEVER_ENABLE_UNIFIED", False)
MEDIA_RETRIEVER_AUTO_BROADEN = _env_bool("MEDIA_RETRIEVER_AUTO_BROADEN", False)
MEDIA_RETRIEVER_DEDUP_INFLUENCERS = _env_bool(
    "MEDIA_RETRIEVER_DEDUP_INFLUENCERS", True
)
MEDIA_RETRIEVER_TEMPLATES_DISABLED = _env_bool(
    "MEDIA_RETRIEVER_TEMPLATES_DISABLED", False
)


# ── Family templates ─────────────────────────────────────────────────────────
# The embedded text should match the distribution of the embedding target,
# not the user question. Per the plan, topic embeddings are short noun
# phrases, comment-summary embeddings are paragraph-length audience
# perspective, and content embeddings are creator-side video metadata.

FAMILY_TEMPLATES: Dict[str, str] = {
    "topic": "{theme}",
    "comment_summary": "audiences discussing {theme}",
    "content": "videos about {theme}",
}


def resolve_query_template(config: "RetrieverConfig") -> str:
    """Return the effective query template for a retriever.

    Resolution order: per-retriever override > per-family env override >
    family default > literal ``"{theme}"`` (when templates are disabled).
    """
    if MEDIA_RETRIEVER_TEMPLATES_DISABLED:
        return "{theme}"
    if config.query_template:
        return config.query_template
    family = config.family or ""
    env_key = f"MEDIA_RETRIEVER_TEMPLATE_{family.upper()}"
    env_override = os.environ.get(env_key)
    if env_override:
        return env_override
    return FAMILY_TEMPLATES.get(family, "{theme}")


def build_query_text(config: "RetrieverConfig", theme: str) -> str:
    template = resolve_query_template(config)
    try:
        return template.format(theme=theme.strip())
    except (KeyError, IndexError):
        # Template was malformed; fall back to the raw theme so we don't
        # blow up the whole retrieval path.
        logger.warning(
            "Invalid query_template %r for retriever %s; falling back to theme",
            template,
            config.name,
        )
        return theme.strip()


# ── Embedding client ─────────────────────────────────────────────────────────


_embed_client_lock = threading.Lock()
_embed_client: Optional[Any] = None
_embed_model_name: Optional[str] = None


def _build_embedding_client() -> Tuple[Any, str]:
    """Build an OpenAI or Azure-OpenAI embeddings client.

    Mirrors the notebook's ``build_embedding_client`` so query-time
    embeddings come from the same model that populated the indexes. Azure
    is preferred when configured; otherwise we fall back to the chat app's
    standard OpenAI client.
    """
    az_endpoint = os.environ.get("AZURE_OPENAI_EMBEDDING_ENDPOINT")
    az_key = os.environ.get("AZURE_OPENAI_EMBEDDING_API_KEY")
    if az_endpoint and az_key:
        from openai import AzureOpenAI  # type: ignore

        api_version = os.environ.get(
            "AZURE_OPENAI_EMBEDDING_API_VERSION", "2024-02-01"
        )
        deployment = (
            os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_MODEL_NAME")
            or os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME")
            or os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
            or "text-embedding-3-large"
        )
        client = AzureOpenAI(
            azure_endpoint=az_endpoint,
            api_key=az_key,
            api_version=api_version,
        )
        logger.info(
            "Media embeddings: Azure OpenAI (deployment=%s, api_version=%s)",
            deployment,
            api_version,
        )
        return client, deployment

    from openai import OpenAI  # type: ignore

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No embedding credentials found. Set OPENAI_API_KEY or "
            "AZURE_OPENAI_EMBEDDING_ENDPOINT/AZURE_OPENAI_EMBEDDING_API_KEY in .env."
        )
    model = (
        os.environ.get("MEDIA_EMBEDDING_MODEL")
        or os.environ.get("OPENAI_EMBEDDING_MODEL")
        or "text-embedding-3-large"
    )
    client = OpenAI(api_key=api_key)
    logger.info("Media embeddings: OpenAI (model=%s)", model)
    return client, model


def get_embedding_client() -> Tuple[Any, str]:
    """Lazily build and memoize the embedding client + model name."""
    global _embed_client, _embed_model_name
    if _embed_client is None:
        with _embed_client_lock:
            if _embed_client is None:
                _embed_client, _embed_model_name = _build_embedding_client()
    assert _embed_model_name is not None
    return _embed_client, _embed_model_name


def embed_query(text: str) -> List[float]:
    """Embed ``text`` with the media-retrievers embedding model.

    The caller is expected to pass an already-rendered ``query_text``
    (i.e. ``query_template.format(theme=theme)``); ``text`` itself is never
    the raw user question.
    """
    if not text or not text.strip():
        raise ValueError("embed_query: empty text")
    client, model = get_embedding_client()
    response = client.embeddings.create(model=model, input=[text])
    return list(response.data[0].embedding)


# ── Vector-index size cache ──────────────────────────────────────────────────
# Each retriever Cypher uses ``$k`` as the ``queryNodes`` top-k. We size
# ``k`` as a fraction of the actual indexed-node count so coverage stays
# consistent across signals (topic/summary/content) and as data grows.

# Maps index_name -> Cypher counting the nodes that have the relevant
# embedding property set (matches the production notebook cells).
_INDEX_COUNT_CYPHER: Dict[str, str] = {
    "video_content_embedding_index": (
        "MATCH (v:YouTubeVideo) "
        "WHERE v.video_content_embedding IS NOT NULL "
        "RETURN count(v) AS c"
    ),
    "video_summary_embedding_index": (
        "MATCH (v:YouTubeVideo) "
        "WHERE v.comment_summary_embedding IS NOT NULL "
        "RETURN count(v) AS c"
    ),
    "youtube_comment_topic_embedding_index": (
        "MATCH (t:YouTubeCommentTopic) "
        "WHERE t.embedding IS NOT NULL "
        "  AND coalesce(t.platform, 'youtube') = 'youtube' "
        "RETURN count(t) AS c"
    ),
    "tiktok_video_content_embedding_index": (
        "MATCH (v:TikTokVideo) "
        "WHERE v.video_content_embedding IS NOT NULL "
        "RETURN count(v) AS c"
    ),
    "tiktok_video_summary_embedding_index": (
        "MATCH (v:TikTokVideo) "
        "WHERE v.comment_summary_embedding IS NOT NULL "
        "RETURN count(v) AS c"
    ),
    "tiktok_comment_topic_embedding_index": (
        "MATCH (t:TikTokCommentTopic) "
        "WHERE t.embedding IS NOT NULL "
        "  AND coalesce(t.platform, 'tiktok') = 'tiktok' "
        "RETURN count(t) AS c"
    ),
}


_index_size_lock = threading.Lock()
_index_size_cache: Dict[str, Tuple[int, float]] = {}


@dataclass(frozen=True)
class IndexSizeLookup:
    """Result of sizing a vector index for ``queryNodes`` top-k."""

    size: int
    degraded_scan: bool = False


def list_expected_indexes() -> List[str]:
    """All six vector indexes the media retrievers depend on."""
    return list(_INDEX_COUNT_CYPHER.keys())


def _read_index_size_from_db(index_name: str) -> int:
    cypher = _INDEX_COUNT_CYPHER[index_name]
    with get_session() as session:
        rec = session.run(cypher).single()
        return int(rec["c"]) if rec else 0


def lookup_index_size(index_name: str, *, force_refresh: bool = False) -> IndexSizeLookup:
    """Return the node count for ``index_name`` and whether the scan is degraded.

    Successful lookups are cached for ``MEDIA_RETRIEVER_INDEX_SIZE_TTL``. Failed
    lookups are **not** cached as zero — we retry once, then reuse any prior
    successful cached size so ranked retrievers do not silently drop to ``k=50``.
    """
    cypher = _INDEX_COUNT_CYPHER.get(index_name)
    if not cypher:
        logger.warning("lookup_index_size: unknown index %r", index_name)
        return IndexSizeLookup(0, degraded_scan=True)

    now = time.time()
    if not force_refresh:
        cached = _index_size_cache.get(index_name)
        if cached and (now - cached[1]) < MEDIA_RETRIEVER_INDEX_SIZE_TTL:
            return IndexSizeLookup(cached[0], degraded_scan=False)

    with _index_size_lock:
        cached = _index_size_cache.get(index_name)
        if (
            not force_refresh
            and cached
            and (now - cached[1]) < MEDIA_RETRIEVER_INDEX_SIZE_TTL
        ):
            return IndexSizeLookup(cached[0], degraded_scan=False)

        last_exc: Optional[Exception] = None
        for attempt in range(2):
            try:
                size = _read_index_size_from_db(index_name)
                _index_size_cache[index_name] = (size, now)
                return IndexSizeLookup(size, degraded_scan=False)
            except Exception as exc:
                last_exc = exc
                if attempt == 0:
                    logger.warning(
                        "lookup_index_size(%s) attempt 1 failed: %s; retrying",
                        index_name,
                        exc,
                    )
                    time.sleep(0.25)

        stale = _index_size_cache.get(index_name)
        if stale and stale[0] > 0:
            logger.warning(
                "lookup_index_size(%s) failed after retry (%s); "
                "using stale cached size %d",
                index_name,
                last_exc,
                stale[0],
            )
            return IndexSizeLookup(stale[0], degraded_scan=False)

        logger.warning(
            "lookup_index_size(%s) failed after retry (%s); "
            "no cached size — vector scan will use k floor only (%d)",
            index_name,
            last_exc,
            MEDIA_RETRIEVER_K_FLOOR,
        )
        return IndexSizeLookup(0, degraded_scan=True)


def get_index_size(index_name: str, *, force_refresh: bool = False) -> int:
    """Return the current node count for ``index_name`` (cached, TTL-bounded)."""
    return lookup_index_size(index_name, force_refresh=force_refresh).size


def compute_k(index_size: int, *, is_count: bool) -> int:
    """Size the ``queryNodes`` top-k as a fraction of the index.

    Ranked retrievers use ``MEDIA_RETRIEVER_K_FRACTION`` (default 0.20);
    count retrievers use ``MEDIA_RETRIEVER_K_COUNT_FRACTION`` (default 1.0,
    a full scan so the count is honest). A small floor prevents pathological
    k=0 on empty/tiny indexes.
    """
    fraction = (
        MEDIA_RETRIEVER_K_COUNT_FRACTION if is_count else MEDIA_RETRIEVER_K_FRACTION
    )
    k = int(fraction * max(index_size, 0))
    return max(MEDIA_RETRIEVER_K_FLOOR, k)


# ── Result dataclasses ───────────────────────────────────────────────────────


@dataclass
class RetrieverConfig:
    """Metadata + dispatch for a single retriever.

    The ``runner`` callable receives:
        ``(config, theme, top_n, min_score)``

    and must return a ``RetrieverResult``. Per-platform retriever modules
    construct one ``RetrieverConfig`` per retriever and register it with the
    ``MediaRetrievalAgent``.
    """

    name: str
    description: str
    platform: str  # "youtube" | "tiktok"
    signal: str  # "topic" | "comment_summary" | "content" | "fused"
    family: str  # key into FAMILY_TEMPLATES; controls query_template default
    index_name: str
    is_count: bool
    output_kind: str  # "creators" | "videos" | "count" | "fused"
    keywords: Tuple[str, ...]
    defaults: Dict[str, Any] = field(default_factory=dict)
    query_template: Optional[str] = None  # explicit override
    runner: Optional[Callable[..., "RetrieverResult"]] = None


@dataclass
class RetrieverResult:
    """Uniform envelope returned by every media retriever.

    ``candidate_keys`` is what Phase 7 (hybrid) consumes. Each retriever
    populates only the keys it actually returned (e.g. ``content_videos``
    fills ``video_ids``; ``top_creators`` fills ``youtube_channel_ids``).
    """

    retriever: str
    platform: str
    signal: str
    family: str
    theme: str
    query_text: str
    k: int
    k_fraction: float
    index_size: int
    min_score: float
    top_n: Optional[int]
    results: List[Dict[str, Any]] = field(default_factory=list)
    candidate_keys: Dict[str, List[Any]] = field(default_factory=dict)
    sample_size: int = 0
    status: str = "ok"  # "ok" | "empty"
    max_observed_score: Optional[float] = None
    suggested_actions: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    degraded_scan: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "retriever": self.retriever,
            "platform": self.platform,
            "signal": self.signal,
            "family": self.family,
            "theme": self.theme,
            "query_text": self.query_text,
            "k": self.k,
            "k_fraction": self.k_fraction,
            "index_size": self.index_size,
            "min_score": self.min_score,
            "top_n": self.top_n,
            "degraded_scan": self.degraded_scan,
            "results": self.results,
            "candidate_keys": self.candidate_keys,
            "sample_size": self.sample_size,
            "status": self.status,
            "max_observed_score": self.max_observed_score,
            "suggested_actions": self.suggested_actions,
            "summary": self.summary,
        }


# ── Shared execution helpers ─────────────────────────────────────────────────


def _suggest_actions_on_empty(
    config: RetrieverConfig, min_score: float
) -> List[Dict[str, Any]]:
    """Build user-facing 'next step' suggestions when a retriever returns 0 rows."""
    actions: List[Dict[str, Any]] = []
    broadened = max(round(min_score - 0.10, 4), 0.50)
    if broadened < min_score:
        actions.append({"label": "broaden", "params": {"min_score": broadened}})
    if config.signal == "topic":
        actions.append({"label": "switch_signal", "to": "video_content"})
        actions.append({"label": "switch_signal", "to": "comment_summary"})
    elif config.signal == "content":
        actions.append({"label": "switch_signal", "to": "comment_topics"})
    elif config.signal == "comment_summary":
        actions.append({"label": "switch_signal", "to": "comment_topics"})
    if config.platform == "youtube":
        actions.append({"label": "switch_platform", "to": "tiktok"})
    elif config.platform == "tiktok":
        actions.append({"label": "switch_platform", "to": "youtube"})
    actions.append({"label": "rephrase", "params": {}})
    return actions


def _empty_result(
    config: RetrieverConfig,
    *,
    theme: str,
    query_text: str,
    k: int,
    index_size: int,
    min_score: float,
    top_n: Optional[int],
    max_observed: Optional[float],
    degraded_scan: bool = False,
) -> RetrieverResult:
    """Build a structured empty-result envelope (no rows above threshold)."""
    fraction = (
        MEDIA_RETRIEVER_K_COUNT_FRACTION
        if config.is_count
        else MEDIA_RETRIEVER_K_FRACTION
    )
    summary = (
        f"No {config.output_kind} matched '{theme}' above similarity "
        f"{min_score:.2f} on {config.platform.title()} "
        f"({config.signal.replace('_', ' ')})."
    )
    if max_observed is not None:
        summary += f" Best observed score was {max_observed:.2f}."
    return RetrieverResult(
        retriever=config.name,
        platform=config.platform,
        signal=config.signal,
        family=config.family,
        theme=theme,
        query_text=query_text,
        k=k,
        k_fraction=fraction,
        index_size=index_size,
        min_score=min_score,
        top_n=top_n,
        results=[],
        candidate_keys={},
        sample_size=0,
        status="empty",
        max_observed_score=max_observed,
        suggested_actions=_suggest_actions_on_empty(config, min_score),
        summary=summary,
        degraded_scan=degraded_scan,
    )


def prepare_query(
    config: RetrieverConfig,
    theme: str,
    *,
    explicit_min_score: Optional[float] = None,
    explicit_top_n: Optional[int] = None,
) -> Dict[str, Any]:
    """Bundle the inputs every retriever needs into one dict.

    Centralizes the "template -> embed -> compute k" flow so each retriever
    runner stays focused on its Cypher and row-shaping logic.
    """
    query_text = build_query_text(config, theme)
    embedding = embed_query(query_text)
    size_lookup = lookup_index_size(config.index_name)
    index_size = size_lookup.size
    degraded_scan = size_lookup.degraded_scan
    k = compute_k(index_size, is_count=config.is_count)
    if not config.is_count and explicit_top_n is not None:
        # Ranked retrievers need k >= top_n so the LIMIT clause has rows.
        k = max(k, int(explicit_top_n))
    min_score = (
        float(explicit_min_score)
        if explicit_min_score is not None
        else float(config.defaults.get("min_score", get_media_retriever_min_score()))
    )
    top_n = (
        int(explicit_top_n)
        if explicit_top_n is not None
        else int(config.defaults.get("top_n", MEDIA_RETRIEVER_TOP_N))
    )
    fraction = (
        MEDIA_RETRIEVER_K_COUNT_FRACTION
        if config.is_count
        else MEDIA_RETRIEVER_K_FRACTION
    )
    return {
        "query_text": query_text,
        "embedding": embedding,
        "k": k,
        "k_fraction": fraction,
        "index_size": index_size,
        "min_score": min_score,
        "top_n": top_n,
        "degraded_scan": degraded_scan,
    }
