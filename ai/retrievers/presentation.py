"""Research-oriented presentation layer for media retrieval results.

Enriches raw retriever rows with matched topics, ``why_retrieved`` text,
multi-paragraph summaries, and a lightweight retrieval trace suitable for
researchers validating relevance — without extra LLM calls.
"""

from __future__ import annotations

import os
from collections import Counter
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .base import MEDIA_RETRIEVER_K_FLOOR, MEDIA_RETRIEVER_TOP_N, get_media_retriever_min_score

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
    return out


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


HYBRID_RESEARCH_NOTES: List[str] = RESEARCH_NOTES + [
    "Hybrid results apply a structural graph filter (area, age, gender, etc.) "
    "on top of semantically matched candidates from Stage 1.",
    "Stage 2 Cypher never re-runs vector search — it only narrows the Stage 1 seed set.",
]


def build_hybrid_summary(
    *,
    question: str,
    theme: str,
    candidate_counts: Dict[str, int],
    stage2_rows: List[Dict[str, Any]],
    stage1_result_count: int,
    status: str,
) -> str:
    """Research-style summary for hybrid_media (deterministic)."""
    total_candidates = sum(candidate_counts.values()) if candidate_counts else 0
    cand_parts = ", ".join(
        f"{count} {kind.replace('_', ' ')}"
        for kind, count in candidate_counts.items()
        if count
    ) or "no candidates"

    if status == "soft_failure" or total_candidates == 0:
        return (
            f"Could not apply a structural filter for '{theme}' because Stage 1 "
            f"found insufficient semantic candidates ({cand_parts}). "
            "Try broadening the theme or lowering MEDIA_RETRIEVER_MIN_SCORE."
        )

    lines = [
        f"Hybrid retrieval for theme '{theme}' combined semantic matching with a "
        "structural filter from your question.",
        "",
        f"Stage 1 (semantic): {stage1_result_count} ranked candidates from vector "
        f"search ({cand_parts} IDs collected for filtering).",
    ]

    if not stage2_rows:
        lines.append("")
        lines.append(
            "Stage 2 (structural): no items matched both the semantic theme and "
            "the structural restriction in your question."
        )
        return "\n".join(lines)

    if len(stage2_rows) == 1:
        row = stage2_rows[0]
        for key in ("creator_count", "video_count", "count"):
            if key in row and isinstance(row[key], (int, float)):
                lines.append("")
                lines.append(
                    f"Stage 2 (structural): {int(row[key])} items matched both the "
                    f"semantic theme and the structural filter."
                )
                return "\n".join(lines)

    lines.append("")
    lines.append(
        f"Stage 2 (structural): {len(stage2_rows)} rows matched after applying the "
        "graph filter over Stage 1 candidates."
    )
    lines.append("")
    lines.append("Top matches:")
    for row in stage2_rows[:SUMMARY_EXAMPLE_LIMIT]:
        if not isinstance(row, dict):
            continue
        label = (
            row.get("creator")
            or row.get("influencer_name")
            or row.get("title")
            or row.get("video_title")
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
    cand_summary = ", ".join(
        f"{count} {kind.replace('_', ' ')}"
        for kind, count in (candidate_counts or {}).items()
        if count
    ) or "none"

    steps = [
        {
            "step": 1,
            "title": "Query understanding",
            "detail": (
                f"Classified as hybrid_media (semantic theme + structural filter). "
                f"Theme: '{theme}'. Question: "
                f"\"{question[:120]}{'...' if len(question) > 120 else ''}\""
            ),
        },
        {
            "step": 2,
            "title": "Stage 1 — Semantic retrieval",
            "detail": (
                f"Embedded '{query_text}' with {embedding_model} and ran "
                f"{stage1.get('retriever_name', retriever_name)} over {signal_label} "
                f"(min_score={min_score})."
            ),
        },
        {
            "step": 3,
            "title": "Stage 1 — Candidate IDs",
            "detail": (
                f"Collected candidate keys for Stage 2: {cand_summary}."
            ),
        },
        {
            "step": 4,
            "title": "Stage 2 — Structural Cypher",
            "detail": (
                "An LLM generated read-only Cypher to apply the structural filter "
                "(geography, demographics, follower attributes) over those candidate IDs."
                + (" Cypher was executed successfully." if stage2_cypher else "")
            ),
        },
        {
            "step": 5,
            "title": "Stage 2 — Graph filter",
            "detail": (
                "Structural Cypher joined candidates to Persons/Areas/Municipalities "
                "as required by the question. No vector search or CONTAINS matching "
                "on topic text in this stage."
            ),
        },
        {
            "step": 6,
            "title": "Final result",
            "detail": f"Combined pipeline retriever: {retriever_name}.",
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

    summary = build_hybrid_summary(
        question=question,
        theme=str(theme),
        candidate_counts=result.candidate_counts or {},
        stage2_rows=result.results or [],
        stage1_result_count=len(stage1_results),
        status=result.status,
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

    return HybridMediaResult(
        retriever_name=result.retriever_name,
        platform=result.platform,
        inputs=inputs,
        stage1=stage1,
        stage2_cypher=result.stage2_cypher,
        candidate_counts=result.candidate_counts,
        results=result.results,
        summary=summary,
        status=result.status,
        error=result.error,
        timings=result.timings,
        retrieval_trace=trace,
        research_notes=list(HYBRID_RESEARCH_NOTES),
    )
