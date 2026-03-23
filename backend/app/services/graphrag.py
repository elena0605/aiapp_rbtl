"""GraphRAG service - wraps existing text_to_cypher logic with intent routing."""

import asyncio
import os
import sys
from functools import lru_cache, partial
from pathlib import Path
from typing import Dict, Any, List, Optional, AsyncIterator
import json
import re
import logging
import time

import yaml

# Add project root to path (go up from backend/app/services/graphrag.py to project root)
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PROMPTS_DIR = ROOT / "ai" / "prompts"

from utils.neo4j import get_session
from utils.cypher_validator import validate_cypher, CypherValidationError, ReadOnlyViolationError
from ai.schema.schema_utils import get_cached_schema, fetch_schema_from_neo4j
from ai.terminology.loader import load as load_terminology, as_text as terminology_as_text
from ai.fewshots.vector_store import get_vector_store
from ai.llmops.langfuse_client import create_completion, get_prompt_from_langfuse

# Optional: Graph analytics agent (only imported if needed)
try:
    from ai.agent import GraphAnalyticsAgent, GraphAnalyticsAgentError
    ANALYTICS_AVAILABLE = True
except ImportError as e:
    ANALYTICS_AVAILABLE = False
    GraphAnalyticsAgent = None
    GraphAnalyticsAgentError = None
    import logging
    _temp_logger = logging.getLogger("GraphRAGService")
    _temp_logger.warning(f"Graph analytics agent import failed: {e}")
except Exception as e:
    ANALYTICS_AVAILABLE = False
    GraphAnalyticsAgent = None
    GraphAnalyticsAgentError = None
    import logging
    _temp_logger = logging.getLogger("GraphRAGService")
    _temp_logger.warning(f"Graph analytics agent import failed (non-ImportError): {e}")

# Optional: Intent router
try:
    from ai.agent.intent_router import IntentRouter, IntentResult
    INTENT_ROUTER_AVAILABLE = True
except ImportError as e:
    INTENT_ROUTER_AVAILABLE = False
    IntentRouter = None  # type: ignore[misc, assignment]
    IntentResult = None  # type: ignore[misc, assignment]
    import logging
    _temp_logger2 = logging.getLogger("GraphRAGService")
    _temp_logger2.warning(f"Intent router import failed: {e}")
except Exception as e:
    INTENT_ROUTER_AVAILABLE = False
    IntentRouter = None  # type: ignore[misc, assignment]
    IntentResult = None  # type: ignore[misc, assignment]
    import logging
    _temp_logger2 = logging.getLogger("GraphRAGService")
    _temp_logger2.warning(f"Intent router import failed (non-ImportError): {e}")

# Optional: Visualization agent
try:
    from ai.agent.visualization_agent import VisualizationAgent, VisualizationSpec
    VISUALIZATION_AVAILABLE = True
except Exception as e:
    VISUALIZATION_AVAILABLE = False
    VisualizationAgent = None  # type: ignore[misc, assignment]
    VisualizationSpec = None  # type: ignore[misc, assignment]

# Guardrails (lightweight — should always be available)
try:
    from ai.agent import guardrails as guardrails_module
    GUARDRAILS_AVAILABLE = True
except Exception:
    GUARDRAILS_AVAILABLE = False
    guardrails_module = None  # type: ignore[assignment]

logger = logging.getLogger("GraphRAGService")

# Log availability on module load
if ANALYTICS_AVAILABLE:
    logger.info("Graph analytics agent is available")
else:
    logger.warning("Graph analytics agent is NOT available (import failed)")

if INTENT_ROUTER_AVAILABLE:
    logger.info("Intent router is available")
else:
    logger.warning("Intent router is NOT available (import failed)")

if VISUALIZATION_AVAILABLE:
    logger.info("Visualization agent is available")
else:
    logger.warning("Visualization agent is NOT available")


_PROMPT_VAR_PATTERN = re.compile(r"{{\s*(\w+)\s*}}")


def _convert_neo4j_temporal_to_string(obj: Any) -> Any:
    """Recursively convert Neo4j temporal types (DateTime, Date, Time, Duration) to strings.
    
    This ensures JSON serialization works correctly for Neo4j query results.
    Even if the prompt instructs to use toString() in Cypher, this provides a safety net
    for any DateTime objects that might still be returned.
    """
    try:
        # Check if it's a Neo4j temporal type
        from neo4j.time import DateTime, Date, Time, Duration
        
        if isinstance(obj, (DateTime, Date, Time, Duration)):
            return str(obj)
    except ImportError:
        # Neo4j types not available, skip conversion
        pass
    
    # Handle dictionaries
    if isinstance(obj, dict):
        return {key: _convert_neo4j_temporal_to_string(value) for key, value in obj.items()}
    
    # Handle lists
    if isinstance(obj, list):
        return [_convert_neo4j_temporal_to_string(item) for item in obj]
    
    # Return as-is for other types
    return obj


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
        self._analytics_agent = None
        self._intent_router = None
        self._visualization_agent = None
        self._discussion_prompt = None
    
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
    
    def _get_analytics_agent(self):
        """Get or create analytics agent (lazy initialization)."""
        if not ANALYTICS_AVAILABLE:
            return None
        if self._analytics_agent is None:
            self._analytics_agent = GraphAnalyticsAgent(use_llm_selector=True)
        return self._analytics_agent

    def _get_intent_router(self):
        """Get or create intent router (lazy initialization)."""
        if not INTENT_ROUTER_AVAILABLE:
            return None
        if self._intent_router is None:
            try:
                self._intent_router = IntentRouter()
            except Exception as e:
                logger.warning("Failed to initialize IntentRouter: %s", e)
                return None
        return self._intent_router

    def _get_visualization_agent(self):
        """Get or create visualization agent (lazy initialization)."""
        if not VISUALIZATION_AVAILABLE:
            return None
        if self._visualization_agent is None:
            try:
                self._visualization_agent = VisualizationAgent()
            except Exception as e:
                logger.warning("Failed to initialize VisualizationAgent: %s", e)
                return None
        return self._visualization_agent

    def _get_discussion_prompt(self):
        """Load discussion prompt (Langfuse with local YAML fallback)."""
        if self._discussion_prompt is not None:
            return self._discussion_prompt

        prompt_label = os.environ.get("PROMPT_LABEL")
        try:
            self._discussion_prompt = get_prompt_from_langfuse(
                "graph.discussion",
                langfuse_client=None,
                label=prompt_label,
            )
        except Exception as err:
            logger.warning(
                "Langfuse prompt fetch for discussion failed (%s). "
                "Using local YAML fallback.",
                err,
            )
            self._discussion_prompt = self._load_local_prompt("graph.discussion")
        return self._discussion_prompt

    def _load_local_prompt(self, prompt_id: str):
        """Load a prompt from local YAML files by id."""
        import re as _re

        _PROMPT_VAR_PATTERN = _re.compile(r"{{\s*(\w+)\s*}}")

        for path in PROMPTS_DIR.glob("*.yaml"):
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
            except Exception as exc:
                logger.debug("Skipping unparseable YAML file %s: %s", path, exc)
                continue
            if not isinstance(data, dict):
                continue
            if data.get("id") != prompt_id:
                continue
            template = data.get("template")
            if not template:
                logger.warning("Prompt file '%s' has no template.", path)
                return None
            params = data.get("params") or {}

            class _LocalPrompt:
                def __init__(self, tmpl, cfg):
                    self._template = tmpl
                    self.config = cfg

                def compile(self, **kwargs):
                    def _sub(m):
                        val = kwargs.get(m.group(1), "")
                        if val is None:
                            return ""
                        if isinstance(val, (dict, list)):
                            import json as _json
                            return _json.dumps(val, ensure_ascii=False)
                        return str(val)
                    return _PROMPT_VAR_PATTERN.sub(_sub, self._template)

            return _LocalPrompt(template, params)

        logger.warning("Prompt '%s' not found in local YAML files.", prompt_id)
        return None

    async def process_question(
        self,
        question: str,
        execute_cypher: bool = True,
        output_mode: str = "chat",
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Process a question with intent-based routing.

        Routing pipeline:
        1. Classify intent (graph_query / analytics / off_topic / chitchat /
           follow_up).  Follow-ups are rewritten into self-contained questions.
        2. Route to the appropriate handler based on classified intent.
        3. Fall back to text-to-Cypher when the intent router is
           unavailable or fails.

        Args:
            question: User's natural language question.
            execute_cypher: Whether to execute the generated Cypher.
            output_mode: "json", "chat", or "both".
            conversation_history: Recent messages for context (list of dicts
                with ``role`` and ``content``).

        Returns:
            Dictionary with question, cypher (or tool_name), results,
            summary, examples_used, and routing metadata.
        """
        history = conversation_history or []

        # ── Guardrails (cheap, runs first) ───────────────────────────
        if GUARDRAILS_AVAILABLE:
            guard_result = guardrails_module.check(question)
            if not guard_result.passed:
                logger.info(
                    "GraphRAG: guardrail blocked question (category=%s)",
                    guard_result.category,
                )
                return {
                    "question": question,
                    "route_type": "guardrail",
                    "intent": "blocked",
                    "cypher": None,
                    "results": None,
                    "summary": guard_result.reason,
                    "examples_used": None,
                    "error": None,
                    "timings": {},
                }

        # ── Intent routing (when available) ──────────────────────────
        use_intent_routing = os.environ.get(
            "ENABLE_INTENT_ROUTER", "true"
        ).lower() in {"1", "true", "yes"}

        router = self._get_intent_router() if use_intent_routing else None

        if router is not None:
            try:
                intent_result = await router.classify(question, history)
                logger.info(
                    "GraphRAG: intent=%s confidence=%.2f is_follow_up=%s effective_q=%r",
                    intent_result.intent,
                    intent_result.confidence,
                    intent_result.is_follow_up,
                    intent_result.effective_question,
                )

                effective_q = intent_result.effective_question

                # ── Off-topic ────────────────────────────────────────
                if intent_result.intent == "off_topic":
                    return self._handle_off_topic(question, intent_result)

                # ── Chitchat ─────────────────────────────────────────
                if intent_result.intent == "chitchat":
                    return self._handle_chitchat(question, intent_result, history)

                # ── Discussion ──────────────────────────────────────
                if intent_result.intent == "discussion":
                    return await self._handle_discussion(
                        effective_q, intent_result, history,
                    )

                # ── Analytics ────────────────────────────────────────
                if intent_result.intent == "analytics":
                    if ANALYTICS_AVAILABLE:
                        analytics_result = await self._handle_analytics(effective_q)
                        if analytics_result is not None:
                            analytics_result["intent"] = intent_result.intent
                            analytics_result["intent_confidence"] = intent_result.confidence
                            return analytics_result
                        logger.info(
                            "GraphRAG: analytics agent returned no result, "
                            "falling back to Cypher"
                        )
                    else:
                        logger.warning(
                            "GraphRAG: intent classified as analytics but "
                            "analytics agent is not available; falling back to Cypher"
                        )

                # ── Visualization ─────────────────────────────────────
                if intent_result.intent == "visualization":
                    viz_result = await self._handle_visualization(
                        effective_q, execute_cypher, output_mode, history,
                    )
                    if viz_result is not None:
                        viz_result["intent"] = intent_result.intent
                        viz_result["intent_confidence"] = intent_result.confidence
                        if intent_result.rewritten_question:
                            viz_result["original_question"] = question
                            viz_result["rewritten_question"] = (
                                intent_result.rewritten_question
                            )
                        return viz_result
                    logger.info(
                        "GraphRAG: visualization handler returned None, "
                        "falling back to Cypher"
                    )

                # ── Graph query (and follow-up after rewrite) ────────
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    partial(
                        self._process_question_sync,
                        effective_q,
                        execute_cypher,
                        output_mode,
                        conversation_history=history,
                    ),
                )
                result["intent"] = intent_result.intent
                result["intent_confidence"] = intent_result.confidence
                if intent_result.rewritten_question:
                    result["original_question"] = question
                    result["rewritten_question"] = intent_result.rewritten_question
                return result

            except Exception as e:
                logger.warning(
                    "GraphRAG: intent routing failed (%s), falling through "
                    "to direct Cypher generation",
                    e,
                    exc_info=True,
                )

        # ── Fallback: direct text-to-Cypher (no intent routing) ──────
        logger.info("GraphRAG: using direct Cypher generation (no intent routing)")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            partial(
                self._process_question_sync,
                question,
                execute_cypher,
                output_mode,
                conversation_history=history,
            ),
        )
        return result

    # ── Route handlers ───────────────────────────────────────────────

    async def _handle_analytics(self, question: str) -> Optional[Dict[str, Any]]:
        """Try the analytics agent; return *None* when no tool matches."""
        agent = self._get_analytics_agent()
        if agent is None:
            return None
        try:
            logger.info("GraphRAG: running analytics agent for %r", question)
            analytics_result = await agent.run(question)
            logger.info(
                "GraphRAG: analytics agent succeeded (tool=%s)",
                analytics_result.tool_name,
            )
            converted_results = _convert_neo4j_temporal_to_string(
                analytics_result.raw_result
            )
            return {
                "question": question,
                "route_type": "analytics",
                "tool_name": analytics_result.tool_name,
                "tool_inputs": analytics_result.inputs,
                "results": converted_results,
                "summary": analytics_result.summary,
                "examples_used": None,
                "cypher": None,
                "error": None,
                "timings": {},
            }
        except GraphAnalyticsAgentError as e:
            logger.info("GraphRAG: analytics agent found no tool: %s", e)
            return None
        except Exception as e:
            logger.warning("GraphRAG: analytics agent error: %s", e, exc_info=True)
            return None

    async def _handle_visualization(
        self,
        question: str,
        execute_cypher: bool,
        output_mode: str,
        history: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Run text-to-cypher, then generate a visualization spec from results.

        Returns ``None`` if visualization processing fails so the caller can
        fall back to a plain graph_query.
        """
        viz_agent = self._get_visualization_agent()
        if viz_agent is None:
            logger.warning("GraphRAG: visualization agent not available")
            return None

        # Step 1: generate Cypher and get results (reuse the sync pipeline)
        loop = asyncio.get_event_loop()
        cypher_result = await loop.run_in_executor(
            None,
            partial(
                self._process_question_sync,
                question,
                execute_cypher,
                "both",  # need raw results for viz
                conversation_history=history,
            ),
        )

        if cypher_result.get("error"):
            return cypher_result

        results = cypher_result.get("results") or []
        cypher = cypher_result.get("cypher") or ""

        if not results:
            cypher_result["route_type"] = "visualization"
            cypher_result["visualization"] = {
                "chart_type": "table",
                "title": "No Data",
                "description": "The query returned no results to visualize.",
                "data": {"columns": [], "rows": []},
                "summary": "No results found.",
            }
            return cypher_result

        # Step 2: generate the visualization spec via LLM
        try:
            viz_spec = viz_agent.generate_spec(question, cypher, results)
            cypher_result["route_type"] = "visualization"
            cypher_result["visualization"] = {
                "chart_type": viz_spec.chart_type,
                "title": viz_spec.title,
                "description": viz_spec.description,
                "data": viz_spec.data,
                "axes": viz_spec.axes,
                "summary": viz_spec.summary,
            }
            # Use the viz summary as the chat summary if present
            if viz_spec.summary:
                cypher_result["summary"] = viz_spec.summary
            return cypher_result
        except Exception as e:
            logger.warning(
                "GraphRAG: visualization generation failed: %s", e, exc_info=True
            )
            return None

    @staticmethod
    def _handle_off_topic(
        question: str, intent_result: Any
    ) -> Dict[str, Any]:
        """Return a polite refusal for off-topic questions."""
        return {
            "question": question,
            "route_type": "off_topic",
            "intent": "off_topic",
            "intent_confidence": intent_result.confidence,
            "cypher": None,
            "results": None,
            "summary": (
                "I'm sorry, but that question falls outside the scope of this "
                "knowledge base. I can help you explore youth health data, "
                "social media influencer analytics, and geographic/demographic "
                "information for areas in the Netherlands. "
                "Feel free to ask me something related to these topics!"
            ),
            "examples_used": None,
            "error": None,
            "timings": {},
        }

    @staticmethod
    def _handle_chitchat(
        question: str,
        intent_result: Any,
        history: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Return a friendly conversational response for greetings etc."""
        q_lower = question.strip().lower().rstrip("!.")

        if any(g in q_lower for g in ("hi", "hello", "hey", "good morning", "good afternoon")):
            reply = (
                "Hello! I'm your knowledge graph assistant. You can ask me "
                "about youth health survey data, social media influencers, "
                "or geographic demographics in the Netherlands. "
                "What would you like to explore?"
            )
        elif any(t in q_lower for t in ("thank", "thanks", "thx")):
            reply = "You're welcome! Let me know if you have more questions."
        elif any(b in q_lower for b in ("bye", "goodbye", "see you")):
            reply = "Goodbye! Feel free to come back anytime."
        else:
            reply = (
                "I'm here to help you explore the knowledge graph. "
                "Ask me a question about the data and I'll do my best!"
            )

        return {
            "question": question,
            "route_type": "chitchat",
            "intent": "chitchat",
            "intent_confidence": intent_result.confidence,
            "cypher": None,
            "results": None,
            "summary": reply,
            "examples_used": None,
            "error": None,
            "timings": {},
        }

    async def _handle_discussion(
        self,
        question: str,
        intent_result: Any,
        history: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Use the LLM to reason about prior results or give data analysis advice."""
        start = time.perf_counter()

        prompt_obj = self._get_discussion_prompt()
        if prompt_obj is None:
            return {
                "question": question,
                "route_type": "discussion",
                "intent": "discussion",
                "intent_confidence": intent_result.confidence,
                "cypher": None,
                "results": None,
                "summary": (
                    "I'd like to help discuss the data, but the discussion "
                    "prompt is not configured. Please try asking a data question instead."
                ),
                "examples_used": None,
                "error": None,
                "timings": {},
            }

        from ai.agent.intent_router import IntentRouter, DOMAIN_DESCRIPTION

        history_text = IntentRouter.format_history_with_budget(
            history, max_chars=4000, recent_full=6,
        )

        rendered = prompt_obj.compile(
            domain_description=DOMAIN_DESCRIPTION,
            conversation_history=history_text,
            question=question,
        )

        loop = asyncio.get_event_loop()
        model = os.environ.get("OPENAI_MODEL") or os.environ.get("OPEN_AI_MODEL", "gpt-4o")
        try:
            reply = await loop.run_in_executor(
                None,
                partial(
                    create_completion,
                    rendered,
                    model=model,
                    temperature=0.3,
                    max_tokens=800,
                ),
            )
        except Exception as exc:
            logger.warning("Discussion LLM call failed: %s", exc)
            reply = (
                "I encountered an error while reasoning about the data. "
                "Please try rephrasing your question or ask a new data query."
            )

        elapsed = time.perf_counter() - start
        logger.info("GraphRAG: discussion response generated in %.2fs", elapsed)

        return {
            "question": question,
            "route_type": "discussion",
            "intent": "discussion",
            "intent_confidence": intent_result.confidence,
            "cypher": None,
            "results": None,
            "summary": reply.strip() if reply else "I couldn't generate a response.",
            "examples_used": None,
            "error": None,
            "timings": {"discussion_llm": round(elapsed, 3)},
        }

    def _process_question_sync(
        self,
        question: str,
        execute_cypher: bool,
        output_mode: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
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

        # Build conversation context for the Cypher prompt
        conversation_context = "(no prior conversation)"
        if conversation_history and INTENT_ROUTER_AVAILABLE:
            try:
                conversation_context = IntentRouter.format_history_for_cypher(
                    conversation_history, max_pairs=3
                )
            except Exception as e:
                logger.warning("GraphRAG: failed to format history for cypher: %s", e)

        # Compile prompt (includes conversation_context; the template treats
        # it as optional — if the variable is missing from the template the
        # _LocalPrompt.compile silently drops it, so this is backwards-compatible
        # with v1 of the prompt that doesn't have {{conversation_context}}).
        rendered = prompt.compile(
            schema=schema_string,
            terminology=terminology_str,
            examples=examples_str,
            conversation_context=conversation_context,
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
            "route_type": "cypher",  # Indicate this used Cypher
            "cypher": cypher,
            "results": None,
            "summary": None,
            "examples_used": examples_used if examples_used else None,
            "timings": timings,
        }
        
        # Check if query is empty (LLM might have refused to generate write query or semantically invalid query)
        if not cypher or not cypher.strip():
            logger.warning("GraphRAG: LLM returned empty Cypher query - may have refused to generate write operation or query references non-existent schema elements")
            error_message = "Cannot generate query for this request. The question may reference concepts that don't exist in the database schema, or it may require write operations which are not allowed. Only read-only queries that match the schema are supported."
            result["error"] = error_message
            result["summary"] = None  # Explicitly set summary to None when there's an error
            result["cypher"] = None
            logger.info(f"GraphRAG: Returning error response: {error_message}")
            return result
        
        # Validate query before execution (includes read-only check)
        # This validation happens even if we don't execute, to catch any write operations
        logger.info("GraphRAG: validating Cypher query")
        try:
            is_valid, validation_details = validate_cypher(cypher, strict=True, enforce_read_only=True)
            if not is_valid:
                raise CypherValidationError(
                    "Cypher query validation failed",
                    validation_details
                )
            logger.info("GraphRAG: Cypher query validation passed")
        except (CypherValidationError, ReadOnlyViolationError) as ve:
            logger.error(
                "GraphRAG: Cypher validation failed: %s (details: %s)",
                ve,
                ve.validation_details
            )
            error_msg = str(ve)
            if isinstance(ve, ReadOnlyViolationError):
                error_msg = f"Read-only violation: {error_msg}"
            result["error"] = error_msg
            result["validation_details"] = ve.validation_details
            result["cypher"] = cypher  # Include the generated query in response for debugging
            return result
        except Exception as e:
            # If validation is unavailable (e.g., CyVer not installed), log warning but continue
            logger.warning("GraphRAG: Cypher validation skipped: %s", e)
        
        # Execute Cypher if requested (validation already done above)
        if execute_cypher and cypher:
            try:
                logger.info("GraphRAG: executing Cypher against Neo4j")
                with get_session() as session:
                    query_start = time.perf_counter()
                    query_result = session.run(cypher)
                    rows = [record.data() for record in query_result]
                    # Convert Neo4j temporal types to strings for JSON serialization
                    rows = [_convert_neo4j_temporal_to_string(row) for row in rows]
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
                        summary_max_tokens = int(summary_params.get("max_tokens", 1200))
                        
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
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Process a question with streaming responses.
        
        Yields:
            Dictionary chunks with type and data
        """
        yield {"type": "status", "message": "Classifying intent..."}

        result = await self.process_question(
            question,
            execute_cypher,
            output_mode,
            conversation_history=conversation_history,
        )

        # Emit intent info if available
        if result.get("intent"):
            yield {
                "type": "intent",
                "data": {
                    "intent": result["intent"],
                    "confidence": result.get("intent_confidence"),
                    "rewritten_question": result.get("rewritten_question"),
                },
            }

        if result.get("examples_used"):
            yield {
                "type": "examples",
                "data": result["examples_used"],
            }

        if result.get("cypher"):
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

