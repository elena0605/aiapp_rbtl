"""GraphRAG service - wraps existing text_to_cypher logic."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, AsyncIterator
import json
import re
from functools import lru_cache
import logging
import time

import yaml

# Add project root to path (go up from backend/app/services/graphrag.py to project root)
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PROMPTS_DIR = ROOT / "ai" / "prompts"

from utils_neo4j import get_session
from ai.schema.schema_utils import get_cached_schema, fetch_schema_from_neo4j
from ai.terminology.loader import load as load_terminology, as_text as terminology_as_text
from ai.fewshots.vector_store import get_vector_store
from ai.llmops.langfuse_client import create_completion, get_prompt_from_langfuse

logger = logging.getLogger("GraphRAGService")


_PROMPT_VAR_PATTERN = re.compile(r"{{\s*(\w+)\s*}}")


class _LocalPrompt:
    """Minimal prompt wrapper to mimic Langfuse prompt objects."""

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

        return _PROMPT_VAR_PATTERN.sub(_replace, self._template)


@lru_cache(maxsize=8)
def _load_local_prompt(prompt_id: str) -> _LocalPrompt:
    """Load a prompt definition from ai/prompts/*.yaml by its Langfuse ID."""
    if not PROMPTS_DIR.exists():
        raise RuntimeError(
            f"Prompts directory '{PROMPTS_DIR}' not found. "
            "Ensure ai/prompts exists for offline prompt usage."
        )

    for path in PROMPTS_DIR.glob("*.yaml"):
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            continue
        if data.get("id") != prompt_id:
            continue

        template = data.get("template")
        if not template:
            raise RuntimeError(f"Prompt file '{path}' is missing a template section.")
        params = data.get("params") or {}
        return _LocalPrompt(template, params)

    raise RuntimeError(
        f"Prompt '{prompt_id}' not found in '{PROMPTS_DIR}'. "
        "Run ai/prompts/sync or ensure the YAML file exists."
    )


class GraphRAGService:
    """Service for processing natural language questions to Cypher queries."""
    
    def __init__(self):
        """Initialize the GraphRAG service."""
        # These will be loaded lazily on first use
        self._schema_string = None
        self._terminology_str = None
        self._prompt = None
        self._params = None
    
    def _get_schema(self) -> str:
        """Get Neo4j schema (cached)."""
        if self._schema_string is None:
            self._schema_string = get_cached_schema(
                force_update=False,
                fetch_schema_fn=fetch_schema_from_neo4j,
            )
        return self._schema_string
    
    def _get_terminology(self) -> str:
        """Get terminology string."""
        if self._terminology_str is None:
            terminology_dict = load_terminology("v1")
            self._terminology_str = terminology_as_text(terminology_dict)
        return self._terminology_str
    
    def _get_prompt(self):
        """Get Langfuse prompt."""
        if self._prompt is None:
            prompt_label = os.environ.get("PROMPT_LABEL")
            if not prompt_label:
                raise RuntimeError("PROMPT_LABEL not set in .env")

            try:
                self._prompt = get_prompt_from_langfuse(
                    "graph.text_to_cypher",
                    langfuse_client=None,
                    label=prompt_label,
                )
            except Exception as err:
                print(
                    f"Langfuse prompt fetch failed ({err}). Using local YAML fallback.",
                    file=sys.stderr,
                )
                self._prompt = _load_local_prompt("graph.text_to_cypher")

            self._params = getattr(self._prompt, "config", None) or {}
        return self._prompt, self._params
    
    async def process_question(
        self,
        question: str,
        execute_cypher: bool = True,
        output_mode: str = "chat",
    ) -> Dict[str, Any]:
        """Process a question and return Cypher query with optional results.
        
        Args:
            question: User's natural language question
            execute_cypher: Whether to execute the generated Cypher
            output_mode: "json", "chat", or "both"
        
        Returns:
            Dictionary with question, cypher, results, summary, examples_used
        """
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self._process_question_sync,
            question,
            execute_cypher,
            output_mode,
        )
        return result
    
    def _process_question_sync(
        self,
        question: str,
        execute_cypher: bool,
        output_mode: str,
    ) -> Dict[str, Any]:
        """Synchronous processing (runs in thread pool)."""
        start_time = time.perf_counter()
        logger.info(
            "GraphRAG: processing question (execute_cypher=%s, output_mode=%s)",
            execute_cypher,
            output_mode,
        )
        # Get schema and terminology
        schema_string = self._get_schema()
        logger.info("GraphRAG: schema loaded (%s chars)", len(schema_string))
        terminology_str = self._get_terminology()
        logger.info("GraphRAG: terminology loaded (%s chars)", len(terminology_str))
        
        # Get prompt
        prompt, params = self._get_prompt()
        logger.info("GraphRAG: prompt loaded (params=%s)", params)
        
        # Track timings for each stage
        timings: Dict[str, float] = {
            "similar_queries": 0.0,
            "generate_cypher": 0.0,
            "query_knowledge_base": 0.0,
            "generate_final_response": 0.0,
        }
        
        # Get similar examples using vector search (optional)
        include_examples = os.environ.get("INCLUDE_FEWSHOT_EXAMPLES", "true").lower() in {"1", "true", "yes"}
        examples_str = ""
        examples_used = []
        use_vector_search = include_examples and os.environ.get("USE_VECTOR_SEARCH", "").lower() in {"1", "true", "yes"}
        
        if not include_examples:
            logger.info("GraphRAG: few-shot examples disabled via INCLUDE_FEWSHOT_EXAMPLES")
        elif use_vector_search:
            try:
                stage_start = time.perf_counter()
                top_k = int(os.environ.get("VECTOR_SEARCH_TOP_K", "5"))
                logger.debug("GraphRAG: running vector search (top_k=%s)", top_k)
                vector_store_start = time.perf_counter()
                logger.info("GraphRAG: initializing vector store instance...")
                vector_store = get_vector_store()
                logger.info(
                    "GraphRAG: vector store ready in %.2fs (model=%s, index=%s)",
                    time.perf_counter() - vector_store_start,
                    getattr(vector_store, "embedding_model", "unknown"),
                    getattr(vector_store, "index_name", "unknown"),
                )
                results = vector_store.search(query=question, top_k=top_k)
                if results:
                    examples_used = [
                        {
                            "question": ex["question"],
                            "cypher": ex["cypher"],
                            "similarity": float(sim),
                        }
                        for ex, sim in results
                    ]
                    examples_str = vector_store.get_examples_text(query=question, top_k=top_k)
                    logger.info(
                        "GraphRAG: vector search returned %s examples",
                        len(examples_used),
                    )
                timings["similar_queries"] = time.perf_counter() - stage_start
            except Exception as e:
                # Fallback to static examples
                logger.warning("GraphRAG: vector search failed (%s), falling back to static examples", e)
                with open("/tmp/graphrag_vector_error.log", "a", encoding="utf-8") as out:
                    out.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {type(e).__name__}: {e}\n")
                    out.flush()
                from ai.fewshots.loader import load_text as load_examples_text
                examples_str = load_examples_text(
                    "v1", prompt_id="graph.text_to_cypher", include_tags=None, limit=None
                )
        
        if include_examples and not examples_str:
            from ai.fewshots.loader import load_text as load_examples_text
            examples_str = load_examples_text(
                "v1", prompt_id="graph.text_to_cypher", include_tags=None, limit=None
            )
            logger.info("GraphRAG: loaded fallback static examples")
        elif not include_examples:
            logger.info("GraphRAG: proceeding without few-shot examples")
        
        # Compile prompt
        rendered = prompt.compile(
            schema=schema_string,
            terminology=terminology_str,
            examples=examples_str,
            question=question,
        )
        
        # Get model configuration
        model = os.environ.get("OPENAI_MODEL") or os.environ.get("OPEN_AI_MODEL")
        if not model:
            raise RuntimeError("OPENAI_MODEL not set in .env")
        
        temperature = float(params.get("temperature", 0.0))
        max_tokens = int(params.get("max_tokens", 1200))
        
        # Generate Cypher
        logger.info(
            "GraphRAG: invoking LLM for Cypher generation (model=%s, temperature=%s, max_tokens=%s)",
            model,
            temperature,
            max_tokens,
        )
        llm_start = time.perf_counter()
        try:
            cypher = create_completion(
                rendered,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                langfuse_prompt=prompt,
            ).strip()
            timings["generate_cypher"] = time.perf_counter() - llm_start
            logger.info(
                "GraphRAG: LLM returned Cypher in %.2fs (length=%s chars)",
                time.perf_counter() - llm_start,
                len(cypher),
            )
        except Exception as exc:
            logger.exception("GraphRAG: LLM call for Cypher failed: %s", exc)
            raise
        
        result = {
            "question": question,
            "cypher": cypher,
            "results": None,
            "summary": None,
            "examples_used": examples_used if examples_used else None,
            "timings": timings,
        }
        
        # Execute Cypher if requested
        if execute_cypher and cypher:
            try:
                logger.info("GraphRAG: executing Cypher against Neo4j")
                with get_session() as session:
                    query_start = time.perf_counter()
                    query_result = session.run(cypher)
                    rows = [record.data() for record in query_result]
                    timings["query_knowledge_base"] = time.perf_counter() - query_start
                    logger.info(
                        "GraphRAG: Cypher execution completed in %.2fs (%s rows)",
                        time.perf_counter() - query_start,
                        len(rows),
                    )
                    
                    if output_mode in {"json", "both"}:
                        result["results"] = rows
                    
                    if output_mode in {"chat", "both"}:
                        # Generate summary
                        try:
                            summary_prompt = get_prompt_from_langfuse(
                                "graph-result-summarizer",
                                label=os.environ.get("PROMPT_LABEL"),
                            )
                        except Exception as err:
                            print(
                                f"Langfuse summary prompt fetch failed ({err}). "
                                "Using local YAML fallback.",
                                file=sys.stderr,
                            )
                            summary_prompt = _load_local_prompt("graph.result_summarizer")
                        summary_params = getattr(summary_prompt, "config", None) or {}
                        summary_temp = float(summary_params.get("temperature", 0.0))
                        summary_max_tokens = int(summary_params.get("max_tokens", 600))
                        
                        preview = rows[:10] if isinstance(rows, list) else rows
                        summary_rendered = summary_prompt.compile(
                            question=question,
                            cypher=cypher,
                            results=json.dumps(preview, ensure_ascii=False),
                        )
                        
                        logger.info(
                            "GraphRAG: invoking LLM for summary (model=%s, max_tokens=%s)",
                            model,
                            summary_max_tokens,
                        )
                        summary_start = time.perf_counter()
                        result["summary"] = create_completion(
                            summary_rendered,
                            model=model,
                            temperature=summary_temp,
                            max_tokens=summary_max_tokens,
                            langfuse_prompt=summary_prompt,
                        )
                        timings["generate_final_response"] = time.perf_counter() - summary_start
                        logger.info(
                            "GraphRAG: summary LLM completed in %.2fs",
                            time.perf_counter() - summary_start,
                        )
            except Exception as e:
                result["error"] = str(e)
                logger.exception("GraphRAG: error executing Cypher or summarizing: %s", e)
        
        logger.info(
            "GraphRAG: finished processing question in %.2fs",
            time.perf_counter() - start_time,
        )
        return result
    
    async def process_question_stream(
        self,
        question: str,
        execute_cypher: bool = True,
        output_mode: str = "chat",
    ) -> AsyncIterator[Dict[str, Any]]:
        """Process a question with streaming responses.
        
        Yields:
            Dictionary chunks with type and data
        """
        # Send status updates
        yield {"type": "status", "message": "Finding similar examples..."}
        
        # Process question (non-streaming for now, can be enhanced)
        result = await self.process_question(question, execute_cypher, output_mode)
        
        # Stream results back
        if result.get("examples_used"):
            yield {
                "type": "examples",
                "data": result["examples_used"],
            }
        
        yield {
            "type": "cypher",
            "data": result["cypher"],
        }
        
        if result.get("results"):
            yield {
                "type": "results",
                "data": result["results"],
            }
        
        if result.get("summary"):
            yield {
                "type": "summary",
                "data": result["summary"],
            }
        
        if result.get("error"):
            yield {
                "type": "error",
                "data": result["error"],
            }

