#!/usr/bin/env python3
"""Run a batch of chat questions against the GraphRAG backend (same path as the UI).

Usage:
  python batch_eval/run_batch.py
  python batch_eval/run_batch.py --dry-run
  python batch_eval/run_batch.py --keyword vaping --force
  python batch_eval/run_batch.py --base-url http://localhost:8001 --username batch

Requires the backend to be running (see batch_eval/README.md).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = Path(__file__).resolve().parent / "input" / "campaign.md"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output"
DEFAULT_BASE_URL = "http://localhost:8001"
DEFAULT_USERNAME = "batch"
PLACEHOLDER = "[keyword]"


@dataclass
class Campaign:
    keywords: List[str]
    questions: List[str]


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "keyword"


def _parse_campaign(path: Path) -> Campaign:
    text = path.read_text(encoding="utf-8")
    keywords: List[str] = []
    questions: List[str] = []
    section: Optional[str] = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("# ") and not line.startswith("## "):
            continue
        if line.lower().startswith("## keywords"):
            section = "keywords"
            continue
        if line.lower().startswith("## questions"):
            section = "questions"
            continue
        if line.startswith("##"):
            section = None
            continue

        if section == "keywords":
            if line.startswith(("-", "*")):
                kw = line.lstrip("-*").strip()
                if kw:
                    keywords.append(kw)
            elif line and not line.startswith("#"):
                keywords.append(line)
        elif section == "questions":
            cleaned = re.sub(r"^\d+\.\s*", "", line)
            cleaned = cleaned.lstrip("-*").strip()
            if cleaned and PLACEHOLDER in cleaned:
                questions.append(cleaned)
            elif cleaned and PLACEHOLDER not in cleaned:
                print(
                    f"Warning: skipping question without {PLACEHOLDER!r}: {cleaned[:80]}",
                    file=sys.stderr,
                )

    if not keywords:
        raise ValueError(f"No keywords found in {path} (add a ## Keywords section)")
    if not questions:
        raise ValueError(f"No questions found in {path} (add a ## Questions section)")
    return Campaign(keywords=keywords, questions=questions)


def _substitute(question: str, keyword: str) -> str:
    return question.replace(PLACEHOLDER, keyword)


def _http_json(
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 300.0,
) -> Dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {detail}") from exc


def _health_ok(base_url: str, timeout: float = 10.0) -> bool:
    try:
        resp = _http_json("GET", f"{base_url.rstrip('/')}/api/health", timeout=timeout)
        return resp.get("status") == "healthy"
    except Exception:
        return False


def _format_md(
    *,
    keyword: str,
    question_index: int,
    question: str,
    response: Dict[str, Any],
    elapsed_s: float,
) -> str:
    lines = [
        f"# Question {question_index}",
        "",
        f"- **Keyword:** {keyword}",
        f"- **Asked at:** {datetime.now(timezone.utc).isoformat()}",
        f"- **Elapsed (s):** {elapsed_s:.1f}",
        "",
        "## Question",
        "",
        question,
        "",
        "## Routing",
        "",
        f"- **route_type:** `{response.get('route_type')}`",
        f"- **intent:** `{response.get('intent')}`",
        f"- **intent_confidence:** {response.get('intent_confidence')}",
        f"- **tool_name:** `{response.get('tool_name')}`",
        f"- **status:** `{response.get('status')}`",
    ]
    if response.get("error"):
        lines.extend(["", "## Error", "", str(response.get("error"))])

    lines.extend(["", "## Summary", "", str(response.get("summary") or "—")])

    cypher = response.get("cypher")
    if cypher:
        lines.extend(["", "## Cypher", "", "```cypher", str(cypher).strip(), "```"])

    stage1 = response.get("stage1")
    if isinstance(stage1, dict):
        lines.extend(
            [
                "",
                "## Hybrid Stage 1",
                "",
                f"- **retriever:** `{stage1.get('retriever_name')}`",
            ]
        )
        inputs = stage1.get("inputs") or {}
        if inputs.get("theme"):
            lines.append(f"- **theme:** `{inputs.get('theme')}`")

    candidate_counts = response.get("candidate_counts")
    if candidate_counts:
        lines.extend(["", "## Candidate counts", "", "```json"])
        lines.append(json.dumps(candidate_counts, indent=2))
        lines.append("```")

    hybrid_audit = response.get("hybrid_audit")
    if hybrid_audit:
        stage2_cypher = hybrid_audit.get("stage2_cypher") or response.get("cypher")
        if stage2_cypher and stage2_cypher != cypher:
            lines.extend(
                [
                    "",
                    "## Stage 2 Cypher",
                    "",
                    "```cypher",
                    str(stage2_cypher).strip(),
                    "```",
                ]
            )

    results = response.get("results")
    if isinstance(results, list):
        lines.extend(["", "## Results", "", f"Row count: **{len(results)}**"])
        if results and len(results) <= 5:
            lines.extend(["", "```json", json.dumps(results, indent=2, default=str), "```"])
        elif results:
            lines.append("")
            lines.append("(First 3 rows in JSON sidecar; full list omitted here.)")

    timings = response.get("timings")
    if timings:
        lines.extend(["", "## Timings", "", "```json"])
        lines.append(json.dumps(timings, indent=2))
        lines.append("```")

    trace = response.get("retrieval_trace")
    if trace:
        lines.extend(["", "## Retrieval trace", "", "```json"])
        lines.append(json.dumps(trace, indent=2, default=str))
        lines.append("```")

    return "\n".join(lines) + "\n"


def _run_one(
    *,
    base_url: str,
    username: str,
    question: str,
    output_mode: str,
    timeout: float,
) -> Tuple[Dict[str, Any], float]:
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "username": username,
        "question": question,
        "execute_cypher": True,
        "output_mode": output_mode,
    }
    started = time.perf_counter()
    response = _http_json("POST", url, payload, timeout=timeout)
    elapsed = time.perf_counter() - started
    return response, elapsed


def _build_jobs(
    campaign: Campaign,
    keyword_filter: Optional[str],
    question_indices: Optional[Sequence[int]],
) -> List[Tuple[str, int, str, str]]:
    jobs: List[Tuple[str, int, str, str]] = []
    for keyword in campaign.keywords:
        if keyword_filter and keyword != keyword_filter:
            continue
        for idx, template in enumerate(campaign.questions, start=1):
            if question_indices and idx not in question_indices:
                continue
            question = _substitute(template, keyword)
            jobs.append((keyword, idx, template, question))
    return jobs


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Batch-run chat questions via /api/chat")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Campaign markdown (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output root (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Backend base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--username",
        default=DEFAULT_USERNAME,
        help=f"Allowed test username (default: {DEFAULT_USERNAME})",
    )
    parser.add_argument(
        "--output-mode",
        choices=("chat", "json", "both"),
        default="both",
        help="Same as UI output_mode; 'both' keeps summary + structured fields",
    )
    parser.add_argument("--keyword", help="Run a single keyword only")
    parser.add_argument(
        "--question",
        type=int,
        action="append",
        dest="questions",
        help="Run specific question index(es) only (1-based); repeatable",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Seconds to wait between requests (rate limiting)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="HTTP timeout per question in seconds (default: 300)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print substituted questions without calling the API",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output files",
    )
    parser.add_argument(
        "--skip-health",
        action="store_true",
        help="Do not check /api/health before starting",
    )
    args = parser.parse_args(argv)

    campaign = _parse_campaign(args.input)
    jobs = _build_jobs(campaign, args.keyword, args.questions)
    if not jobs:
        print("No jobs to run.", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"Would run {len(jobs)} question(s):\n")
        for keyword, idx, _template, question in jobs:
            print(f"  [{_slug(keyword)}] Q{idx}: {question}")
        return 0

    if not args.skip_health and not _health_ok(args.base_url):
        print(
            f"Backend not healthy at {args.base_url}/api/health — start Docker first.\n"
            f"  docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d backend",
            file=sys.stderr,
        )
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    index_rows: List[str] = [
        f"# Batch run {datetime.now(timezone.utc).isoformat()}",
        "",
        f"- Input: `{args.input}`",
        f"- Base URL: `{args.base_url}`",
        f"- Jobs: {len(jobs)}",
        "",
        "| Keyword | Q# | route_type | tool_name | status | seconds | file |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    failures = 0
    for n, (keyword, idx, _template, question) in enumerate(jobs, start=1):
        folder = args.output_dir / _slug(keyword)
        folder.mkdir(parents=True, exist_ok=True)
        md_path = folder / f"question{idx}.md"
        json_path = folder / f"question{idx}.json"

        if md_path.exists() and not args.force:
            print(f"[{n}/{len(jobs)}] skip (exists): {md_path}")
            continue

        print(f"[{n}/{len(jobs)}] {keyword!r} Q{idx} …", flush=True)
        try:
            response, elapsed = _run_one(
                base_url=args.base_url,
                username=args.username,
                question=question,
                output_mode=args.output_mode,
                timeout=args.timeout,
            )
            md_path.write_text(
                _format_md(
                    keyword=keyword,
                    question_index=idx,
                    question=question,
                    response=response,
                    elapsed_s=elapsed,
                ),
                encoding="utf-8",
            )
            json_path.write_text(
                json.dumps(
                    {
                        "keyword": keyword,
                        "question_index": idx,
                        "question": question,
                        "elapsed_s": elapsed,
                        "response": response,
                    },
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            route = response.get("route_type")
            tool = response.get("tool_name")
            status = response.get("status") or ("error" if response.get("error") else "ok")
            index_rows.append(
                f"| {keyword} | {idx} | {route} | {tool} | {status} | {elapsed:.1f} | `{md_path.relative_to(args.output_dir)}` |"
            )
            if response.get("error"):
                failures += 1
        except Exception as exc:
            failures += 1
            err_md = (
                f"# Question {idx} — ERROR\n\n"
                f"**Keyword:** {keyword}\n\n"
                f"**Question:** {question}\n\n"
                f"**Error:** {exc}\n"
            )
            md_path.write_text(err_md, encoding="utf-8")
            index_rows.append(
                f"| {keyword} | {idx} | — | — | error | — | `{md_path.relative_to(args.output_dir)}` |"
            )
            print(f"  ERROR: {exc}", file=sys.stderr)

        if args.delay > 0 and n < len(jobs):
            time.sleep(args.delay)

    index_path = args.output_dir / "_index.md"
    index_path.write_text("\n".join(index_rows) + "\n", encoding="utf-8")
    print(f"\nWrote index: {index_path}")
    print(f"Failures: {failures}/{len(jobs)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
