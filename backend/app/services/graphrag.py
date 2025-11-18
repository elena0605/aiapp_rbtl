"""GraphRAG service - wraps existing text_to_cypher logic."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, AsyncIterator
import json

# Add project root to path (go up from backend/app/services/graphrag.py to project root)
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils_neo4j import get_session
from ai.schema.schema_utils import get_cached_schema, fetch_schema_from_neo4j
from ai.terminology.loader import load as load_terminology, as_text as terminology_as_text
from ai.fewshots.vector_store import get_vector_store
from ai.llmops.langfuse_client import create_completion, get_prompt_from_langfuse


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
            
            self._prompt = get_prompt_from_langfuse(
                "graph.text_to_cypher",
                langfuse_client=None,
                label=prompt_label,
            )
            self._params = self._prompt.config or {}
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
        # Get schema and terminology
        schema_string = self._get_schema()
        terminology_str = self._get_terminology()
        
        # Get prompt
        prompt, params = self._get_prompt()
        
        # Get similar examples using vector search
        examples_str = ""
        examples_used = []
        use_vector_search = os.environ.get("USE_VECTOR_SEARCH", "").lower() in {"1", "true", "yes"}
        
        if use_vector_search:
            try:
                top_k = int(os.environ.get("VECTOR_SEARCH_TOP_K", "5"))
                vector_store = get_vector_store()
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
            except Exception as e:
                # Fallback to static examples
                from ai.fewshots.loader import load_text as load_examples_text
                examples_str = load_examples_text(
                    "v1", prompt_id="graph.text_to_cypher", include_tags=None, limit=None
                )
        
        if not examples_str:
            from ai.fewshots.loader import load_text as load_examples_text
            examples_str = load_examples_text(
                "v1", prompt_id="graph.text_to_cypher", include_tags=None, limit=None
            )
        
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
        cypher = create_completion(
            rendered,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            langfuse_prompt=prompt,
        ).strip()
        
        result = {
            "question": question,
            "cypher": cypher,
            "results": None,
            "summary": None,
            "examples_used": examples_used if examples_used else None,
        }
        
        # Execute Cypher if requested
        if execute_cypher and cypher:
            try:
                with get_session() as session:
                    query_result = session.run(cypher)
                    rows = [record.data() for record in query_result]
                    
                    if output_mode in {"json", "both"}:
                        result["results"] = rows
                    
                    if output_mode in {"chat", "both"}:
                        # Generate summary
                        summary_prompt = get_prompt_from_langfuse(
                            "graph-result-summarizer",
                            label=os.environ.get("PROMPT_LABEL"),
                        )
                        summary_params = summary_prompt.config or {}
                        summary_temp = float(summary_params.get("temperature", 0.0))
                        summary_max_tokens = int(summary_params.get("max_tokens", 600))
                        
                        preview = rows[:10] if isinstance(rows, list) else rows
                        summary_rendered = summary_prompt.compile(
                            question=question,
                            cypher=cypher,
                            results=json.dumps(preview, ensure_ascii=False),
                        )
                        
                        result["summary"] = create_completion(
                            summary_rendered,
                            model=model,
                            temperature=summary_temp,
                            max_tokens=summary_max_tokens,
                            langfuse_prompt=summary_prompt,
                        )
            except Exception as e:
                result["error"] = str(e)
        
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

