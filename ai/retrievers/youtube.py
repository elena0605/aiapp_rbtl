"""YouTube media retrievers.

13 retrievers ported from
``/Users/elenasimoska/airflow_upgrade/notebooks/youtube_prod_comment_summary_embeddings.ipynb``.

Each retriever:
- Resolves an embedding query via its family template (see ``base.FAMILY_TEMPLATES``).
- Embeds that query (never the raw user question).
- Sizes ``$k`` as a fraction of the actual indexed-node count.
- Runs a single, parameterized Cypher against the production Neo4j.
- Returns a ``RetrieverResult`` with inline per-row ``explanation`` data
  and the ``candidate_keys`` Phase 7 hybrid composition needs.

Min-score default is 0.75 (notebook default was 0.0) to keep low-relevance
themes from flooding chat answers.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from utils.neo4j import get_session

from .base import (
    MEDIA_RETRIEVER_TOP_N,
    RetrieverConfig,
    RetrieverResult,
    _empty_result,
    prepare_query,
)

logger = logging.getLogger("MediaRetrievers.YouTube")

PLATFORM = "youtube"

# ── Index names ──────────────────────────────────────────────────────────────
TOPIC_INDEX = "youtube_comment_topic_embedding_index"
SUMMARY_INDEX = "video_summary_embedding_index"
CONTENT_INDEX = "video_content_embedding_index"


# ── Cypher (ported verbatim from the notebook) ──────────────────────────────

_TOP_CREATORS_CYPHER = """
CALL db.index.vector.queryNodes($index, $k, $q) YIELD node AS t, score
WHERE coalesce(t.platform, 'youtube') = $platform
  AND score >= $min_score
MATCH (v:YouTubeVideo)-[rel:HAS_COMMENT_TOPIC]->(t)
WHERE coalesce(rel.platform, 'youtube') = $platform
OPTIONAL MATCH (c:YouTubeChannel)-[hv:HAS_VIDEO]->(v)
WHERE coalesce(hv.platform, "YouTube") = "YouTube"
WITH
  coalesce(c.title, v.channel_title, v.username, 'unknown') AS creator,
  coalesce(c.channel_id, v.channel_id) AS channel_id,
  t, v, rel, score
WITH
  creator,
  channel_id,
  sum(score * coalesce(rel.weight, 1.0)) AS relevance,
  max(score * coalesce(rel.weight, 1.0)) AS best_weighted_score,
  max(score) AS max_score,
  count(DISTINCT v) AS video_count,
  collect(DISTINCT t.name) AS sample_topics,
  collect(DISTINCT {video_id: v.video_id, title: v.video_title, url: v.video_url}) AS sample_videos
RETURN creator, channel_id, relevance, best_weighted_score, max_score,
       video_count, sample_topics, sample_videos
ORDER BY relevance DESC
LIMIT $top_n
"""

_EXAMPLE_VIDEOS_CYPHER = """
CALL db.index.vector.queryNodes($index, $k, $q) YIELD node AS t, score
WHERE coalesce(t.platform, 'youtube') = $platform
  AND score >= $min_score
MATCH (v:YouTubeVideo)-[rel:HAS_COMMENT_TOPIC]->(t)
WHERE coalesce(rel.platform, 'youtube') = $platform
WITH v, t, rel, score
ORDER BY score * coalesce(rel.weight, 1.0) DESC
WITH v,
     collect({topic: t.name, weight: rel.weight, score: score}) AS matches,
     max(score * coalesce(rel.weight, 1.0)) AS best
RETURN v.video_id AS video_id,
       v.video_title AS title,
       coalesce(v.channel_title, v.username) AS creator,
       coalesce(v.channel_id, '') AS channel_id,
       v.video_url AS url,
       v.view_count AS views,
       best AS relevance,
       matches
ORDER BY best DESC
LIMIT $top_n
"""

_COMMENT_DISCUSSIONS_CYPHER = """
CALL db.index.vector.queryNodes($index, $k, $q) YIELD node AS v, score
WHERE score >= $min_score
RETURN v.video_id AS video_id,
       v.video_title AS title,
       coalesce(v.channel_title, v.username) AS creator,
       coalesce(v.channel_id, '') AS channel_id,
       v.video_url AS url,
       score,
       v.comment_summary_description AS comment_summary_description
ORDER BY score DESC
LIMIT $top_n
"""

_CONTENT_VIDEOS_CYPHER = """
CALL db.index.vector.queryNodes($index, $k, $q) YIELD node AS v, score
WHERE score >= $min_score
RETURN v.video_id AS video_id,
       v.video_title AS title,
       coalesce(v.channel_title, v.username) AS creator,
       coalesce(v.channel_id, '') AS channel_id,
       v.video_url AS url,
       v.view_count AS views,
       v.thumbnail_url AS thumbnail_url,
       v.thumbnail_description AS thumbnail_description,
       v.video_description AS video_description,
       v.thumbnail_keywords AS thumbnail_keywords,
       v.tags AS tags,
       score
ORDER BY score DESC
LIMIT $top_n
"""

_CONTENT_TOP_CREATORS_CYPHER = """
CALL db.index.vector.queryNodes($index, $k, $q) YIELD node AS v, score
WHERE score >= $min_score
OPTIONAL MATCH (c:YouTubeChannel)-[hv:HAS_VIDEO]->(v)
WHERE coalesce(hv.platform, "YouTube") = "YouTube"
WITH coalesce(c.title, v.channel_title, v.username, 'unknown') AS creator,
     coalesce(c.channel_id, v.channel_id) AS channel_id,
     v, score
WITH creator, channel_id,
     sum(score) AS relevance,
     max(score) AS max_score,
     count(DISTINCT v) AS video_count,
     collect({video_id: v.video_id, title: v.video_title, url: v.video_url, score: score}) AS sample_videos
RETURN creator, channel_id, relevance, max_score, video_count, sample_videos
ORDER BY relevance DESC
LIMIT $top_n
"""

_COUNT_CREATORS_BY_TOPIC_CYPHER = """
CALL db.index.vector.queryNodes($index, $k, $q) YIELD node AS t, score
WHERE coalesce(t.platform, 'youtube') = $platform
  AND score >= $min_score
MATCH (v:YouTubeVideo)-[rel:HAS_COMMENT_TOPIC]->(t)
WHERE coalesce(rel.platform, 'youtube') = $platform
OPTIONAL MATCH (c:YouTubeChannel)-[hv:HAS_VIDEO]->(v)
WHERE coalesce(hv.platform, "YouTube") = "YouTube"
WITH
  coalesce(c.title, v.channel_title, v.username, 'unknown') AS creator,
  coalesce(c.channel_id, v.channel_id) AS channel_id,
  v,
  score * coalesce(rel.weight, 1.0) AS weighted_score
WITH creator, channel_id,
     count(DISTINCT v) AS video_count,
     max(weighted_score) AS best_weighted_score
RETURN count(*) AS creator_count,
       sum(video_count) AS video_link_rows,
       max(best_weighted_score) AS max_observed_score,
       collect({
         creator: creator,
         channel_id: channel_id,
         video_count: video_count,
         best_weighted_score: best_weighted_score
       }) AS sample_creators
"""

_COUNT_CREATORS_BY_CONTENT_CYPHER = """
CALL db.index.vector.queryNodes($index, $k, $q) YIELD node AS v, score
WHERE score >= $min_score
OPTIONAL MATCH (c:YouTubeChannel)-[hv:HAS_VIDEO]->(v)
WHERE coalesce(hv.platform, "YouTube") = "YouTube"
WITH
  coalesce(c.title, v.channel_title, v.username, 'unknown') AS creator,
  coalesce(c.channel_id, v.channel_id) AS channel_id,
  v,
  score
WITH creator, channel_id,
     count(DISTINCT v) AS video_count,
     max(score) AS best_score
RETURN count(*) AS creator_count,
       sum(video_count) AS video_link_rows,
       max(best_score) AS max_observed_score,
       collect({
         creator: creator,
         channel_id: channel_id,
         video_count: video_count,
         best_score: best_score
       }) AS sample_creators
"""

_COUNT_VIDEOS_BY_TOPIC_CYPHER = """
CALL db.index.vector.queryNodes($index, $k, $q) YIELD node AS t, score
WHERE coalesce(t.platform, 'youtube') = $platform
  AND score >= $min_score
MATCH (v:YouTubeVideo)-[rel:HAS_COMMENT_TOPIC]->(t)
WHERE coalesce(rel.platform, 'youtube') = $platform
WITH v, score * coalesce(rel.weight, 1.0) AS weighted_score
WITH v, max(weighted_score) AS best_weighted_score
RETURN count(v) AS video_count,
       max(best_weighted_score) AS max_observed_score,
       collect({
         video_id: v.video_id,
         title: v.video_title,
         creator: coalesce(v.channel_title, v.username),
         url: v.video_url,
         best_weighted_score: best_weighted_score
       }) AS sample_videos
"""

_COUNT_VIDEOS_BY_COMMENT_SUMMARY_CYPHER = """
CALL db.index.vector.queryNodes($index, $k, $q) YIELD node AS v, score
WHERE score >= $min_score
WITH v, max(score) AS best_score
RETURN count(v) AS video_count,
       max(best_score) AS max_observed_score,
       collect({
         video_id: v.video_id,
         title: v.video_title,
         creator: coalesce(v.channel_title, v.username),
         url: v.video_url,
         score: best_score
       }) AS sample_videos
"""

_COUNT_VIDEOS_BY_CONTENT_CYPHER = """
CALL db.index.vector.queryNodes($index, $k, $q) YIELD node AS v, score
WHERE score >= $min_score
WITH v, max(score) AS best_score
RETURN count(v) AS video_count,
       max(best_score) AS max_observed_score,
       collect({
         video_id: v.video_id,
         title: v.video_title,
         creator: coalesce(v.channel_title, v.username),
         url: v.video_url,
         score: best_score
       }) AS sample_videos
"""

_TOP_VIDEOS_BY_TOPIC_ENGAGEMENT_CYPHER = """
CALL db.index.vector.queryNodes($index, $k, $q) YIELD node AS t, score
WHERE coalesce(t.platform, 'youtube') = $platform
  AND score >= $min_score
MATCH (v:YouTubeVideo)-[rel:HAS_COMMENT_TOPIC]->(t)
WHERE coalesce(rel.platform, 'youtube') = $platform
WITH v, t, rel, score,
  score * coalesce(rel.weight, 1.0) AS topic_strength,
  log(1.0 + toFloat(coalesce(v.comment_count, 0))) AS log_comments
WITH v,
  max(topic_strength) AS best_topic_strength,
  max(log_comments) AS log_comments,
  collect(DISTINCT {topic: t.name, weight: rel.weight, score: score}) AS matches
WITH v, best_topic_strength, log_comments, matches,
  best_topic_strength * log_comments AS engagement_score
RETURN v.video_id AS video_id,
       v.video_title AS title,
       coalesce(v.channel_title, v.username) AS creator,
       coalesce(v.channel_id, '') AS channel_id,
       v.video_url AS url,
       toInteger(coalesce(v.comment_count, 0)) AS comment_count,
       round(best_topic_strength, 5) AS best_topic_strength,
       round(log_comments, 5) AS log_comments,
       round(engagement_score, 5) AS engagement_score,
       matches
ORDER BY engagement_score DESC
LIMIT $top_n
"""

_TOP_CREATORS_BY_TOPIC_ENGAGEMENT_CYPHER = """
CALL db.index.vector.queryNodes($index, $k, $q) YIELD node AS t, score
WHERE coalesce(t.platform, 'youtube') = $platform
  AND score >= $min_score
MATCH (v:YouTubeVideo)-[rel:HAS_COMMENT_TOPIC]->(t)
WHERE coalesce(rel.platform, 'youtube') = $platform
OPTIONAL MATCH (c:YouTubeChannel)-[hv:HAS_VIDEO]->(v)
WHERE coalesce(hv.platform, "YouTube") = "YouTube"
WITH
  coalesce(c.title, v.channel_title, v.username, 'unknown') AS creator,
  coalesce(c.channel_id, v.channel_id) AS channel_id,
  v, t, rel, score,
  score * coalesce(rel.weight, 1.0) AS topic_strength,
  log(1.0 + toFloat(coalesce(v.comment_count, 0))) AS log_comments
WITH creator, channel_id, v,
  max(topic_strength) AS video_topic_strength,
  max(log_comments) AS log_comments,
  collect(DISTINCT t.name) AS video_topics
WITH creator, channel_id, v, video_topics,
  video_topic_strength * log_comments AS video_engagement,
  toInteger(coalesce(v.comment_count, 0)) AS comment_count
WITH creator, channel_id,
  sum(video_engagement) AS engagement_score,
  max(video_engagement) AS max_video_engagement,
  count(DISTINCT v) AS video_count,
  sum(comment_count) AS total_comment_count,
  collect(DISTINCT video_topics) AS sample_topics,
  collect({
    video_id: v.video_id,
    title: v.video_title,
    url: v.video_url,
    comment_count: comment_count,
    engagement_score: round(video_engagement, 5)
  }) AS sample_videos
RETURN creator,
       channel_id,
       round(engagement_score, 5) AS engagement_score,
       round(max_video_engagement, 5) AS max_video_engagement,
       video_count,
       total_comment_count,
       sample_topics,
       sample_videos
ORDER BY engagement_score DESC
LIMIT $top_n
"""

# ── Fused / unified search ───────────────────────────────────────────────────

_UNIFIED_CONTENT_Q = """
CALL db.index.vector.queryNodes('video_content_embedding_index', $k, $q) YIELD node AS v, score
WHERE score >= $min_score
RETURN v.video_id AS video_id, score
"""

_UNIFIED_SUMMARY_Q = """
CALL db.index.vector.queryNodes('video_summary_embedding_index', $k, $q) YIELD node AS v, score
WHERE score >= $min_score
RETURN v.video_id AS video_id, score
"""

_UNIFIED_TOPIC_Q = """
CALL db.index.vector.queryNodes('youtube_comment_topic_embedding_index', $k, $q) YIELD node AS t, score
WHERE coalesce(t.platform, 'youtube') = $platform
  AND score >= $min_score
MATCH (v:YouTubeVideo)-[rel:HAS_COMMENT_TOPIC]->(t)
WHERE coalesce(rel.platform, 'youtube') = $platform
WITH v.video_id AS video_id, max(score * coalesce(rel.weight, 1.0)) AS score
RETURN video_id, score
"""

_UNIFIED_HYDRATE = """
UNWIND $video_ids AS vid
MATCH (v:YouTubeVideo {video_id: vid})
OPTIONAL MATCH (c:YouTubeChannel)-[hv:HAS_VIDEO]->(v)
WHERE coalesce(hv.platform, "YouTube") = "YouTube"
RETURN v.video_id AS video_id,
       v.video_title AS title,
       coalesce(c.title, v.channel_title, v.username) AS creator,
       coalesce(c.channel_id, v.channel_id) AS channel_id,
       v.video_url AS url,
       v.view_count AS views,
       v.thumbnail_description AS thumbnail_description,
       v.video_description AS video_description,
       v.comment_summary_description AS comment_summary_description
"""


# ── Runner helpers ───────────────────────────────────────────────────────────


def _safe_dict(record) -> Dict[str, Any]:
    """Convert a Neo4j Record to a plain dict (handles ``Record`` or dict)."""
    return dict(record) if record is not None else {}


def _build_creator_results(
    rows: List[Dict[str, Any]], *, ranking_key: str, score_keys: Tuple[str, ...]
) -> Tuple[List[Dict[str, Any]], Dict[str, List[Any]]]:
    """Shape creator-family rows + collect ``youtube_channel_ids``.

    ``score_keys`` are the columns from the Cypher RETURN that the
    explanation block exposes so the frontend can render "why this rank".
    """
    results: List[Dict[str, Any]] = []
    channel_ids: List[str] = []
    for row in rows:
        creator = row.get("creator") or "unknown"
        channel_id = row.get("channel_id") or None
        explanation = {
            "relevance_ranking": row.get(ranking_key),
            "video_count": row.get("video_count"),
            "sample_topics": row.get("sample_topics") or [],
            "sample_videos": row.get("sample_videos") or [],
            "score_breakdown": {k: row.get(k) for k in score_keys},
        }
        shaped = {
            "creator": creator,
            "channel_id": channel_id,
            "platform": PLATFORM,
            "relevance": row.get(ranking_key),
            "video_count": row.get("video_count"),
            "sample_topics": row.get("sample_topics") or [],
            "sample_videos": row.get("sample_videos") or [],
            "explanation": explanation,
        }
        # Preserve any engagement-specific extras when present.
        for extra in ("total_comment_count", "engagement_score", "max_video_engagement"):
            if extra in row:
                shaped[extra] = row[extra]
        results.append(shaped)
        if channel_id:
            channel_ids.append(channel_id)
    return results, ({"youtube_channel_ids": channel_ids} if channel_ids else {})


def _build_video_results(
    rows: List[Dict[str, Any]], *, ranking_key: str
) -> Tuple[List[Dict[str, Any]], Dict[str, List[Any]]]:
    """Shape video-family rows + collect ``video_ids`` and ``youtube_channel_ids``."""
    results: List[Dict[str, Any]] = []
    video_ids: List[str] = []
    channel_ids: List[str] = []
    for row in rows:
        video_id = row.get("video_id")
        channel_id = row.get("channel_id") or None
        ranking_value = row.get(ranking_key)
        explanation = {
            "relevance_ranking": ranking_value,
            "matches": row.get("matches") or [],
            "score_breakdown": {
                k: row.get(k)
                for k in ("best_topic_strength", "log_comments", "engagement_score", "score", "relevance")
                if k in row
            },
        }
        shaped = dict(row)
        shaped["platform"] = PLATFORM
        shaped["explanation"] = explanation
        # Promote a uniform ``relevance`` field so the frontend can sort across retrievers.
        if "relevance" not in shaped and ranking_value is not None:
            shaped["relevance"] = ranking_value
        results.append(shaped)
        if video_id:
            video_ids.append(video_id)
        if channel_id:
            channel_ids.append(channel_id)
    candidate_keys: Dict[str, List[Any]] = {}
    if video_ids:
        candidate_keys["video_ids"] = video_ids
    if channel_ids:
        candidate_keys["youtube_channel_ids"] = list(dict.fromkeys(channel_ids))
    return results, candidate_keys


def _run_ranked(
    config: RetrieverConfig,
    theme: str,
    *,
    cypher: str,
    top_n: Optional[int],
    min_score: Optional[float],
    pass_platform: bool,
    output_kind: str,
    ranking_key: str,
    creator_score_keys: Tuple[str, ...] = (),
) -> RetrieverResult:
    """Generic runner for the ranked retrievers (creators / videos)."""
    ctx = prepare_query(
        config, theme, explicit_min_score=min_score, explicit_top_n=top_n
    )
    params: Dict[str, Any] = {
        "index": config.index_name,
        "q": ctx["embedding"],
        "k": ctx["k"],
        "min_score": ctx["min_score"],
        "top_n": ctx["top_n"],
    }
    if pass_platform:
        params["platform"] = PLATFORM

    logger.info(
        "yt:%s theme=%r k=%s index_size=%s min_score=%.2f top_n=%s",
        config.name, theme, ctx["k"], ctx["index_size"], ctx["min_score"], ctx["top_n"],
    )

    with get_session() as session:
        rows = [_safe_dict(r) for r in session.run(cypher, **params)]

    if not rows:
        return _empty_result(
            config,
            theme=theme,
            query_text=ctx["query_text"],
            k=ctx["k"],
            index_size=ctx["index_size"],
            min_score=ctx["min_score"],
            top_n=ctx["top_n"],
            max_observed=None,
            degraded_scan=ctx["degraded_scan"],
        )

    if output_kind == "creators":
        results, candidate_keys = _build_creator_results(
            rows, ranking_key=ranking_key, score_keys=creator_score_keys
        )
    else:
        results, candidate_keys = _build_video_results(
            rows, ranking_key=ranking_key
        )

    return RetrieverResult(
        retriever=config.name,
        platform=PLATFORM,
        signal=config.signal,
        family=config.family,
        theme=theme,
        query_text=ctx["query_text"],
        k=ctx["k"],
        k_fraction=ctx["k_fraction"],
        index_size=ctx["index_size"],
        min_score=ctx["min_score"],
        top_n=ctx["top_n"],
        results=results,
        candidate_keys=candidate_keys,
        sample_size=len(results),
        status="ok",
        summary=_summarize_ranked(config, results, theme),
        degraded_scan=ctx["degraded_scan"],
    )


def _run_count(
    config: RetrieverConfig,
    theme: str,
    *,
    cypher: str,
    min_score: Optional[float],
    pass_platform: bool,
    count_field: str,
    sample_field: str,
) -> RetrieverResult:
    """Generic runner for the count retrievers (creator_count / video_count)."""
    ctx = prepare_query(config, theme, explicit_min_score=min_score)
    params: Dict[str, Any] = {
        "index": config.index_name,
        "q": ctx["embedding"],
        "k": ctx["k"],
        "min_score": ctx["min_score"],
    }
    if pass_platform:
        params["platform"] = PLATFORM

    logger.info(
        "yt:%s theme=%r k=%s index_size=%s min_score=%.2f (count)",
        config.name, theme, ctx["k"], ctx["index_size"], ctx["min_score"],
    )

    with get_session() as session:
        record = session.run(cypher, **params).single()

    if record is None:
        return _empty_result(
            config,
            theme=theme,
            query_text=ctx["query_text"],
            k=ctx["k"],
            index_size=ctx["index_size"],
            min_score=ctx["min_score"],
            top_n=None,
            max_observed=None,
            degraded_scan=ctx["degraded_scan"],
        )

    count = int(record.get(count_field) or 0)
    samples = list(record.get(sample_field) or [])
    max_observed = record.get("max_observed_score")
    max_observed_f = float(max_observed) if max_observed is not None else None

    candidate_keys: Dict[str, List[Any]] = {}
    if config.output_kind == "count" and config.signal == "topic":
        ids = [s.get("channel_id") for s in samples if s.get("channel_id")]
        if ids:
            candidate_keys["youtube_channel_ids"] = list(dict.fromkeys(ids))
    elif sample_field == "sample_videos":
        vids = [s.get("video_id") for s in samples if s.get("video_id") is not None]
        if vids:
            candidate_keys["video_ids"] = list(dict.fromkeys(vids))
    elif sample_field == "sample_creators":
        ids = [s.get("channel_id") for s in samples if s.get("channel_id")]
        if ids:
            candidate_keys["youtube_channel_ids"] = list(dict.fromkeys(ids))

    explanation_summary = (
        f"{count} matches above similarity {ctx['min_score']:.2f} "
        f"(scanned {ctx['k']}/{ctx['index_size']} indexed nodes)"
    )

    results: List[Dict[str, Any]] = [
        {
            "platform": PLATFORM,
            "signal": config.signal,
            "count_field": count_field,
            "count": count,
            "k": ctx["k"],
            "k_fraction": ctx["k_fraction"],
            "index_size": ctx["index_size"],
            "min_score": ctx["min_score"],
            "max_observed_score": max_observed_f,
            "video_link_rows": int(record.get("video_link_rows") or 0)
            if "video_link_rows" in record.keys()
            else None,
            "sample": samples,
            "explanation": {
                "summary": explanation_summary,
                "max_observed_score": max_observed_f,
                "scanned": ctx["k"],
                "index_size": ctx["index_size"],
            },
        }
    ]
    if count <= 0:
        return _empty_result(
            config,
            theme=theme,
            query_text=ctx["query_text"],
            k=ctx["k"],
            index_size=ctx["index_size"],
            min_score=ctx["min_score"],
            top_n=None,
            max_observed=max_observed_f,
            degraded_scan=ctx["degraded_scan"],
        )

    summary = _summarize_count(
        config, count, ctx["min_score"], ctx["k"], ctx["index_size"], theme
    )
    return RetrieverResult(
        retriever=config.name,
        platform=PLATFORM,
        signal=config.signal,
        family=config.family,
        theme=theme,
        query_text=ctx["query_text"],
        k=ctx["k"],
        k_fraction=ctx["k_fraction"],
        index_size=ctx["index_size"],
        min_score=ctx["min_score"],
        top_n=None,
        results=results,
        candidate_keys=candidate_keys,
        sample_size=len(samples),
        status="ok",
        max_observed_score=max_observed_f,
        summary=summary,
        degraded_scan=ctx["degraded_scan"],
    )


# ── Summary builders ─────────────────────────────────────────────────────────


def _summarize_ranked(
    config: RetrieverConfig, results: List[Dict[str, Any]], theme: str
) -> str:
    if not results:
        return f"No {config.output_kind} matched '{theme}' on YouTube."
    if config.output_kind == "creators":
        top = results[0]
        return (
            f"Top YouTube creators for '{theme}' ({config.signal.replace('_', ' ')}): "
            f"{top.get('creator')} leads with {top.get('video_count')} matching videos."
        )
    if config.output_kind == "videos":
        top = results[0]
        return (
            f"Top YouTube videos for '{theme}' ({config.signal.replace('_', ' ')}): "
            f"\"{top.get('title')}\" by {top.get('creator')}."
        )
    return f"Returned {len(results)} YouTube rows for '{theme}'."


def _summarize_count(
    config: RetrieverConfig,
    count: int,
    min_score: float,
    k: int,
    index_size: int,
    theme: str,
) -> str:
    return (
        f"{count} YouTube {config.output_kind.split('_')[0]} matched '{theme}' "
        f"({config.signal.replace('_', ' ')}) above similarity {min_score:.2f} "
        f"(scanned {k}/{index_size})."
    )


# ── Public runners (one per retriever) ───────────────────────────────────────


def _run_top_creators(config, theme, *, top_n=None, min_score=None, **_):
    return _run_ranked(
        config, theme, cypher=_TOP_CREATORS_CYPHER, top_n=top_n, min_score=min_score,
        pass_platform=True, output_kind="creators", ranking_key="relevance",
        creator_score_keys=("relevance", "best_weighted_score", "max_score", "video_count"),
    )


def _run_example_videos(config, theme, *, top_n=None, min_score=None, **_):
    return _run_ranked(
        config, theme, cypher=_EXAMPLE_VIDEOS_CYPHER, top_n=top_n, min_score=min_score,
        pass_platform=True, output_kind="videos", ranking_key="relevance",
    )


def _run_comment_discussions(config, theme, *, top_n=None, min_score=None, **_):
    return _run_ranked(
        config, theme, cypher=_COMMENT_DISCUSSIONS_CYPHER, top_n=top_n, min_score=min_score,
        pass_platform=False, output_kind="videos", ranking_key="score",
    )


def _run_content_videos(config, theme, *, top_n=None, min_score=None, **_):
    return _run_ranked(
        config, theme, cypher=_CONTENT_VIDEOS_CYPHER, top_n=top_n, min_score=min_score,
        pass_platform=False, output_kind="videos", ranking_key="score",
    )


def _run_content_top_creators(config, theme, *, top_n=None, min_score=None, **_):
    return _run_ranked(
        config, theme, cypher=_CONTENT_TOP_CREATORS_CYPHER, top_n=top_n, min_score=min_score,
        pass_platform=False, output_kind="creators", ranking_key="relevance",
        creator_score_keys=("relevance", "max_score", "video_count"),
    )


def _run_top_videos_by_topic_engagement(config, theme, *, top_n=None, min_score=None, **_):
    return _run_ranked(
        config, theme, cypher=_TOP_VIDEOS_BY_TOPIC_ENGAGEMENT_CYPHER,
        top_n=top_n, min_score=min_score, pass_platform=True,
        output_kind="videos", ranking_key="engagement_score",
    )


def _run_top_creators_by_topic_engagement(config, theme, *, top_n=None, min_score=None, **_):
    return _run_ranked(
        config, theme, cypher=_TOP_CREATORS_BY_TOPIC_ENGAGEMENT_CYPHER,
        top_n=top_n, min_score=min_score, pass_platform=True,
        output_kind="creators", ranking_key="engagement_score",
        creator_score_keys=("engagement_score", "max_video_engagement", "video_count", "total_comment_count"),
    )


def _run_count_creators_by_topic(config, theme, *, min_score=None, **_):
    return _run_count(
        config, theme, cypher=_COUNT_CREATORS_BY_TOPIC_CYPHER, min_score=min_score,
        pass_platform=True, count_field="creator_count", sample_field="sample_creators",
    )


def _run_count_creators_by_content(config, theme, *, min_score=None, **_):
    return _run_count(
        config, theme, cypher=_COUNT_CREATORS_BY_CONTENT_CYPHER, min_score=min_score,
        pass_platform=False, count_field="creator_count", sample_field="sample_creators",
    )


def _run_count_videos_by_topic(config, theme, *, min_score=None, **_):
    return _run_count(
        config, theme, cypher=_COUNT_VIDEOS_BY_TOPIC_CYPHER, min_score=min_score,
        pass_platform=True, count_field="video_count", sample_field="sample_videos",
    )


def _run_count_videos_by_comment_summary(config, theme, *, min_score=None, **_):
    return _run_count(
        config, theme, cypher=_COUNT_VIDEOS_BY_COMMENT_SUMMARY_CYPHER, min_score=min_score,
        pass_platform=False, count_field="video_count", sample_field="sample_videos",
    )


def _run_count_videos_by_content(config, theme, *, min_score=None, **_):
    return _run_count(
        config, theme, cypher=_COUNT_VIDEOS_BY_CONTENT_CYPHER, min_score=min_score,
        pass_platform=False, count_field="video_count", sample_field="sample_videos",
    )


def _rrf_rank(rows: List[Dict[str, Any]], k_const: int = 60) -> Dict[str, float]:
    """Reciprocal Rank Fusion — robust to differing score scales across indexes."""
    scores: Dict[str, float] = {}
    for rank, row in enumerate(rows):
        vid = row.get("video_id")
        if vid is None:
            continue
        scores[vid] = 1.0 / (k_const + rank + 1)
    return scores


def _run_unified_search(config, theme, *, top_n=None, min_score=None, **_):
    ctx = prepare_query(
        config, theme, explicit_min_score=min_score, explicit_top_n=top_n
    )
    with get_session() as session:
        content_rows = [
            _safe_dict(r)
            for r in session.run(
                _UNIFIED_CONTENT_Q, q=ctx["embedding"], k=ctx["k"], min_score=ctx["min_score"]
            )
        ]
        summary_rows = [
            _safe_dict(r)
            for r in session.run(
                _UNIFIED_SUMMARY_Q, q=ctx["embedding"], k=ctx["k"], min_score=ctx["min_score"]
            )
        ]
        topic_rows = [
            _safe_dict(r)
            for r in session.run(
                _UNIFIED_TOPIC_Q,
                q=ctx["embedding"],
                k=ctx["k"],
                min_score=ctx["min_score"],
                platform=PLATFORM,
            )
        ]

        content_rank = _rrf_rank(content_rows)
        summary_rank = _rrf_rank(summary_rows)
        topic_rank = _rrf_rank(topic_rows)

        fused: Dict[str, float] = {}
        signals: Dict[str, List[str]] = {}
        for ranks, label in [
            (content_rank, "content"),
            (summary_rank, "comment_summary"),
            (topic_rank, "topic"),
        ]:
            for vid, score_val in ranks.items():
                fused[vid] = fused.get(vid, 0.0) + score_val
                signals.setdefault(vid, []).append(label)

        if not fused:
            return _empty_result(
                config,
                theme=theme,
                query_text=ctx["query_text"],
                k=ctx["k"],
                index_size=ctx["index_size"],
                min_score=ctx["min_score"],
                top_n=ctx["top_n"],
                max_observed=None,
                degraded_scan=ctx["degraded_scan"],
            )

        top_ids = sorted(fused, key=lambda x: fused[x], reverse=True)[: ctx["top_n"]]
        hydrated = {
            r["video_id"]: _safe_dict(r)
            for r in session.run(_UNIFIED_HYDRATE, video_ids=top_ids)
        }

    results: List[Dict[str, Any]] = []
    for vid in top_ids:
        if vid not in hydrated:
            continue
        row = hydrated[vid]
        row["platform"] = PLATFORM
        row["fused_score"] = round(fused[vid], 5)
        row["matched_signals"] = signals[vid]
        row["explanation"] = {
            "fused_score": row["fused_score"],
            "matched_signals": signals[vid],
            "score_breakdown": {
                "content_rrf": content_rank.get(vid),
                "summary_rrf": summary_rank.get(vid),
                "topic_rrf": topic_rank.get(vid),
            },
        }
        results.append(row)

    summary = (
        f"Fused YouTube search for '{theme}': "
        f"{len(results)} videos across content+comment_summary+topic signals."
    )
    return RetrieverResult(
        retriever=config.name,
        platform=PLATFORM,
        signal="fused",
        family=config.family,
        theme=theme,
        query_text=ctx["query_text"],
        k=ctx["k"],
        k_fraction=ctx["k_fraction"],
        index_size=ctx["index_size"],
        min_score=ctx["min_score"],
        top_n=ctx["top_n"],
        results=results,
        candidate_keys={"video_ids": [r["video_id"] for r in results]},
        sample_size=len(results),
        status="ok" if results else "empty",
        summary=summary,
        degraded_scan=ctx["degraded_scan"],
    )


# ── Public registry ──────────────────────────────────────────────────────────


def build_configs() -> List[RetrieverConfig]:
    """All 13 YouTube retrievers in a single registry, ready for the agent."""
    return [
        RetrieverConfig(
            name="youtube.top_creators",
            description=(
                "Rank YouTube creators whose audiences discuss the theme in "
                "comments (comment-topic signal). Best for: 'which creators "
                "have audiences talking about X?' (quality / relevance)."
            ),
            platform=PLATFORM,
            signal="topic",
            family="topic",
            index_name=TOPIC_INDEX,
            is_count=False,
            output_kind="creators",
            keywords=("creator", "channel", "influencer", "youtube"),
            defaults={"top_n": MEDIA_RETRIEVER_TOP_N},
            runner=_run_top_creators,
        ),
        RetrieverConfig(
            name="youtube.example_videos",
            description=(
                "Example YouTube videos whose comment topics match the theme. "
                "Best for: 'show me videos where commenters discuss X' (evidence)."
            ),
            platform=PLATFORM,
            signal="topic",
            family="topic",
            index_name=TOPIC_INDEX,
            is_count=False,
            output_kind="videos",
            keywords=("video", "example", "show", "youtube"),
            defaults={"top_n": MEDIA_RETRIEVER_TOP_N},
            runner=_run_example_videos,
        ),
        RetrieverConfig(
            name="youtube.comment_discussions",
            description=(
                "YouTube videos whose comment-section SUMMARY is semantically "
                "similar to the theme. Best for: 'whose comment section discusses X?'"
            ),
            platform=PLATFORM,
            signal="comment_summary",
            family="comment_summary",
            index_name=SUMMARY_INDEX,
            is_count=False,
            output_kind="videos",
            keywords=("comment", "discussion", "summary"),
            defaults={"top_n": MEDIA_RETRIEVER_TOP_N},
            runner=_run_comment_discussions,
        ),
        RetrieverConfig(
            name="youtube.content_videos",
            description=(
                "YouTube videos whose on-video content (title, description, "
                "thumbnail text/keywords, tags) matches the theme. Best for: "
                "'which videos are about / show X?'"
            ),
            platform=PLATFORM,
            signal="content",
            family="content",
            index_name=CONTENT_INDEX,
            is_count=False,
            output_kind="videos",
            keywords=("video about", "content", "show me", "videos"),
            defaults={"top_n": MEDIA_RETRIEVER_TOP_N},
            runner=_run_content_videos,
        ),
        RetrieverConfig(
            name="youtube.content_top_creators",
            description=(
                "Rank YouTube creators by how much their PUBLISHED videos "
                "match the theme. Best for: 'which creators make content about X?'"
            ),
            platform=PLATFORM,
            signal="content",
            family="content",
            index_name=CONTENT_INDEX,
            is_count=False,
            output_kind="creators",
            keywords=("creator", "channel", "makes content", "produces"),
            defaults={"top_n": MEDIA_RETRIEVER_TOP_N},
            runner=_run_content_top_creators,
        ),
        RetrieverConfig(
            name="youtube.top_videos_by_topic_engagement",
            description=(
                "Rank YouTube videos by topic match × log(comment_count). Best for: "
                "'most popular videos where people discuss X in comments'."
            ),
            platform=PLATFORM,
            signal="topic",
            family="topic",
            index_name=TOPIC_INDEX,
            is_count=False,
            output_kind="videos",
            keywords=("popular", "most discussed", "engagement"),
            defaults={"top_n": MEDIA_RETRIEVER_TOP_N},
            runner=_run_top_videos_by_topic_engagement,
        ),
        RetrieverConfig(
            name="youtube.top_creators_by_topic_engagement",
            description=(
                "Rank YouTube creators by summed per-video engagement (topic "
                "strength × log comments). Best for: 'which popular creators have "
                "the biggest audience discussions about X?'"
            ),
            platform=PLATFORM,
            signal="topic",
            family="topic",
            index_name=TOPIC_INDEX,
            is_count=False,
            output_kind="creators",
            keywords=("popular creators", "engagement", "biggest discussion"),
            defaults={"top_n": MEDIA_RETRIEVER_TOP_N},
            runner=_run_top_creators_by_topic_engagement,
        ),
        RetrieverConfig(
            name="youtube.count_creators_by_topic",
            description=(
                "Count distinct YouTube creators whose comment topics match "
                "the theme. Best for: 'how many creators talk about X in comments?'"
            ),
            platform=PLATFORM,
            signal="topic",
            family="topic",
            index_name=TOPIC_INDEX,
            is_count=True,
            output_kind="count_creators",
            keywords=("how many creators", "count creators"),
            defaults={},
            runner=_run_count_creators_by_topic,
        ),
        RetrieverConfig(
            name="youtube.count_creators_by_content",
            description=(
                "Count distinct YouTube creators whose video content matches "
                "the theme. Best for: 'how many creators make content about X?'"
            ),
            platform=PLATFORM,
            signal="content",
            family="content",
            index_name=CONTENT_INDEX,
            is_count=True,
            output_kind="count_creators",
            keywords=("how many creators make", "count content creators"),
            defaults={},
            runner=_run_count_creators_by_content,
        ),
        RetrieverConfig(
            name="youtube.count_videos_by_topic",
            description=(
                "Count distinct YouTube videos with comment-topic matches above "
                "threshold. Best for: 'how many videos discuss X in comment topics?'"
            ),
            platform=PLATFORM,
            signal="topic",
            family="topic",
            index_name=TOPIC_INDEX,
            is_count=True,
            output_kind="count_videos",
            keywords=("how many videos", "count videos"),
            defaults={},
            runner=_run_count_videos_by_topic,
        ),
        RetrieverConfig(
            name="youtube.count_videos_by_comment_summary",
            description=(
                "Count distinct YouTube videos whose comment-section summary "
                "matches the theme. Best for: 'how many videos have comment "
                "sections that discuss X?'"
            ),
            platform=PLATFORM,
            signal="comment_summary",
            family="comment_summary",
            index_name=SUMMARY_INDEX,
            is_count=True,
            output_kind="count_videos",
            keywords=("how many videos comments", "comment sections discussing"),
            defaults={},
            runner=_run_count_videos_by_comment_summary,
        ),
        RetrieverConfig(
            name="youtube.count_videos_by_content",
            description=(
                "Count distinct YouTube videos whose on-video content matches "
                "the theme. Best for: 'how many videos are about / show X?'"
            ),
            platform=PLATFORM,
            signal="content",
            family="content",
            index_name=CONTENT_INDEX,
            is_count=True,
            output_kind="count_videos",
            keywords=("how many videos about", "videos showing"),
            defaults={},
            runner=_run_count_videos_by_content,
        ),
        RetrieverConfig(
            name="youtube.unified_search",
            description=(
                "Fuse YouTube hits across content, comment-summary, and topic "
                "indexes using Reciprocal Rank Fusion. Best for ambiguous queries."
            ),
            platform=PLATFORM,
            signal="fused",
            family="content",
            index_name=CONTENT_INDEX,
            is_count=False,
            output_kind="videos",
            keywords=("fused", "all signals", "best match"),
            defaults={"top_n": MEDIA_RETRIEVER_TOP_N},
            runner=_run_unified_search,
        ),
    ]
