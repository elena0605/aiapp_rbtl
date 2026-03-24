"""Visualization agent — transforms query results into chart specifications.

Runs as a post-processing step after the text-to-cypher pipeline when the
user's intent is classified as ``visualization``.  The agent calls an LLM
to decide the best chart type and structures the data for the frontend.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai.llmops.langfuse_client import create_completion, get_prompt_from_langfuse

logger = logging.getLogger("VisualizationAgent")

ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = ROOT / "ai" / "prompts"

VALID_CHART_TYPES = {"bar", "horizontal_bar", "pie", "line", "table", "number"}


@dataclass
class VisualizationSpec:
    """Structured visualization specification for the frontend."""

    chart_type: str
    title: str
    description: str
    data: Dict[str, Any]
    axes: Optional[Dict[str, Optional[str]]] = None
    summary: str = ""


class VisualizationAgent:
    """Decides how to visualize query results and prepares chart data."""

    def __init__(self, *, llm_model: Optional[str] = None) -> None:
        self._llm_model = (
            llm_model
            or os.environ.get("VISUALIZATION_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or os.environ.get("OPEN_AI_MODEL")
        )
        if not self._llm_model:
            raise RuntimeError(
                "No LLM model configured for VisualizationAgent. "
                "Set VISUALIZATION_MODEL or OPENAI_MODEL."
            )
        self._prompt = None

    def _get_prompt(self):
        """Load the visualization prompt (Langfuse with local fallback)."""
        if self._prompt is not None:
            return self._prompt

        prompt_label = os.environ.get("PROMPT_LABEL")
        try:
            self._prompt = get_prompt_from_langfuse(
                "graph.visualization",
                langfuse_client=None,
                label=prompt_label,
            )
        except Exception as err:
            logger.warning(
                "Langfuse prompt fetch for visualization failed (%s). "
                "Using local YAML fallback.",
                err,
            )
            self._prompt = self._load_local_prompt()
        return self._prompt

    def _load_local_prompt(self):
        """Load visualization prompt from local YAML."""
        import yaml

        _VAR_PATTERN = re.compile(r"{{\s*(\w+)\s*}}")

        for path in PROMPTS_DIR.glob("*.yaml"):
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if data.get("id") != "graph.visualization":
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
                    return _VAR_PATTERN.sub(_sub, self._template)

            return _Prompt(template, params)

        raise RuntimeError(
            "Prompt 'graph.visualization' not found in local YAML files."
        )

    def generate_spec(
        self,
        question: str,
        cypher: str,
        results: List[Dict[str, Any]],
    ) -> VisualizationSpec:
        """Generate a visualization specification from query results.

        Args:
            question: The original (or rewritten) user question.
            cypher: The Cypher query that was executed.
            results: The query result rows.

        Returns:
            A ``VisualizationSpec`` the frontend can render.
        """
        if not results:
            return VisualizationSpec(
                chart_type="table",
                title="No Data",
                description="The query returned no results.",
                data={"columns": [], "rows": []},
                summary="No results were found for this query.",
            )

        prompt_obj = self._get_prompt()

        preview = results[:20]
        rendered = prompt_obj.compile(
            question=question,
            cypher=cypher,
            results=json.dumps(preview, ensure_ascii=False),
            result_count=str(len(results)),
        )

        try:
            raw = create_completion(
                rendered,
                model=self._llm_model,
                temperature=0.0,
                max_tokens=1500,
                response_format={"type": "json_object"},
            )
        except Exception:
            raw = create_completion(
                rendered,
                model=self._llm_model,
                temperature=0.0,
                max_tokens=1500,
            )

        return self._parse_response(raw, question, results)

    def _parse_response(
        self,
        raw: str,
        question: str,
        results: List[Dict[str, Any]],
    ) -> VisualizationSpec:
        """Parse LLM JSON into a VisualizationSpec."""
        try:
            text = raw.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Visualization JSON parse failed: %s", exc)
            return self._fallback_table(question, results)

        chart_type = data.get("chart_type", "table")
        if chart_type not in VALID_CHART_TYPES:
            chart_type = "table"

        return VisualizationSpec(
            chart_type=chart_type,
            title=data.get("title", "Query Results"),
            description=data.get("description", ""),
            data=data.get("data", {}),
            axes=data.get("axes"),
            summary=data.get("summary", ""),
        )

    @staticmethod
    def _fallback_table(
        question: str, results: List[Dict[str, Any]]
    ) -> VisualizationSpec:
        """Produce a plain table spec when the LLM response is unparseable."""
        if not results:
            return VisualizationSpec(
                chart_type="table",
                title="No Data",
                description="No results to display.",
                data={"columns": [], "rows": []},
                summary="No results found.",
            )
        columns = list(results[0].keys())
        rows = [[row.get(c) for c in columns] for row in results[:50]]
        return VisualizationSpec(
            chart_type="table",
            title="Query Results",
            description=f"Results for: {question}",
            data={"columns": columns, "rows": rows},
            summary=f"Showing {len(rows)} of {len(results)} rows.",
        )
