#!/usr/bin/env python3
"""Merge per-keyword batch JSON results into theme-level deduplicated totals.

Phase 2 of batch eval: read output/{keyword}/questionN.json, union ID lists per
theme, and write output/themes/{theme}/questionN_merged.json.

Usage:
  python batch_eval/merge_themes.py
  python batch_eval/merge_themes.py --theme violence --question 5
  python batch_eval/merge_themes.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

DEFAULT_THEMES = Path(__file__).resolve().parent / "input" / "themes.yaml"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output"
QUESTION_COUNT = 7

# question_index -> merge kind
CREATOR_QUESTIONS = {4, 6}
VIDEO_COUNT_QUESTIONS = {5, 7}
EXAMPLE_QUESTIONS = {1, 2, 3}


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "keyword"


def _load_themes(path: Path) -> Dict[str, List[str]]:
    if not path.exists():
        raise FileNotFoundError(f"Themes file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError("PyYAML is required to read themes.yaml (pip install pyyaml)")
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid themes file (expected mapping): {path}")
    themes: Dict[str, List[str]] = {}
    for name, keywords in data.items():
        if not isinstance(keywords, list):
            raise ValueError(f"Theme {name!r} must be a list of keywords")
        themes[str(name)] = [str(k).strip() for k in keywords if str(k).strip()]
    return themes


def _load_batch_json(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not path.exists():
        return None, "missing file"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if "response" not in data and "error" in str(data.get("response", "")):
        pass
    resp = data.get("response")
    if not isinstance(resp, dict):
        return None, "no response object"
    if resp.get("error"):
        return None, f"api error: {resp.get('error')}"
    return data, None


def _per_platform_candidate_keys(response: Dict[str, Any]) -> Dict[str, Set[Any]]:
    """Collect candidate_keys from response.per_platform.*."""
    merged: Dict[str, Set[Any]] = {
        "youtube_channel_ids": set(),
        "tiktok_usernames": set(),
        "video_ids": set(),
    }
    per_platform = response.get("per_platform") or {}
    if not isinstance(per_platform, dict):
        return merged
    for plat_data in per_platform.values():
        if not isinstance(plat_data, dict):
            continue
        keys = plat_data.get("candidate_keys") or {}
        if not isinstance(keys, dict):
            continue
        for bucket, ids in keys.items():
            if bucket not in merged or not isinstance(ids, list):
                continue
            for item in ids:
                if item is not None and str(item).strip():
                    merged[bucket].add(item if bucket == "video_ids" else str(item))
    top_keys = response.get("candidate_keys")
    if isinstance(top_keys, dict):
        for bucket, ids in top_keys.items():
            if bucket in merged and isinstance(ids, list):
                for item in ids:
                    if item is not None and str(item).strip():
                        merged[bucket].add(item if bucket == "video_ids" else str(item))
    return merged


def _reported_count(response: Dict[str, Any]) -> Optional[int]:
    """Sum count fields from platform rows (informational only — do not merge by summing)."""
    total = 0
    found = False
    for row in response.get("results") or []:
        if not isinstance(row, dict):
            continue
        if row.get("count_field") and row.get("count") is not None:
            try:
                total += int(row["count"])
                found = True
            except (TypeError, ValueError):
                pass
    return total if found else None


def _score_value(row: Dict[str, Any]) -> float:
    for key in ("score", "relevance", "ranking_value", "engagement_score"):
        val = row.get(key)
        if isinstance(val, (int, float)):
            return float(val)
    return -1.0


def _merge_examples(
    keyword_payloads: List[Tuple[str, Dict[str, Any]]],
) -> Dict[str, Any]:
    by_video: Dict[str, Dict[str, Any]] = {}
    keywords_included: List[str] = []
    skipped: List[Dict[str, str]] = []
    tool_names: Set[str] = set()
    route_types: Set[str] = set()

    for keyword, data in keyword_payloads:
        resp = data["response"]
        keywords_included.append(keyword)
        if resp.get("tool_name"):
            tool_names.add(str(resp["tool_name"]))
        if resp.get("route_type"):
            route_types.add(str(resp["route_type"]))

        for row in resp.get("results") or []:
            if not isinstance(row, dict):
                continue
            vid = row.get("video_id")
            if vid is None:
                continue
            key = str(vid)
            existing = by_video.get(key)
            row_copy = dict(row)
            row_copy["_source_keywords"] = [keyword]
            if existing is None or _score_value(row_copy) > _score_value(existing):
                if existing and existing.get("_source_keywords"):
                    row_copy["_source_keywords"] = sorted(
                        set(existing["_source_keywords"]) | {keyword}
                    )
                by_video[key] = row_copy
            else:
                existing["_source_keywords"] = sorted(
                    set(existing.get("_source_keywords") or []) | {keyword}
                )

    merged_rows = sorted(by_video.values(), key=_score_value, reverse=True)
    return {
        "merge_kind": "examples",
        "keywords_included": keywords_included,
        "skipped_keywords": skipped,
        "tool_names": sorted(tool_names),
        "route_types": sorted(route_types),
        "unique_counts": {"videos": len(merged_rows)},
        "sum_of_per_keyword_result_rows": None,
        "unique_total": len(merged_rows),
        "ids": {"video_ids": list(by_video.keys())},
        "merged_results": merged_rows,
    }


def _merge_id_buckets(
    keyword_payloads: List[Tuple[str, Dict[str, Any]]],
    *,
    merge_kind: str,
    id_buckets: Tuple[str, ...],
) -> Dict[str, Any]:
    union: Dict[str, Set[Any]] = {b: set() for b in id_buckets}
    per_keyword_counts: Dict[str, Optional[int]] = {}
    keywords_included: List[str] = []
    skipped: List[Dict[str, str]] = []
    tool_names: Set[str] = set()
    route_types: Set[str] = set()

    for keyword, data in keyword_payloads:
        resp = data["response"]
        keywords_included.append(keyword)
        if resp.get("tool_name"):
            tool_names.add(str(resp["tool_name"]))
        if resp.get("route_type"):
            route_types.add(str(resp["route_type"]))
        per_keyword_counts[keyword] = _reported_count(resp)
        keys = _per_platform_candidate_keys(resp)
        for bucket in id_buckets:
            union[bucket] |= keys[bucket]

    unique_counts = {b: len(union[b]) for b in id_buckets}
    sum_reported = sum(c for c in per_keyword_counts.values() if c is not None)
    unique_total = sum(unique_counts.values())

    if merge_kind == "creators":
        headline = unique_counts.get("youtube_channel_ids", 0) + unique_counts.get(
            "tiktok_usernames", 0
        )
    else:
        headline = unique_counts.get("video_ids", 0)

    return {
        "merge_kind": merge_kind,
        "keywords_included": keywords_included,
        "skipped_keywords": skipped,
        "tool_names": sorted(tool_names),
        "route_types": sorted(route_types),
        "unique_counts": unique_counts,
        "unique_total": headline,
        "sum_of_per_keyword_reported_counts": sum_reported if per_keyword_counts else None,
        "overlap_note": (
            f"Summing per-keyword reported counts would give {sum_reported}; "
            f"unique IDs across the theme give {headline} "
            f"(platform buckets may double-count cross-platform creators)."
            if sum_reported is not None
            else None
        ),
        "per_keyword_reported_counts": per_keyword_counts,
        "ids": {b: sorted(union[b], key=lambda x: str(x)) for b in id_buckets},
        "merged_results": None,
    }


def _merge_question(
    theme: str,
    question_index: int,
    keywords: List[str],
    output_dir: Path,
) -> Dict[str, Any]:
    keyword_payloads: List[Tuple[str, Dict[str, Any]]] = []
    skipped: List[Dict[str, str]] = []

    for keyword in keywords:
        path = output_dir / _slug(keyword) / f"question{question_index}.json"
        data, err = _load_batch_json(path)
        if err or data is None:
            skipped.append(
                {"keyword": keyword, "reason": err or "empty payload", "path": str(path)}
            )
            continue
        keyword_payloads.append((keyword, data))

    base: Dict[str, Any] = {
        "theme": theme,
        "question_index": question_index,
        "keywords_requested": keywords,
    }

    if not keyword_payloads:
        return {
            **base,
            "status": "error",
            "error": "no keyword JSON files loaded",
            "skipped_keywords": skipped,
        }

    if question_index in EXAMPLE_QUESTIONS:
        merged = _merge_examples(keyword_payloads)
    elif question_index in CREATOR_QUESTIONS:
        merged = _merge_id_buckets(
            keyword_payloads,
            merge_kind="creators",
            id_buckets=("youtube_channel_ids", "tiktok_usernames"),
        )
    elif question_index in VIDEO_COUNT_QUESTIONS:
        merged = _merge_id_buckets(
            keyword_payloads,
            merge_kind="videos",
            id_buckets=("video_ids",),
        )
    else:
        return {**base, "status": "error", "error": f"unsupported question index {question_index}"}

    merged["skipped_keywords"] = skipped + merged.get("skipped_keywords", [])
    merged["status"] = "ok" if len(keyword_payloads) == len(keywords) else "partial"
    return {**base, **merged}


def _format_md_row(theme: str, q: int, merged: Dict[str, Any]) -> str:
    status = merged.get("status", "?")
    n_kw = len(merged.get("keywords_included") or [])
    n_skip = len(merged.get("skipped_keywords") or [])
    unique = merged.get("unique_total", "—")
    tools = ", ".join(merged.get("tool_names") or []) or "—"
    return (
        f"| {theme} | {q} | {status} | {n_kw} | {n_skip} | {unique} | `{tools}` |"
    )


def _write_md_summary(
    out_path: Path,
    rows: List[str],
    *,
    themes_path: Path,
) -> None:
    lines = [
        f"# Theme merge {datetime.now(timezone.utc).isoformat()}",
        "",
        f"- Themes: `{themes_path}`",
        "",
        "| Theme | Q# | Status | Keywords merged | Skipped | Unique total | Tools |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *rows,
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Merge batch JSON results by theme")
    parser.add_argument(
        "--themes",
        type=Path,
        default=DEFAULT_THEMES,
        help=f"Themes YAML/JSON (default: {DEFAULT_THEMES})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Batch output root (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument("--theme", help="Merge a single theme only")
    parser.add_argument(
        "--question",
        type=int,
        action="append",
        dest="questions",
        help="Merge specific question index(es) only (1-based)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print merge summary without writing files",
    )
    args = parser.parse_args(argv)

    try:
        themes = _load_themes(args.themes)
    except (OSError, ValueError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.theme:
        if args.theme not in themes:
            print(f"Unknown theme {args.theme!r}. Available: {', '.join(themes)}", file=sys.stderr)
            return 1
        themes = {args.theme: themes[args.theme]}

    question_indices = args.questions or list(range(1, QUESTION_COUNT + 1))
    themes_out = args.output_dir / "themes"
    index_rows: List[str] = []
    failures = 0

    for theme_name, keywords in themes.items():
        for q in question_indices:
            merged = _merge_question(theme_name, q, keywords, args.output_dir)
            index_rows.append(_format_md_row(theme_name, q, merged))
            if merged.get("status") == "error":
                failures += 1

            if args.dry_run:
                print(
                    f"[dry-run] {theme_name} Q{q}: status={merged.get('status')} "
                    f"unique_total={merged.get('unique_total')} "
                    f"keywords={len(merged.get('keywords_included') or [])} "
                    f"skipped={len(merged.get('skipped_keywords') or [])}"
                )
                continue

            theme_dir = themes_out / theme_name
            theme_dir.mkdir(parents=True, exist_ok=True)
            out_json = theme_dir / f"question{q}_merged.json"
            out_md = theme_dir / f"question{q}_merged.md"

            out_json.write_text(json.dumps(merged, indent=2, default=str), encoding="utf-8")

            md_lines = [
                f"# Theme merge — {theme_name} — Question {q}",
                "",
                f"- **Status:** {merged.get('status')}",
                f"- **Merge kind:** {merged.get('merge_kind')}",
                f"- **Keywords merged:** {len(merged.get('keywords_included') or [])} / {len(keywords)}",
                f"- **Unique total:** {merged.get('unique_total')}",
                "",
            ]
            if merged.get("overlap_note"):
                md_lines.extend(["## Overlap note", "", str(merged["overlap_note"]), ""])
            if merged.get("unique_counts"):
                md_lines.extend(["## Unique counts", "", "```json"])
                md_lines.append(json.dumps(merged["unique_counts"], indent=2))
                md_lines.extend(["```", ""])
            if merged.get("skipped_keywords"):
                md_lines.extend(["## Skipped keywords", ""])
                for sk in merged["skipped_keywords"]:
                    md_lines.append(f"- **{sk.get('keyword')}:** {sk.get('reason')}")
                md_lines.append("")
            out_md.write_text("\n".join(md_lines), encoding="utf-8")
            print(f"Wrote {out_json}")

    if not args.dry_run:
        _write_md_summary(themes_out / "_index.md", index_rows, themes_path=args.themes)
        print(f"\nWrote index: {themes_out / '_index.md'}")

    print(f"Failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
