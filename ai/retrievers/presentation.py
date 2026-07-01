"""Research-oriented presentation layer for media retrieval results.

Enriches raw retriever rows with matched topics, ``why_retrieved`` text,
multi-paragraph summaries, and a lightweight retrieval trace suitable for
researchers validating relevance — without extra LLM calls.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .base import (
    MEDIA_RETRIEVER_K_FLOOR,
    MEDIA_RETRIEVER_TOP_N,
    get_media_retriever_min_score,
    is_valid_media_theme,
)

if TYPE_CHECKING:
    from .base import RetrieverConfig
    from .hybrid_handler import HybridMediaResult
    from .media_retrieval_agent import MediaRetrievalResult

SIGNAL_LABELS: Dict[str, str] = {
    "topic": "audience discussion topics",
    "comment_summary": "comment-section summaries",
    "content": "video content text",
    "fused": "fused multi-signal retrieval",
}

# Max rows shown in the narrative summary (full data remains in result cards).
SUMMARY_EXAMPLE_LIMIT = 5

RESEARCH_NOTES: List[str] = [
    "Results reflect semantic similarity over indexed media text, not exact keyword matches.",
    "Topic-based retrievers use audience discussion topics linked to videos via HAS_COMMENT_TOPIC.",
    "Some creators may discuss a theme indirectly (reactions, streaming culture, adjacent topics).",
    "Lower similarity thresholds include broader matches; raise min_score for stricter results.",
]

SIGNAL_RESEARCH_NOTES: Dict[str, List[str]] = {
    "topic": [
        "Topic matches use YouTubeCommentTopic / TikTokCommentTopic nodes linked to videos.",
    ],
    "comment_summary": [
        "Comment-summary matches use AI-generated summaries of all comments on a video, "
        "not individual comment text.",
    ],
    "content": [
        "Content matches use creator-side video metadata (title, description, thumbnail text, tags).",
    ],
}

EVIDENCE_LABELS: Dict[str, str] = {
    "topic": "Audience discussion topics",
    "comment_summary": "Comment-section summary",
    "content": "Video content excerpt",
    "fused": "Multi-signal fusion",
}

# Per-retriever presentation metadata (keyed by suffix after youtube./tiktok./all.)
RETRIEVER_SUFFIX_PROFILES: Dict[str, Dict[str, Any]] = {
    "top_creators": {
        "output": "creators",
        "ranking_label": "Topic relevance",
        "ranking_field": "relevance",
        "ranking_detail": (
            "Sum of (semantic similarity × HAS_COMMENT_TOPIC weight) across all "
            "matching videos per creator."
        ),
        "trace_ranking": (
            "Creators ranked by summed weighted topic strength across their videos "
            "whose comment topics matched the theme."
        ),
    },
    "example_videos": {
        "output": "videos",
        "ranking_label": "Topic relevance",
        "ranking_field": "relevance",
        "ranking_detail": (
            "Best weighted comment-topic match per video: "
            "max(similarity × topic weight)."
        ),
        "trace_ranking": "Videos ranked by strongest weighted comment-topic match.",
    },
    "comment_discussions": {
        "output": "videos",
        "ranking_label": "Semantic similarity",
        "ranking_field": "score",
        "ranking_detail": (
            "Cosine similarity between the query embedding and the video's "
            "comment-section summary embedding."
        ),
        "trace_ranking": "Videos ranked by comment-summary semantic similarity.",
    },
    "content_videos": {
        "output": "videos",
        "ranking_label": "Semantic similarity",
        "ranking_field": "score",
        "ranking_detail": (
            "Cosine similarity between the query embedding and the video content "
            "embedding (title, description, thumbnail text, tags)."
        ),
        "trace_ranking": "Videos ranked by on-video content semantic similarity.",
    },
    "content_top_creators": {
        "output": "creators",
        "ranking_label": "Content relevance",
        "ranking_field": "relevance",
        "ranking_detail": (
            "Sum of content-embedding similarity scores across matching videos per creator."
        ),
        "trace_ranking": "Creators ranked by aggregated content similarity across their videos.",
    },
    "top_videos_by_topic_engagement": {
        "output": "videos",
        "ranking_label": "Engagement score",
        "ranking_field": "engagement_score",
        "is_engagement": True,
        "ranking_detail": (
            "engagement_score = max(topic_strength) × log(1 + comment_count), where "
            "topic_strength = semantic similarity × HAS_COMMENT_TOPIC weight. "
            "Videos with more comments and stronger topic matches rank higher."
        ),
        "trace_ranking": (
            "Videos ranked by engagement_score = topic_strength × log(1 + comment_count). "
            "This combines how well comment topics match the theme with how much "
            "discussion the video received."
        ),
        "research_notes": [
            "Engagement ranking is NOT raw view count — it uses comment_count via "
            "log(1 + comments) multiplied by topic match strength.",
        ],
    },
    "top_creators_by_topic_engagement": {
        "output": "creators",
        "ranking_label": "Engagement score",
        "ranking_field": "engagement_score",
        "is_engagement": True,
        "ranking_detail": (
            "Sum of per-video engagement scores across a creator's matching videos: "
            "each video contributes topic_strength × log(1 + comment_count)."
        ),
        "trace_ranking": (
            "Creators ranked by summed engagement across videos whose comment topics "
            "matched the theme."
        ),
        "research_notes": [
            "Creator engagement aggregates per-video topic_strength × log(comments) "
            "across all theme-matching videos.",
        ],
    },
    "count_creators_by_topic": {
        "output": "count",
        "ranking_label": "Count",
        "ranking_field": "count",
        "ranking_detail": "Distinct creators linked to semantically matching comment topics.",
        "trace_ranking": "Count of distinct creators with at least one matching comment topic.",
    },
    "count_creators_by_content": {
        "output": "count",
        "ranking_label": "Count",
        "ranking_field": "count",
        "ranking_detail": "Distinct creators with at least one content-matching video.",
        "trace_ranking": "Count of distinct creators whose video content matched the theme.",
    },
    "count_videos_by_topic": {
        "output": "count",
        "ranking_label": "Count",
        "ranking_field": "count",
        "ranking_detail": "Distinct videos linked to semantically matching comment topics.",
        "trace_ranking": "Count of distinct videos with matching comment topics.",
    },
    "count_videos_by_comment_summary": {
        "output": "count",
        "ranking_label": "Count",
        "ranking_field": "count",
        "ranking_detail": "Distinct videos whose comment-summary embedding matched the theme.",
        "trace_ranking": "Count of distinct videos with matching comment-section summaries.",
    },
    "count_videos_by_content": {
        "output": "count",
        "ranking_label": "Count",
        "ranking_field": "count",
        "ranking_detail": "Distinct videos whose content embedding matched the theme.",
        "trace_ranking": "Count of distinct videos with matching on-video content.",
    },
    "unified_search": {
        "output": "videos",
        "ranking_label": "Fused RRF score",
        "ranking_field": "fused_score",
        "is_fused": True,
        "ranking_detail": (
            "Reciprocal Rank Fusion across content, comment-summary, and topic vector "
            "searches — videos matching multiple signals rank higher."
        ),
        "trace_ranking": (
            "Videos ranked by RRF fusion of content + comment_summary + topic signals."
        ),
        "research_notes": [
            "Unified search combines three embedding indexes; matched_signals shows "
            "which signals contributed.",
        ],
    },
}

_DEFAULT_RETRIEVER_PROFILE: Dict[str, Any] = {
    "output": "unknown",
    "ranking_label": "Relevance",
    "ranking_field": "relevance",
    "ranking_detail": "Ranked by retriever-specific semantic scoring.",
    "trace_ranking": "Results ranked by the selected retriever's scoring function.",
}


def retriever_suffix(retriever_name: Optional[str]) -> str:
    if not retriever_name:
        return ""
    if "." in retriever_name:
        return retriever_name.rsplit(".", 1)[-1]
    return retriever_name


def get_retriever_profile(retriever_name: Optional[str]) -> Dict[str, Any]:
    suffix = retriever_suffix(retriever_name)
    profile = dict(_DEFAULT_RETRIEVER_PROFILE)
    profile.update(RETRIEVER_SUFFIX_PROFILES.get(suffix, {}))
    profile["suffix"] = suffix
    profile["name"] = retriever_name or ""
    return profile


def get_retriever_research_notes(retriever_name: Optional[str], signal: str) -> List[str]:
    profile = get_retriever_profile(retriever_name)
    notes = list(RESEARCH_NOTES)
    notes.extend(SIGNAL_RESEARCH_NOTES.get(signal, []))
    notes.extend(profile.get("research_notes") or [])
    if profile.get("ranking_detail"):
        notes.append(str(profile["ranking_detail"]))
    return notes


def _dedupe_strings(items: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for raw in items:
        s = (raw or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def normalize_topics(raw: Any) -> List[str]:
    """Extract topic name strings from Cypher output (strings or dicts)."""
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            name = item.get("name") or item.get("topic")
            if name:
                out.append(str(name).strip())
    return out


def collect_topics_from_row(row: Dict[str, Any]) -> List[str]:
    """Gather all topic strings from a row (top-level, matches, accounts)."""
    topics: List[str] = []
    topics.extend(normalize_topics(row.get("matched_topics")))
    topics.extend(normalize_topics(row.get("sample_topics")))
    topics.extend(normalize_topics(row.get("matches")))
    for acc in row.get("accounts") or []:
        if isinstance(acc, dict):
            topics.extend(normalize_topics(acc.get("sample_topics")))
            topics.extend(normalize_topics(acc.get("matched_topics")))
            topics.extend(normalize_topics(acc.get("matches")))
    return _dedupe_strings(topics)


def collect_topic_match_details(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Structured topic matches with optional weight/score (from ``matches`` field)."""
    details: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in row.get("matches") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("topic") or item.get("name")
        if not name:
            continue
        key = str(name).lower()
        if key in seen:
            continue
        seen.add(key)
        details.append(
            {
                "topic": str(name),
                "weight": item.get("weight"),
                "score": item.get("score"),
            }
        )
    for name in collect_topics_from_row(row):
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        details.append({"topic": name})
    return details


def _score_breakdown_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    expl = row.get("explanation")
    if isinstance(expl, dict) and expl.get("score_breakdown"):
        return dict(expl["score_breakdown"])
    breakdown: Dict[str, Any] = {}
    for key in (
        "best_topic_strength",
        "log_comments",
        "engagement_score",
        "comment_count",
        "total_comment_count",
        "max_video_engagement",
        "score",
        "relevance",
        "fused_score",
        "follower_count",
        "content_rrf",
        "summary_rrf",
        "topic_rrf",
    ):
        if row.get(key) is not None:
            breakdown[key] = row.get(key)
    return breakdown


def apply_ranking_metadata(
    row: Dict[str, Any], profile: Dict[str, Any]
) -> Dict[str, Any]:
    """Attach ranking_label/value and score_breakdown for the UI."""
    out = dict(row)
    rank_field = profile.get("ranking_field") or "relevance"
    rank_value = out.get(rank_field)
    if rank_value is None:
        rank_value = out.get("relevance") or out.get("score") or out.get("engagement_score")
    out["ranking_label"] = profile.get("ranking_label") or "Relevance"
    out["ranking_value"] = rank_value
    out["score_breakdown"] = _score_breakdown_from_row(out)
    out["retriever_method"] = profile.get("ranking_detail") or profile.get("trace_ranking")
    if profile.get("is_engagement") and rank_value is not None:
        out["relevance"] = rank_value
    return out


def collect_sample_videos(
    row: Dict[str, Any], *, limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Merge sample videos from row and nested accounts (no cap unless limit set)."""
    videos: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def _add(batch: Any) -> None:
        if not isinstance(batch, list):
            return
        for v in batch:
            if not isinstance(v, dict):
                continue
            key = str(v.get("video_id") or v.get("url") or v.get("title") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            videos.append(v)
            if limit is not None and len(videos) >= limit:
                return

    _add(row.get("sample_videos"))
    for acc in row.get("accounts") or []:
        if isinstance(acc, dict):
            _add(acc.get("sample_videos"))
        if limit is not None and len(videos) >= limit:
            break
    return videos if limit is None else videos[:limit]


def collect_platforms(row: Dict[str, Any]) -> List[str]:
    platforms: List[str] = []
    if row.get("platform"):
        platforms.append(str(row["platform"]))
    for acc in row.get("accounts") or []:
        if isinstance(acc, dict) and acc.get("platform"):
            p = str(acc["platform"])
            if p not in platforms:
                platforms.append(p)
    return platforms


def evidence_snippet(row: Dict[str, Any], signal: str) -> str:
    """Return the best human-readable evidence string for a row."""
    if signal == "comment_summary":
        return " ".join(str(row.get("comment_summary_description") or "").split())
    if signal == "content":
        for key in (
            "video_description",
            "thumbnail_description",
            "video_title",
            "title",
        ):
            val = row.get(key)
            if val:
                return " ".join(str(val).split())
        keywords = row.get("thumbnail_keywords") or row.get("tags")
        if isinstance(keywords, list) and keywords:
            return ", ".join(str(k) for k in keywords)
    topics = collect_topics_from_row(row)
    if topics:
        return ", ".join(topics)
    return ""


def build_why_retrieved(
    *,
    signal: str,
    theme: str,
    topics: List[str],
    row: Optional[Dict[str, Any]] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> str:
    profile = profile or _DEFAULT_RETRIEVER_PROFILE
    signal_label = SIGNAL_LABELS.get(signal, signal.replace("_", " "))

    if profile.get("is_engagement") and row:
        bts = row.get("best_topic_strength")
        lc = row.get("log_comments")
        cc = row.get("comment_count")
        es = row.get("engagement_score") or row.get("relevance")
        topic_names = topics or collect_topics_from_row(row)
        parts = [
            "Ranked by engagement: topic match strength",
        ]
        if bts is not None:
            parts.append(f"({float(bts):.2f})")
        parts.append("× log(1 + comments)")
        if lc is not None:
            parts.append(f"({float(lc):.2f})")
        if cc is not None:
            parts.append(f"from {int(cc)} comments")
        if es is not None:
            parts.append(f"= engagement score {float(es):.2f}.")
        else:
            parts.append(".")
        if topic_names:
            parts.append(f" Matching comment topics: {', '.join(topic_names)}.")
        return " ".join(parts)

    if profile.get("is_fused") and row:
        signals = row.get("matched_signals") or []
        fs = row.get("fused_score") or row.get("relevance")
        base = (
            f"Retrieved via fused search across content, comment-summary, and topic indexes "
            f"for '{theme}'."
        )
        if signals:
            base += f" Matched signals: {', '.join(str(s) for s in signals)}."
        if fs is not None:
            base += f" Fused RRF score: {float(fs):.3f}."
        return base

    if signal == "comment_summary":
        base = (
            f"Retrieved because the video's comment-section summary semantically "
            f"matched '{theme}'."
        )
    elif signal == "content":
        base = (
            f"Retrieved because the video's on-platform content text semantically "
            f"matched '{theme}'."
        )
    elif profile.get("suffix") == "example_videos":
        base = (
            f"Retrieved because comment topics on this video matched '{theme}' "
            f"(weighted by topic strength)."
        )
    elif profile.get("suffix") == "top_creators":
        base = (
            f"Retrieved because this creator's videos have comment topics matching "
            f"'{theme}' (summed weighted relevance)."
        )
    else:
        base = (
            f"Retrieved because {signal_label} matched the theme "
            f"'{theme}' via semantic vector search."
        )

    snippet = evidence_snippet(row, signal) if row else ""
    if snippet and signal != "topic":
        return f"{base} Evidence: {snippet}"
    if topics:
        return f"{base} Matching topics: {', '.join(topics)}."
    if snippet:
        return f"{base} Evidence: {snippet}."
    return base


def _tiktok_username_from_row(row: Dict[str, Any]) -> Optional[str]:
    for key in ("username", "tiktok_username", "channel_username", "creator", "creator_name"):
        val = row.get(key)
        if isinstance(val, str):
            cleaned = val.strip().lstrip("@")
            if cleaned:
                return cleaned
    return None


def _looks_like_tiktok_row(row: Dict[str, Any], video_id: str) -> bool:
    platform = str(row.get("platform") or "").lower()
    if platform == "tiktok":
        return True
    channel_id = row.get("channel_id")
    if isinstance(channel_id, str) and channel_id.startswith("UC"):
        return False
    return video_id.isdigit() and len(video_id) >= 15


def resolve_video_url(row: Dict[str, Any]) -> Optional[str]:
    """Return a watch URL, synthesizing TikTok links when the graph omitted video_url."""
    for key in ("url", "video_url"):
        val = row.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    raw_id = row.get("video_id")
    if raw_id is None:
        return None
    video_id = str(raw_id).strip()
    if not video_id:
        return None

    if _looks_like_tiktok_row(row, video_id):
        username = _tiktok_username_from_row(row)
        if username:
            return f"https://www.tiktok.com/@{username}/video/{video_id}"
        if video_id.isdigit():
            return f"https://www.tiktok.com/video/{video_id}"

    platform = str(row.get("platform") or "").lower()
    if platform == "youtube" or re.fullmatch(r"[\w-]{11}", video_id):
        return f"https://www.youtube.com/watch?v={video_id}"

    return None


def apply_video_url_fallback(row: Dict[str, Any]) -> Dict[str, Any]:
    """Fill ``url`` / ``video_url`` on a video row when only username + video_id exist."""
    resolved = resolve_video_url(row)
    if not resolved:
        return row
    out = dict(row)
    out["url"] = resolved
    out["video_url"] = resolved
    return out


def enrich_creator_row(
    row: Dict[str, Any],
    *,
    signal: str,
    theme: str,
    retriever_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Add matched_topics, why_retrieved, platforms, merged sample_videos."""
    profile = get_retriever_profile(retriever_name)
    out = apply_ranking_metadata(dict(row), profile)
    topics = collect_topics_from_row(out)
    out["matched_topics"] = topics
    out["matched_topic_details"] = collect_topic_match_details(out)
    out["platforms"] = collect_platforms(out)
    out["sample_videos"] = collect_sample_videos(out)
    out["why_retrieved"] = build_why_retrieved(
        signal=signal,
        theme=theme,
        topics=topics,
        row=out,
        profile=profile,
    )
    if out.get("explanation") is None:
        out["explanation"] = {}
    if isinstance(out["explanation"], dict):
        out["explanation"] = {
            **out["explanation"],
            "matched_topics": topics,
            "matched_topic_details": out["matched_topic_details"],
            "why_retrieved": out["why_retrieved"],
            "score_breakdown": out["score_breakdown"],
        }
    return out


def enrich_creator_results(
    rows: List[Dict[str, Any]],
    *,
    signal: str,
    theme: str,
    retriever_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    return [
        enrich_creator_row(r, signal=signal, theme=theme, retriever_name=retriever_name)
        for r in rows
    ]


def enrich_video_row(
    row: Dict[str, Any],
    *,
    signal: str,
    theme: str,
    retriever_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Add relevance, evidence snippet, topics, and why_retrieved for video rows."""
    profile = get_retriever_profile(retriever_name)
    out = apply_ranking_metadata(dict(row), profile)
    if out.get("relevance") is None and out.get("score") is not None:
        out["relevance"] = out.get("score")
    out["platforms"] = collect_platforms(out) or (
        [str(out["platform"])] if out.get("platform") else []
    )
    topics = collect_topics_from_row(out)
    out["matched_topics"] = topics
    out["matched_topic_details"] = collect_topic_match_details(out)
    out["evidence_snippet"] = evidence_snippet(out, signal)
    out["why_retrieved"] = build_why_retrieved(
        signal=signal,
        theme=theme,
        topics=topics,
        row=out,
        profile=profile,
    )
    if out.get("explanation") is None:
        out["explanation"] = {}
    if isinstance(out["explanation"], dict):
        out["explanation"] = {
            **out["explanation"],
            "matched_topics": topics,
            "matched_topic_details": out["matched_topic_details"],
            "evidence_snippet": out["evidence_snippet"],
            "why_retrieved": out["why_retrieved"],
            "score_breakdown": out["score_breakdown"],
        }
    return apply_video_url_fallback(out)


def enrich_video_results(
    rows: List[Dict[str, Any]],
    *,
    signal: str,
    theme: str,
    retriever_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    return [
        enrich_video_row(r, signal=signal, theme=theme, retriever_name=retriever_name)
        for r in rows
    ]


def _normalize_hybrid_stage2_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map Stage 2 Cypher aliases to the media-retrieval row shape the UI expects."""
    out = dict(row)
    out["title"] = out.get("title") or out.get("video_title")
    out["url"] = out.get("url") or out.get("video_url")
    out["creator"] = (
        out.get("creator")
        or out.get("creator_name")
        or out.get("channel_title")
        or out.get("username")
        or out.get("channel_username")
        or out.get("tiktok_username")
    )
    out["channel_id"] = (
        out.get("channel_id")
        or out.get("creator_id")
        or out.get("account_id")
    )
    if not out.get("username"):
        out["username"] = out.get("tiktok_username") or out.get("channel_username")
    if not out.get("influencer_name") and out.get("creator_name"):
        out["influencer_name"] = out.get("creator_name")
    platform = out.get("platform")
    if isinstance(platform, str):
        out["platform"] = platform.lower()
    elif out.get("channel_id") and str(out["channel_id"]).startswith("UC"):
        out["platform"] = "youtube"
    return apply_video_url_fallback(out)


def _stage1_row_dedupe_key(row: Dict[str, Any]) -> str:
    """Dedupe Stage 1 rows by video_id so hybrid merge keeps every video, not one per channel."""
    video_id = row.get("video_id")
    if video_id is not None and str(video_id):
        return f"video:{video_id}"
    for key in (
        "channel_id",
        "username",
        "creator",
        "creator_name",
        "influencer_name",
    ):
        val = row.get(key)
        if val:
            return f"account:{val}"
    return f"row:{id(row)}"


def _flatten_stage1_index_rows(
    stage1_results: List[Dict[str, Any]],
    per_platform: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Flatten merged Stage 1 rows, per-platform results, and nested accounts."""
    flat: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def _append(row: Dict[str, Any]) -> None:
        if not row:
            return
        dedupe_key = _stage1_row_dedupe_key(row)
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        flat.append(row)

    for row in stage1_results:
        if not isinstance(row, dict):
            continue
        _append(row)
        for acc in row.get("accounts") or []:
            if not isinstance(acc, dict):
                continue
            merged = dict(row)
            merged.update(acc)
            _append(merged)

    for plat_data in (per_platform or {}).values():
        if not isinstance(plat_data, dict):
            continue
        for row in plat_data.get("results") or []:
            if isinstance(row, dict):
                _append(row)

    return flat


def _index_stage1_results(
    stage1_results: List[Dict[str, Any]],
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Index Stage 1 preview rows by video_id and account id for hybrid merge."""
    by_video: Dict[str, Dict[str, Any]] = {}
    by_account: Dict[str, Dict[str, Any]] = {}
    for row in stage1_results:
        video_id = row.get("video_id")
        if video_id is not None:
            by_video[str(video_id)] = row
        for key in (
            "channel_id",
            "username",
            "creator",
            "creator_name",
            "influencer_name",
            "channel_title",
            "channel_username",
            "tiktok_username",
            "account_id",
        ):
            val = row.get(key)
            if val:
                by_account[str(val)] = row
    return by_video, by_account


def _needs_hybrid_semantic_hydration(row: Dict[str, Any]) -> bool:
    if row.get("relevance") is not None or row.get("score") is not None:
        return False
    return not collect_sample_videos(row)


def _resolve_youtube_creator_config(retriever_name: Optional[str]):
    from .youtube import build_configs

    base = _hybrid_stage1_retriever_name(retriever_name)
    if base.startswith("all."):
        base = "youtube." + base[len("all.") :]
    configs = {c.name: c for c in build_configs()}
    return configs.get(base) or configs.get("youtube.content_top_creators")


def _resolve_tiktok_creator_config(retriever_name: Optional[str]):
    from .tiktok import build_configs

    base = _hybrid_stage1_retriever_name(retriever_name)
    if base.startswith("all."):
        base = "tiktok." + base[len("all.") :]
    configs = {c.name: c for c in build_configs()}
    return configs.get(base) or configs.get("tiktok.content_top_creators")


def _fetch_hybrid_semantic_metadata(
    *,
    theme: str,
    retriever_name: Optional[str],
    min_score: Optional[float],
    youtube_channel_ids: List[str],
    tiktok_usernames: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Load semantic scores/sample videos for Stage 2 rows missing Stage 1 rows."""
    index: Dict[str, Dict[str, Any]] = {}
    if youtube_channel_ids:
        from .youtube import fetch_creator_rows_for_channel_ids

        cfg = _resolve_youtube_creator_config(retriever_name)
        if cfg:
            for row in fetch_creator_rows_for_channel_ids(
                cfg,
                theme,
                youtube_channel_ids,
                min_score=min_score,
            ):
                cid = row.get("channel_id")
                if cid:
                    index[f"yt:{cid}"] = row
    if tiktok_usernames:
        from .tiktok import fetch_creator_rows_for_usernames

        cfg = _resolve_tiktok_creator_config(retriever_name)
        if cfg:
            for row in fetch_creator_rows_for_usernames(
                cfg,
                theme,
                tiktok_usernames,
                min_score=min_score,
            ):
                uname = row.get("username")
                if uname:
                    index[f"tt:{uname}"] = row
    return index


def _merge_hybrid_stage1_seed(
    base: Dict[str, Any],
    *,
    by_video: Dict[str, Dict[str, Any]],
    by_account: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Overlay Stage 2 structural fields onto the full Stage 1 semantic row."""
    base = _normalize_hybrid_stage2_row(base)
    video_id = base.get("video_id")
    if video_id is not None and str(video_id) in by_video:
        merged = dict(by_video[str(video_id)])
        for key, value in base.items():
            if value is not None and value != "":
                merged[key] = value
        return _normalize_hybrid_stage2_row(merged)

    # Creator-only Stage 2 rows (no video_id) may still join via account identifiers.
    if video_id is None:
        for lookup in (
            base.get("channel_id"),
            base.get("creator_id"),
            base.get("account_id"),
            base.get("username"),
            base.get("creator"),
            base.get("creator_name"),
            base.get("influencer_name"),
        ):
            if lookup and str(lookup) in by_account:
                merged = dict(by_account[str(lookup)])
                for key, value in base.items():
                    if value is not None and value != "":
                        merged[key] = value
                return _normalize_hybrid_stage2_row(merged)
    return base


def _resolve_youtube_video_config(
    retriever_name: Optional[str],
    signal: str,
):
    from .youtube import build_configs

    configs = {c.name: c for c in build_configs()}
    base = _hybrid_stage1_retriever_name(retriever_name)
    if base.startswith("all."):
        base = "youtube." + base[len("all.") :]
    cfg = configs.get(base)
    if cfg and cfg.output_kind in {"videos", "count_videos"}:
        return cfg
    if signal == "content":
        return configs.get("youtube.content_videos")
    if signal == "comment_summary":
        return configs.get("youtube.comment_discussions")
    return configs.get("youtube.example_videos")


def _resolve_tiktok_video_config(
    retriever_name: Optional[str],
    signal: str,
):
    from .tiktok import build_configs

    configs = {c.name: c for c in build_configs()}
    base = _hybrid_stage1_retriever_name(retriever_name)
    if base.startswith("all."):
        base = "tiktok." + base[len("all.") :]
    cfg = configs.get(base)
    if cfg and cfg.output_kind in {"videos", "count_videos"}:
        return cfg
    if signal == "content":
        return configs.get("tiktok.content_videos")
    if signal == "comment_summary":
        return configs.get("tiktok.comment_discussions")
    return configs.get("tiktok.example_videos")


def _overlay_hybrid_video_db_row(
    base: Dict[str, Any],
    seed: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge Neo4j per-video fields onto a Stage 2 row; keep Stage 1 scores when present."""
    merged = _normalize_hybrid_stage2_row({**seed, **base})
    for key in (
        "comment_summary_description",
        "video_description",
        "thumbnail_description",
        "thumbnail_keywords",
        "tags",
    ):
        if seed.get(key):
            merged[key] = seed[key]
    if base.get("relevance") is not None:
        merged["relevance"] = base["relevance"]
        merged["score"] = base.get("score", base["relevance"])
    elif seed.get("relevance") is not None:
        merged["relevance"] = seed["relevance"]
        merged["score"] = seed.get("score", seed["relevance"])
    return _normalize_hybrid_stage2_row(merged)


def _fetch_hybrid_video_metadata_by_ids(
    *,
    theme: str,
    signal: str,
    retriever_name: Optional[str],
    min_score: Optional[float],
    youtube_video_ids: List[str],
    tiktok_video_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Load each video's own comment/content fields from Neo4j (not channel-level aggregates)."""
    index: Dict[str, Dict[str, Any]] = {}
    yt_ids = list(dict.fromkeys(str(v) for v in youtube_video_ids if v))
    tt_ids = list(dict.fromkeys(str(v) for v in tiktok_video_ids if v))
    if yt_ids:
        from .youtube import fetch_video_rows_for_video_ids

        cfg = _resolve_youtube_video_config(retriever_name, signal)
        if cfg:
            for vid, row in fetch_video_rows_for_video_ids(
                cfg,
                theme,
                yt_ids,
                min_score=min_score,
            ).items():
                index[f"yt:{vid}"] = row
    if tt_ids:
        from .tiktok import fetch_video_rows_for_video_ids

        cfg = _resolve_tiktok_video_config(retriever_name, signal)
        if cfg:
            for vid, row in fetch_video_rows_for_video_ids(
                cfg,
                theme,
                tt_ids,
                min_score=min_score,
            ).items():
                index[f"tt:{vid}"] = row
    return index


def enrich_hybrid_stage2_results(
    rows: List[Dict[str, Any]],
    *,
    stage1_results: List[Dict[str, Any]],
    signal: str,
    theme: str,
    retriever_name: Optional[str] = None,
    per_platform: Optional[Dict[str, Any]] = None,
    min_score: Optional[float] = None,
    question: str = "",
) -> List[Dict[str, Any]]:
    """Merge Stage 2 structural rows with Stage 1 semantic metadata for the UI."""
    if not rows or _is_count_result(rows):
        return rows

    index_rows = _flatten_stage1_index_rows(stage1_results, per_platform)
    by_video, by_account = _index_stage1_results(index_rows)
    merged_rows: List[Dict[str, Any]] = [
        _merge_hybrid_stage1_seed(row, by_video=by_video, by_account=by_account)
        for row in rows
    ]

    yt_video_ids: List[str] = []
    tt_video_ids: List[str] = []
    for base in merged_rows:
        video_id = base.get("video_id")
        if video_id is None:
            continue
        plat = str(base.get("platform") or "").lower()
        if plat == "tiktok":
            tt_video_ids.append(str(video_id))
        else:
            yt_video_ids.append(str(video_id))

    if yt_video_ids or tt_video_ids:
        by_video_db = _fetch_hybrid_video_metadata_by_ids(
            theme=theme,
            signal=signal,
            retriever_name=retriever_name,
            min_score=min_score,
            youtube_video_ids=yt_video_ids,
            tiktok_video_ids=tt_video_ids,
        )
        for i, base in enumerate(merged_rows):
            video_id = base.get("video_id")
            if video_id is None:
                continue
            plat = str(base.get("platform") or "").lower()
            key = (
                f"tt:{video_id}"
                if plat == "tiktok"
                else f"yt:{video_id}"
            )
            seed = by_video_db.get(key)
            if seed:
                merged_rows[i] = _overlay_hybrid_video_db_row(base, seed)

    missing_yt: List[str] = []
    missing_tt: List[str] = []
    for base in merged_rows:
        if base.get("video_id") is not None:
            continue
        if not _needs_hybrid_semantic_hydration(base):
            continue
        plat = str(base.get("platform") or "").lower()
        cid = base.get("channel_id")
        uname = base.get("username") or base.get("tiktok_username")
        if plat == "tiktok" and uname:
            missing_tt.append(str(uname))
        elif cid:
            missing_yt.append(str(cid))

    if missing_yt or missing_tt:
        hydrated = _fetch_hybrid_semantic_metadata(
            theme=theme,
            retriever_name=retriever_name,
            min_score=min_score,
            youtube_channel_ids=list(dict.fromkeys(missing_yt)),
            tiktok_usernames=list(dict.fromkeys(missing_tt)),
        )
        for i, base in enumerate(merged_rows):
            if not _needs_hybrid_semantic_hydration(base):
                continue
            plat = str(base.get("platform") or "").lower()
            key = (
                f"tt:{base.get('username') or base.get('tiktok_username')}"
                if plat == "tiktok"
                else f"yt:{base.get('channel_id')}"
            )
            seed = hydrated.get(key)
            if seed:
                merged = dict(seed)
                for k, value in base.items():
                    if value is not None and value != "":
                        merged[k] = value
                merged_rows[i] = _normalize_hybrid_stage2_row(merged)

    from .hybrid_handler import question_wants_follower_ranking

    wants_rank = bool(question) and question_wants_follower_ranking(question)

    enriched: List[Dict[str, Any]] = []
    for base in merged_rows:
        if _is_video_result([base]) or base.get("video_id"):
            enriched.append(
                enrich_video_row(
                    base,
                    signal=signal,
                    theme=theme,
                    retriever_name=retriever_name,
                )
            )
        else:
            enriched.append(
                enrich_creator_row(
                    base,
                    signal=signal,
                    theme=theme,
                    retriever_name=retriever_name,
                )
            )

    if wants_rank:
        for item in enriched:
            fc = item.get("follower_count")
            if isinstance(fc, (int, float)):
                item["ranking_label"] = "Survey followers"
                item["ranking_value"] = fc
                if isinstance(item.get("score_breakdown"), dict):
                    item["score_breakdown"]["follower_count"] = fc
                elif isinstance(item.get("explanation"), dict):
                    item["explanation"] = {
                        **item["explanation"],
                        "score_breakdown": {
                            **(item["explanation"].get("score_breakdown") or {}),
                            "follower_count": fc,
                        },
                    }

    def _semantic_sort_key(item: Dict[str, Any]) -> float:
        for key in ("relevance", "score", "engagement_score", "fused_score"):
            val = item.get(key)
            if isinstance(val, (int, float)):
                return float(val)
        return -1.0

    if wants_rank:
        enriched.sort(
            key=lambda item: (
                float(item["follower_count"])
                if isinstance(item.get("follower_count"), (int, float))
                else -1.0,
                _semantic_sort_key(item),
            ),
            reverse=True,
        )
    else:
        enriched.sort(key=_semantic_sort_key, reverse=True)
    return enriched


def _is_count_result(rows: List[Dict[str, Any]]) -> bool:
    if not rows:
        return False
    first = rows[0]
    return "count" in first and first.get("count_field") is not None


def _is_video_result(rows: List[Dict[str, Any]]) -> bool:
    if not rows:
        return False
    first = rows[0]
    return "video_id" in first or ("title" in first and "creator" in first)


def _resolve_top_n(inputs: Optional[Dict[str, Any]]) -> int:
    raw = (inputs or {}).get("top_n")
    if raw is not None:
        try:
            parsed = int(raw)
            if parsed > 0:
                return parsed
        except (TypeError, ValueError):
            pass
    return MEDIA_RETRIEVER_TOP_N


def _ranked_shortlist_note(
    *,
    entity: str,
    top_n: int,
    platform: str,
    min_score: float,
) -> str:
    """Clarify that ranked lists are capped, not exhaustive counts."""
    if platform == "all":
        cap = (
            f"Up to {top_n} {entity} per platform (YouTube and TikTok) are retrieved "
            f"and merged into a ranked shortlist"
        )
    else:
        cap = f"Results are capped at the top {top_n} {entity}"
    return (
        f"{cap} with similarity ≥ {min_score:.2f}. "
        f"This is not a total count — more {entity} may match in the database."
    )


def build_research_summary(
    result: "MediaRetrievalResult",
    *,
    question: str,
) -> str:
    """Build a multi-paragraph research-style summary (deterministic)."""
    rows = result.raw_result or []
    theme = (result.inputs or {}).get("theme") or "?"
    signal = (result.inputs or {}).get("signal") or "topic"
    platform = result.platform or "all"
    min_score = float((result.inputs or {}).get("min_score") or get_media_retriever_min_score())
    signal_label = SIGNAL_LABELS.get(signal, signal.replace("_", " "))

    if platform == "all":
        platform_label = "YouTube and TikTok"
    else:
        platform_label = platform.title()

    if result.status == "empty" or not rows:
        return (
            f"No results matched '{theme}' on {platform_label} using {signal_label} "
            f"(similarity ≥ {min_score:.2f}). Try broadening the theme or lowering "
            "MEDIA_RETRIEVER_MIN_SCORE."
        )

    degraded_prefix = ""
    if (result.inputs or {}).get("degraded_scan"):
        degraded_prefix = (
            f"⚠ Degraded scan: index size lookup failed, so vector search used "
            f"only k={MEDIA_RETRIEVER_K_FLOOR} topics per platform instead of the "
            f"full index fraction. Results may be incomplete — retry the query.\n\n"
        )

    if _is_count_result(rows):
        total = 0
        for row in rows:
            try:
                total += int(row.get("count") or 0)
            except (TypeError, ValueError):
                pass
        entity = "creators" if "creator" in (result.retriever_name or "") else "videos"
        lines = [
            f"{total} {entity} matched '{theme}'-related {signal_label} on "
            f"{platform_label} (similarity ≥ {min_score:.2f}).",
            "",
            "Results were retrieved using semantic vector search over indexed "
            f"{signal_label}, then aggregated to {entity}.",
        ]
        samples: List[str] = []
        for row in rows:
            for s in row.get("sample") or []:
                if isinstance(s, dict):
                    name = s.get("creator") or s.get("title")
                    if name:
                        samples.append(str(name))
        if samples:
            lines.append("")
            shown = samples[:SUMMARY_EXAMPLE_LIMIT]
            sample_text = ", ".join(shown)
            if len(samples) > SUMMARY_EXAMPLE_LIMIT:
                sample_text += f", and {len(samples) - SUMMARY_EXAMPLE_LIMIT} more"
            lines.append(f"Sample matches include: {sample_text}.")
        body = "\n".join(lines)
        return f"{degraded_prefix}{body}" if degraded_prefix else body

    if _is_video_result(rows):
        profile = get_retriever_profile(result.retriever_name)
        n = len(rows)
        top_n = _resolve_top_n(result.inputs)
        rank_label = profile.get("ranking_label") or "Relevance"
        lines = [
            f"Showing the top {n} video{'s' if n != 1 else ''} matching '{theme}' on "
            f"{platform_label} using {signal_label}.",
            "",
            _ranked_shortlist_note(
                entity="videos",
                top_n=top_n,
                platform=platform,
                min_score=min_score,
            ),
            "",
            profile.get("trace_ranking")
            or f"Results ranked by {rank_label.lower()}.",
        ]
        if profile.get("ranking_detail"):
            lines.append("")
            lines.append(str(profile["ranking_detail"]))
        lines.append("")
        lines.append("Top matches:")
        for row in rows[:SUMMARY_EXAMPLE_LIMIT]:
            title = row.get("title") or "Untitled video"
            creator = row.get("creator") or "Unknown creator"
            rel = row.get("ranking_value") or row.get("relevance") or row.get("score")
            rel_text = f"{float(rel):.2f}" if rel is not None else "—"
            topics = row.get("matched_topics") or collect_topics_from_row(row)
            bullet = f"• \"{title}\" by {creator} ({rank_label.lower()} {rel_text})"
            if topics:
                bullet += f" — topics: {', '.join(topics)}"
            elif row.get("evidence_snippet") or evidence_snippet(row, signal):
                snippet = row.get("evidence_snippet") or evidence_snippet(row, signal)
                bullet += f" — {snippet}"
            lines.append(bullet)
        if len(rows) > SUMMARY_EXAMPLE_LIMIT:
            lines.append(
                f"• … and {len(rows) - SUMMARY_EXAMPLE_LIMIT} more "
                f"(see full results below)."
            )
        body = "\n".join(lines)
        return f"{degraded_prefix}{body}" if degraded_prefix else body

    # Creator-ranked results
    profile = get_retriever_profile(result.retriever_name)
    n = len(rows)
    top_n = _resolve_top_n(result.inputs)
    rank_label = profile.get("ranking_label") or "Relevance"
    all_topics: List[str] = []
    if signal == "topic":
        for row in rows:
            all_topics.extend(row.get("matched_topics") or collect_topics_from_row(row))
    recurring = [name for name, _ in Counter(all_topics).most_common(SUMMARY_EXAMPLE_LIMIT)]

    top = rows[0]

    if profile.get("is_engagement"):
        opener = (
            f"Showing the top {n} creator{'s' if n != 1 else ''} ranked by audience "
            f"discussion engagement for '{theme}' on {platform_label}."
        )
        retrieval_line = str(
            profile.get("ranking_detail") or profile.get("trace_ranking") or ""
        )
    elif signal == "comment_summary":
        opener = (
            f"Showing the top {n} creator{'s' if n != 1 else ''} whose videos have "
            f"comment sections discussing '{theme}' on {platform_label}."
        )
        retrieval_line = (
            f"Results were retrieved using semantic matching on {signal_label}."
        )
    elif signal == "content":
        opener = (
            f"Showing the top {n} creator{'s' if n != 1 else ''} whose video content "
            f"matches '{theme}' on {platform_label}."
        )
        retrieval_line = (
            f"Results were retrieved using semantic matching on {signal_label}."
        )
    else:
        opener = (
            f"Showing the top {n} creator{'s' if n != 1 else ''} whose audiences discuss "
            f"'{theme}'-related content on {platform_label}."
        )
        retrieval_line = (
            f"Results were retrieved using semantic matching on {signal_label} "
            f"associated with creator videos."
        )

    lines = [opener, ""]
    lines.append(
        _ranked_shortlist_note(
            entity="creators",
            top_n=top_n,
            platform=platform,
            min_score=min_score,
        )
    )
    if retrieval_line:
        lines.append("")
        lines.append(retrieval_line)
    if profile.get("is_engagement"):
        lines.append(
            f"Ranking metric: {rank_label} (not raw cosine similarity)."
        )
    if recurring:
        lines.append("")
        lines.append("The strongest recurring themes include:")
        for t in recurring:
            lines.append(f"• {t}")
        unique_recurring = len({name for name in all_topics})
        if unique_recurring > len(recurring):
            lines.append(
                f"• … and {unique_recurring - len(recurring)} more themes "
                f"(see full results below)."
            )
    elif signal in {"comment_summary", "content"}:
        sample_videos = collect_sample_videos(top, limit=SUMMARY_EXAMPLE_LIMIT)
        if sample_videos:
            lines.append("")
            lines.append("Example matching videos:")
            for v in sample_videos:
                title = v.get("title") or "Video"
                url = v.get("url")
                if url:
                    lines.append(f"• \"{title}\" ({url})")
                else:
                    lines.append(f"• \"{title}\"")
            total_videos = len(collect_sample_videos(top))
            if total_videos > SUMMARY_EXAMPLE_LIMIT:
                lines.append(
                    f"• … and {total_videos - SUMMARY_EXAMPLE_LIMIT} more videos "
                    f"(see full results below)."
                )
    lines.append("")
    lines.append("Top matches:")
    for row in rows[:SUMMARY_EXAMPLE_LIMIT]:
        name = row.get("influencer_name") or row.get("creator") or "Unknown"
        rel = row.get("ranking_value") or row.get("relevance") or row.get("score")
        rel_text = f"{float(rel):.2f}" if rel is not None else "—"
        video_count = row.get("video_count")
        video_part = f", {video_count} matching videos" if video_count is not None else ""
        lines.append(
            f"• {name} ({rank_label.lower()} {rel_text}{video_part})"
        )
    if len(rows) > SUMMARY_EXAMPLE_LIMIT:
        lines.append(
            f"• … and {len(rows) - SUMMARY_EXAMPLE_LIMIT} more "
            f"(see full results below)."
        )
    if result.deduped_by_influencer:
        lines.append("")
        lines.append(
            "Creators appearing on both YouTube and TikTok were merged via Influencer nodes."
        )
    body = "\n".join(lines)
    return f"{degraded_prefix}{body}" if degraded_prefix else body


def build_retrieval_trace(
    result: "MediaRetrievalResult",
    *,
    question: str,
    retriever_config: Optional["RetrieverConfig"] = None,
) -> Dict[str, Any]:
    """Lightweight step-by-step trace for researchers."""
    inputs = result.inputs or {}
    theme = inputs.get("theme") or "?"
    signal = inputs.get("signal") or "topic"
    signal_label = SIGNAL_LABELS.get(signal, signal.replace("_", " "))
    min_score = inputs.get("min_score") or get_media_retriever_min_score()
    k = inputs.get("k")
    index_size = inputs.get("index_size")
    degraded_scan = bool(inputs.get("degraded_scan"))
    query_text = inputs.get("query_text") or theme
    platform = result.platform or "all"
    embedding_model = (
        os.environ.get("MEDIA_EMBEDDING_MODEL")
        or os.environ.get("OPENAI_EMBEDDING_MODEL")
        or "text-embedding-3-large"
    )

    index_names: List[str] = []
    if retriever_config:
        index_names.append(retriever_config.index_name)
    if platform == "all" and result.per_platform:
        for plat_data in result.per_platform.values():
            if isinstance(plat_data, dict) and plat_data.get("index_size"):
                pass  # per-platform indexes differ; names from retriever names
    if platform == "all":
        search_targets = f"YouTube and TikTok {signal_label} indexes"
    else:
        search_targets = f"{platform.title()} {signal_label}"

    rows = result.raw_result or []
    is_video = _is_video_result(rows)
    profile = get_retriever_profile(result.retriever_name)
    step4_title = "Video ranking" if is_video else "Creator aggregation"
    if is_video:
        step4_detail = profile.get("trace_ranking") or (
            f"Videos whose {signal_label} exceeded min_score={min_score} were ranked "
            "by semantic similarity score."
        )
    elif result.deduped_by_influencer:
        step4_detail = (
            f"Matching {signal_label} were linked to videos and creators. "
            "Cross-platform duplicates merged via Influencer nodes."
        )
    else:
        step4_detail = (
            f"Matching {signal_label} were linked to videos and creators. "
            "Results listed per platform account."
        )

    step5_detail = profile.get("trace_ranking") or (
        "Ranked by semantic similarity score."
        if is_video
        else (
            f"Ranked by retriever '{result.retriever_name}' using weighted semantic "
            "scores and matching video counts."
        )
    )

    scan_detail = (
        f"Similarity threshold min_score={min_score}. "
        + (
            f"Vector search top-k={k} of {index_size} indexed nodes."
            if k and index_size
            else f"Vector search top-k={k} (index size unavailable)."
            if k
            else "Vector search sized as a fraction of index node count."
        )
    )
    if degraded_scan:
        scan_detail += (
            f" ⚠ DEGRADED SCAN: index size lookup failed — only k={MEDIA_RETRIEVER_K_FLOOR} "
            f"topics per platform were searched instead of the full index fraction. "
            "Retry the query; results may be incomplete."
        )

    warnings: List[str] = []
    if degraded_scan:
        warnings.append(
            f"Degraded vector scan (k={k or MEDIA_RETRIEVER_K_FLOOR} only). "
            "Index size could not be determined — results may differ from a full scan."
        )

    steps = [
        {
            "step": 1,
            "title": "Query understanding",
            "detail": (
                f"Classified as media retrieval. Theme extracted: '{theme}'. "
                f"Question: \"{question[:120]}{'...' if len(question) > 120 else ''}\""
            ),
        },
        {
            "step": 2,
            "title": "Semantic retrieval",
            "detail": (
                f"Embedded query text '{query_text}' with {embedding_model} and matched "
                f"against {search_targets}."
            ),
        },
        {
            "step": 3,
            "title": "Threshold & scan",
            "detail": scan_detail,
        },
        {
            "step": 4,
            "title": step4_title,
            "detail": step4_detail,
        },
        {
            "step": 5,
            "title": "Ranking",
            "detail": step5_detail,
        },
    ]

    return {
        "steps": steps,
        "params": {
            "retriever": result.retriever_name,
            "theme": theme,
            "query_text": query_text,
            "signal": signal,
            "platform": platform,
            "min_score": min_score,
            "k": k,
            "k_fraction": inputs.get("k_fraction"),
            "index_size": index_size,
            "top_n": inputs.get("top_n"),
            "embedding_model": embedding_model,
            "deduped_by_influencer": result.deduped_by_influencer,
            "degraded_scan": degraded_scan,
            "ranking_method": profile.get("ranking_detail"),
            "retriever_suffix": profile.get("suffix"),
        },
        "warnings": warnings,
        "research_notes": get_retriever_research_notes(result.retriever_name, signal),
    }


def present_media_result(
    result: "MediaRetrievalResult",
    *,
    question: str,
    retriever_config: Optional["RetrieverConfig"] = None,
) -> "MediaRetrievalResult":
    """Enrich rows, summary, and trace on a finished MediaRetrievalResult."""
    from .media_retrieval_agent import MediaRetrievalResult

    signal = (result.inputs or {}).get("signal") or "topic"
    theme = (result.inputs or {}).get("theme") or ""
    retriever_name = result.retriever_name or ""

    rows = list(result.raw_result or [])
    if rows and _is_video_result(rows):
        rows = enrich_video_results(
            rows, signal=signal, theme=theme, retriever_name=retriever_name
        )
    elif rows and not _is_count_result(rows):
        rows = enrich_creator_results(
            rows, signal=signal, theme=theme, retriever_name=retriever_name
        )

    # Merge retrieval params from per_platform when missing on inputs (all-platform).
    inputs = dict(result.inputs or {})
    if result.per_platform:
        for plat_data in result.per_platform.values():
            if not isinstance(plat_data, dict):
                continue
            for key in ("k", "k_fraction", "index_size", "min_score", "query_text", "degraded_scan"):
                if inputs.get(key) is None and plat_data.get(key) is not None:
                    inputs[key] = plat_data.get(key)
            break

    enriched = MediaRetrievalResult(
        retriever_name=result.retriever_name,
        platform=result.platform,
        inputs=inputs,
        raw_result=rows,
        summary=result.summary,
        status=result.status,
        suggested_actions=result.suggested_actions,
        candidate_keys=result.candidate_keys,
        per_platform=result.per_platform,
        deduped_by_influencer=result.deduped_by_influencer,
    )
    summary = build_research_summary(enriched, question=question)
    trace = build_retrieval_trace(
        enriched, question=question, retriever_config=retriever_config
    )

    research_notes = get_retriever_research_notes(retriever_name, signal)

    return MediaRetrievalResult(
        retriever_name=result.retriever_name,
        platform=result.platform,
        inputs=inputs,
        raw_result=rows,
        summary=summary,
        status=result.status,
        suggested_actions=result.suggested_actions,
        candidate_keys=result.candidate_keys,
        per_platform=result.per_platform,
        deduped_by_influencer=result.deduped_by_influencer,
        retrieval_trace=trace,
        research_notes=research_notes,
    )


HYBRID_AUDIT_MAX_IDS = 250


def _cap_audit_id_list(values: List[Any]) -> List[str]:
    """Stringify and cap ID lists stored for hybrid debugging in Mongo."""
    cleaned = [str(v) for v in values if v is not None and str(v).strip()]
    if len(cleaned) <= HYBRID_AUDIT_MAX_IDS:
        return cleaned
    omitted = len(cleaned) - HYBRID_AUDIT_MAX_IDS
    return cleaned[:HYBRID_AUDIT_MAX_IDS] + [f"... +{omitted} more (truncated)"]


def build_hybrid_audit(
    *,
    candidate_keys: Optional[Dict[str, List[Any]]],
    candidate_counts: Optional[Dict[str, int]],
    stage2_cypher: Optional[str],
    stage2_params: Optional[Dict[str, Any]],
    stage1_retriever: Optional[str] = None,
) -> Dict[str, Any]:
    """Compact audit blob for hybrid runs (persisted to chat_message_payloads)."""
    keys_in = candidate_keys or {}
    keys_out: Dict[str, List[str]] = {}
    for kind, vals in keys_in.items():
        if isinstance(vals, list):
            keys_out[kind] = _cap_audit_id_list(vals)

    params_out: Dict[str, Any] = {}
    for key, vals in (stage2_params or {}).items():
        if isinstance(vals, list):
            params_out[key] = _cap_audit_id_list(vals)
        elif vals is not None:
            params_out[key] = vals

    return {
        "stage1_retriever": stage1_retriever,
        "candidate_keys": keys_out,
        "candidate_counts": dict(candidate_counts or {}),
        "stage2_cypher": stage2_cypher,
        "stage2_params": params_out,
    }


HYBRID_RESEARCH_NOTES: List[str] = [
    "This answer uses two steps: (1) find creators or videos whose content or "
    "audience discussions match your topic, then (2) filter or rank them by "
    "who follows the relevant creators in the graph (location, gender, platform, etc.).",
    "Semantic matching uses AI embeddings over indexed media text — not keyword search.",
    "The location/demographic filter uses survey-linked follower data in the graph "
    "(who follows whom, where people live).",
]


def _match_geo_name(question: str) -> Optional[str]:
    try:
        from ai.terminology.loader import load as load_terminology

        data = load_terminology("v1") or {}
        geo = data.get("geography") or {}
        areas = list(geo.get("area_names") or [])
        munis = list(geo.get("municipality_names") or [])
        q_lower = question.lower()
        for name in sorted(areas + munis, key=len, reverse=True):
            if name.lower() in q_lower:
                return name
    except Exception:
        pass
    return None


def _demographic_label(question: str) -> Optional[str]:
    q_lower = question.lower()
    if re.search(r"\b(girls?|females?|women)\b", q_lower):
        return "girls"
    if re.search(r"\b(boys?|males?|men)\b", q_lower):
        return "boys"
    return None


def _explicit_platform_label(question: str) -> Optional[str]:
    q_lower = question.lower()
    yt = bool(re.search(r"\b(youtube|youtuber)s?\b", q_lower))
    tt = bool(re.search(r"\b(tiktok|tiktoker)s?\b", q_lower))
    if yt and not tt:
        return "YouTube"
    if tt and not yt:
        return "TikTok"
    return None


def _hybrid_wants_count(question: str) -> bool:
    return bool(re.search(r"\bhow many\b", question, re.IGNORECASE))


def _hybrid_stage2_action(question: str) -> str:
    """How Stage 2 is described — not how results are sorted in the UI."""
    from .hybrid_handler import question_wants_follower_ranking

    if _hybrid_wants_count(question):
        return "counted"
    if question_wants_follower_ranking(question):
        return "ranked"
    return "filtered"


def _hybrid_stage2_action_label(action: str) -> str:
    return {
        "counted": "Counted",
        "ranked": "Ranked",
        "filtered": "Filtered",
    }.get(action, "Filtered")


def _hybrid_stage1_retriever_name(retriever_name: Optional[str]) -> str:
    if not retriever_name:
        return ""
    return retriever_name.replace("+structural_cypher", "")


def _hybrid_targets_videos(
    retriever_name: Optional[str],
    question: str,
    candidate_counts: Optional[Dict[str, int]] = None,
) -> bool:
    """True when hybrid Stage 2 should surface videos (not creators)."""
    counts = candidate_counts or {}
    video_ids = int(counts.get("video_ids") or 0)
    account_ids = int(counts.get("youtube_channel_ids") or 0) + int(
        counts.get("tiktok_usernames") or 0
    )
    if video_ids > 0 and account_ids == 0:
        return True
    if re.search(r"\bvideos?\b", question, re.IGNORECASE):
        return True
    if re.search(
        r"\b(?:creators?|tiktokers?|youtubers?|influencers?)\b",
        question,
        re.IGNORECASE,
    ):
        return False
    profile = get_retriever_profile(_hybrid_stage1_retriever_name(retriever_name))
    return profile.get("output") == "videos"


def _hybrid_entity_label(
    retriever_name: Optional[str],
    question: str,
    candidate_counts: Optional[Dict[str, int]] = None,
    *,
    plural: bool = True,
) -> str:
    if _hybrid_targets_videos(retriever_name, question, candidate_counts):
        return "videos" if plural else "video"
    return "creators" if plural else "creator"


def _person_survey_label(question: str) -> Optional[str]:
    from .hybrid_handler import (
        _extract_person_attribute_filter,
        person_attribute_human_label,
    )

    person_attr = _extract_person_attribute_filter(question)
    if not person_attr:
        return None
    return person_attribute_human_label(person_attr[0], person_attr[1])


def _income_wealth_label(question: str) -> Optional[str]:
    q = question.lower()
    if not re.search(
        r"\b("
        r"income|wealth|household\s+wealth|socioeconomic|socio-economic|"
        r"deprived|disadvantaged|poor(?:est)?|low-income|low\s+income"
        r")\b",
        q,
    ):
        return None
    if re.search(
        r"\b("
        r"highest|richest|wealthiest|maximum|most\s+wealth|"
        r"high(?:est)?\s+income"
        r")\b",
        q,
    ):
        return "people in areas with the highest household wealth"
    return "people in areas with the lowest household wealth"


def _structural_filter_label(question: str) -> str:
    """Plain-language description of the structural part of a hybrid question."""
    demo = _demographic_label(question)
    geo = _match_geo_name(question)
    survey = _person_survey_label(question)
    income = _income_wealth_label(question)
    platform = _explicit_platform_label(question)

    if demo and geo:
        label = f"{demo} living in {geo}"
    elif survey and geo:
        label = f"{survey} living in {geo}"
    elif geo:
        label = f"people living in {geo}"
    elif survey:
        label = survey
    elif income:
        label = income
    elif demo:
        label = demo
    else:
        label = "people matching the location or demographic filter in your question"

    if platform:
        return f"{label} (via {platform} follows)"
    return label


def _candidate_pool_label(
    candidate_counts: Dict[str, int],
    *,
    retriever_name: Optional[str] = None,
    question: str = "",
) -> str:
    videos = int(candidate_counts.get("video_ids") or 0)
    yt = int(candidate_counts.get("youtube_channel_ids") or 0)
    tt = int(candidate_counts.get("tiktok_usernames") or 0)
    if _hybrid_targets_videos(retriever_name, question, candidate_counts):
        if videos:
            return f"{videos} video{'s' if videos != 1 else ''}"
        return "no semantically matched videos"
    if yt and tt:
        return f"{yt} YouTube channels and {tt} TikTok accounts"
    if yt:
        return f"{yt} YouTube channel{'s' if yt != 1 else ''}"
    if tt:
        return f"{tt} TikTok account{'s' if tt != 1 else ''}"
    return "no semantically matched accounts"


def _platforms_searched_label(
    candidate_counts: Dict[str, int],
    *,
    platform: str = "all",
) -> str:
    yt = int(candidate_counts.get("youtube_channel_ids") or 0)
    tt = int(candidate_counts.get("tiktok_usernames") or 0)
    videos = int(candidate_counts.get("video_ids") or 0)
    if videos and not yt and not tt:
        normalized = (platform or "all").strip().lower()
        if normalized == "youtube":
            return "YouTube"
        if normalized == "tiktok":
            return "TikTok"
        return "YouTube and TikTok"
    if yt and tt:
        return "YouTube and TikTok"
    if yt:
        return "YouTube"
    if tt:
        return "TikTok"
    return "YouTube and TikTok"


def build_hybrid_explanation(
    *,
    question: str,
    theme: str,
    candidate_counts: Dict[str, int],
    min_score: Optional[float],
    signal: str,
    retriever_name: Optional[str] = None,
    platform: str = "all",
) -> str:
    """User-facing paragraph explaining how the hybrid answer was produced."""
    signal_label = SIGNAL_LABELS.get(signal, signal.replace("_", " "))
    pool = _candidate_pool_label(
        candidate_counts, retriever_name=retriever_name, question=question
    )
    platforms = _platforms_searched_label(candidate_counts, platform=platform)
    structural = _structural_filter_label(question)
    score_txt = f"{min_score:.2f}" if isinstance(min_score, (int, float)) else "0.70"
    action = _hybrid_stage2_action(question)
    video_output = _hybrid_targets_videos(retriever_name, question, candidate_counts)
    entity = _hybrid_entity_label(
        retriever_name, question, candidate_counts, plural=True
    )
    if video_output:
        subject = f"videos whose {signal_label}"
        if action == "counted":
            tail = (
                f"Then we counted how many of those videos are published by creators "
                f"followed by {structural}."
            )
        elif action == "ranked":
            tail = (
                f"Then we ranked those videos by how many {structural} follow "
                f"their creators on the graph."
            )
        else:
            tail = (
                f"Then we kept only videos whose creators are followed by "
                f"{structural}."
            )
    else:
        subject = f"creators whose {signal_label}"
        if action == "counted":
            tail = f"Then we counted how many of those {entity} are followed by {structural}."
        elif action == "ranked":
            tail = (
                f"Then we ranked those {entity} by how many {structural} follow them "
                f"on the graph."
            )
        else:
            tail = (
                f"Then we kept only those {entity} followed by {structural} "
                f"(results below are sorted by semantic relevance from step 1)."
            )
    return (
        f"We searched {platforms} for {subject} match "
        f"\"{theme}\" (similarity ≥ {score_txt}) and found {pool}. {tail}"
    )


def build_hybrid_summary(
    *,
    question: str,
    theme: str,
    candidate_counts: Dict[str, int],
    stage2_rows: List[Dict[str, Any]],
    stage1_result_count: int,
    status: str,
    min_score: Optional[float] = None,
    signal: str = "topic",
    retriever_name: Optional[str] = None,
) -> str:
    """User-facing summary for hybrid_media (deterministic)."""
    if not is_valid_media_theme(theme):
        return (
            f"Could not extract a clear topic from your question "
            f"(got {theme!r}). Name the theme explicitly, e.g. 'gaming' or "
            f"'vaping', along with the location or audience filter "
            f"(e.g. girls in IJsselmonde)."
        )

    total_candidates = sum(candidate_counts.values()) if candidate_counts else 0
    structural = _structural_filter_label(question)
    video_output = _hybrid_targets_videos(retriever_name, question, candidate_counts)
    entity = _hybrid_entity_label(
        retriever_name, question, candidate_counts, plural=True
    )
    entity_one = _hybrid_entity_label(
        retriever_name, question, candidate_counts, plural=False
    )

    if status == "soft_failure" or total_candidates == 0:
        return (
            f"Could not answer your question about '{theme}' — too few {entity} "
            f"semantically matched the theme on YouTube/TikTok to apply the filter "
            f"for {structural}. Try broadening the theme or lowering the similarity threshold."
        )

    if not stage2_rows:
        action = _hybrid_stage2_action(question)
        if video_output:
            if action == "ranked":
                return (
                    f"No videos in the semantic '{theme}' pool are from creators "
                    f"followed by {structural} — so none could be ranked."
                )
            if action == "counted":
                return (
                    f"No videos both match '{theme}' (semantically) and are from "
                    f"creators followed by {structural}."
                )
            return (
                f"No videos in the semantic '{theme}' pool are from creators "
                f"followed by {structural}."
            )
        if action == "ranked":
            return (
                f"No creators in the semantic '{theme}' pool are followed by "
                f"{structural} — so none could be ranked for popularity."
            )
        if action == "counted":
            return (
                f"No creators both discuss '{theme}' (semantically) and are followed by "
                f"{structural}."
            )
        return (
            f"No creators in the semantic '{theme}' pool are followed by {structural}."
        )

    if len(stage2_rows) == 1:
        row = stage2_rows[0]
        for key in ("creator_count", "video_count", "count"):
            if key in row and isinstance(row[key], (int, float)):
                count_value = int(row[key])
                names = [
                    str(n).strip()
                    for n in (
                        row.get("video_titles")
                        if video_output and key == "video_count"
                        else row.get("creator_names")
                    )
                    or []
                    if n and str(n).strip()
                ]
                if count_value == 1 and names:
                    return (
                        f"1 {entity_one} matches '{theme}' and the structural filter "
                        f"({structural}): {names[0]}."
                    )
                if names and len(names) <= 10:
                    return (
                        f"{count_value} {entity} match '{theme}' and {structural}: "
                        f"{', '.join(names)}."
                    )
                if count_value == 1:
                    return (
                        f"1 {entity_one} matches '{theme}' and {structural}."
                    )
                return (
                    f"{count_value} {entity} match '{theme}' and {structural}."
                )

    if video_output:
        action = _hybrid_stage2_action(question)
        if action == "ranked":
            heading = (
                f"{len(stage2_rows)} videos match '{theme}' and are from creators "
                f"followed by {structural} (ranked by survey follower count):"
            )
        else:
            heading = (
                f"{len(stage2_rows)} videos match '{theme}' and are from creators "
                f"followed by {structural}:"
            )
    else:
        action = _hybrid_stage2_action(question)
        if action == "ranked":
            heading = (
                f"{len(stage2_rows)} creators match '{theme}' and are followed by "
                f"{structural} (ranked by survey follower count):"
            )
        else:
            heading = (
                f"{len(stage2_rows)} creators match '{theme}' and are followed by "
                f"{structural}:"
            )
    lines = [heading]
    for row in stage2_rows[:SUMMARY_EXAMPLE_LIMIT]:
        if not isinstance(row, dict):
            continue
        label = (
            row.get("title")
            or row.get("video_title")
            or row.get("influencer_name")
            or row.get("creator")
        )
        if label:
            lines.append(f"• {label}")
    if len(stage2_rows) > SUMMARY_EXAMPLE_LIMIT:
        lines.append(
            f"• … and {len(stage2_rows) - SUMMARY_EXAMPLE_LIMIT} more "
            f"(see full results below)."
        )
    return "\n".join(lines)


def build_hybrid_trace(
    *,
    question: str,
    theme: str,
    stage1: Dict[str, Any],
    candidate_counts: Dict[str, int],
    stage2_cypher: Optional[str],
    retriever_name: str,
    inputs: Dict[str, Any],
) -> Dict[str, Any]:
    """Six-step trace covering Stage 1 semantic + Stage 2 structural."""
    signal = inputs.get("signal") or stage1.get("inputs", {}).get("signal") or "topic"
    signal_label = SIGNAL_LABELS.get(signal, signal.replace("_", " "))
    min_score = inputs.get("min_score") or stage1.get("inputs", {}).get("min_score")
    query_text = inputs.get("query_text") or stage1.get("inputs", {}).get("query_text") or theme
    embedding_model = (
        os.environ.get("MEDIA_EMBEDDING_MODEL")
        or os.environ.get("OPENAI_EMBEDDING_MODEL")
        or "text-embedding-3-large"
    )
    stage1_retriever = stage1.get("retriever_name") or retriever_name
    platform = (
        inputs.get("platform")
        or (stage1.get("inputs") or {}).get("platform")
        or "all"
    )
    pool = _candidate_pool_label(
        candidate_counts, retriever_name=stage1_retriever, question=question
    )
    platforms = _platforms_searched_label(candidate_counts, platform=platform)
    structural = _structural_filter_label(question)
    score_txt = (
        f"{float(min_score):.2f}"
        if isinstance(min_score, (int, float))
        else "0.70"
    )
    video_output = _hybrid_targets_videos(
        stage1_retriever, question, candidate_counts
    )
    entity = _hybrid_entity_label(
        stage1_retriever, question, candidate_counts, plural=True
    )
    hybrid_explanation = build_hybrid_explanation(
        question=question,
        theme=theme,
        candidate_counts=candidate_counts,
        min_score=min_score if isinstance(min_score, (int, float)) else None,
        signal=signal,
        retriever_name=stage1_retriever,
        platform=platform,
    )
    stage2_action = _hybrid_stage2_action(question)
    stage2_verb = _hybrid_stage2_action_label(stage2_action)
    if video_output:
        stage2_detail = (
            f"{stage2_verb} videos from that pool to those whose creators are "
            f"followed among {structural}. "
            "This uses follower ↔ influencer ↔ account ↔ video links in Neo4j — "
            "no second keyword or vector search."
        )
        stage2_search_subject = f"videos whose {signal_label}"
    else:
        stage2_detail = (
            f"{stage2_verb} {entity} from that pool to those followed among "
            f"{structural}. "
            "This uses follower ↔ influencer ↔ channel links in Neo4j — "
            "no second keyword or vector search."
        )
        stage2_search_subject = f"creators whose {signal_label}"

    steps = [
        {
            "step": 1,
            "title": "Understand your question",
            "detail": (
                f"Topic to match: \"{theme}\". "
                f"Structural filter: {structural}."
            ),
        },
        {
            "step": 2,
            "title": f"Semantic search ({platforms})",
            "detail": (
                f"Searched {platforms} for {stage2_search_subject} that are "
                f"semantically similar to \"{query_text}\" (threshold ≥ {score_txt}, "
                f"model {embedding_model}). Found {pool} to consider."
            ),
        },
        {
            "step": 3,
            "title": "Structural filter in the graph",
            "detail": (
                stage2_detail
                + (" Cypher ran successfully." if stage2_cypher else "")
            ),
        },
        {
            "step": 4,
            "title": "Your answer",
            "detail": hybrid_explanation,
        },
    ]

    return {
        "steps": steps,
        "params": {
            "route": "hybrid_media",
            "retriever": retriever_name,
            "stage1_retriever": stage1.get("retriever_name"),
            "theme": theme,
            "query_text": query_text,
            "signal": signal,
            "min_score": min_score,
            "candidate_counts": candidate_counts,
            "platforms_searched": platforms,
            "structural_filter": structural,
            "hybrid_explanation": hybrid_explanation,
            "embedding_model": embedding_model,
            "deduped_by_influencer": stage1.get("deduped_by_influencer"),
            "stage2_cypher_generated": bool(stage2_cypher),
        },
        "research_notes": list(HYBRID_RESEARCH_NOTES),
    }


def present_hybrid_result(
    result: HybridMediaResult,
    *,
    question: str,
) -> HybridMediaResult:
    """Enrich hybrid summary, trace, and Stage 1 creator rows for the UI."""
    from .hybrid_handler import HybridMediaResult

    inputs = dict(result.inputs or {})
    theme = inputs.get("theme") or inputs.get("inputs", {}).get("theme") or "?"
    stage1 = dict(result.stage1 or {})
    signal = (
        inputs.get("signal")
        or (stage1.get("inputs") or {}).get("signal")
        or "topic"
    )

    stage1_results = list(stage1.get("results") or stage1.get("results_preview") or [])
    stage1_retriever = stage1.get("retriever_name") or inputs.get("stage1_retriever") or ""
    min_score = inputs.get("min_score") or (stage1.get("inputs") or {}).get("min_score")
    if stage1_results and _is_video_result(stage1_results):
        stage1_results = enrich_video_results(
            stage1_results,
            signal=signal,
            theme=str(theme),
            retriever_name=stage1_retriever,
        )
        stage1 = {**stage1, "results": stage1_results}
    elif stage1_results and not _is_count_result(stage1_results):
        stage1_results = enrich_creator_results(
            stage1_results,
            signal=signal,
            theme=str(theme),
            retriever_name=stage1_retriever,
        )
        stage1 = {**stage1, "results": stage1_results}

    stage2_results = list(result.results or [])
    if stage2_results:
        stage2_results = enrich_hybrid_stage2_results(
            stage2_results,
            stage1_results=stage1_results,
            signal=signal,
            theme=str(theme),
            retriever_name=stage1_retriever or result.retriever_name,
            per_platform=stage1.get("per_platform"),
            min_score=min_score if isinstance(min_score, (int, float)) else None,
            question=question,
        )

    summary = build_hybrid_summary(
        question=question,
        theme=str(theme),
        candidate_counts=result.candidate_counts or {},
        stage2_rows=stage2_results,
        stage1_result_count=len(stage1_results),
        status=result.status,
        min_score=min_score if isinstance(min_score, (int, float)) else None,
        signal=signal,
        retriever_name=stage1_retriever or result.retriever_name,
    )
    hybrid_audit = build_hybrid_audit(
        candidate_keys=stage1.get("candidate_keys"),
        candidate_counts=result.candidate_counts,
        stage2_cypher=result.stage2_cypher,
        stage2_params=result.stage2_params,
        stage1_retriever=stage1_retriever or result.retriever_name,
    )

    trace = build_hybrid_trace(
        question=question,
        theme=str(theme),
        stage1=stage1,
        candidate_counts=result.candidate_counts or {},
        stage2_cypher=result.stage2_cypher,
        retriever_name=result.retriever_name,
        inputs=inputs,
    )
    if isinstance(trace.get("params"), dict):
        trace["params"]["stage2_cypher"] = result.stage2_cypher
        trace["params"]["hybrid_audit"] = hybrid_audit

    return HybridMediaResult(
        retriever_name=result.retriever_name,
        platform=result.platform,
        inputs=inputs,
        stage1=stage1,
        stage2_cypher=result.stage2_cypher,
        stage2_params=result.stage2_params,
        candidate_counts=result.candidate_counts,
        results=stage2_results,
        summary=summary,
        status=result.status,
        error=result.error,
        timings=result.timings,
        retrieval_trace=trace,
        research_notes=list(HYBRID_RESEARCH_NOTES),
        hybrid_audit=hybrid_audit,
    )
