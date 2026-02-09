from pathlib import Path
import os
import sys

# Ensure project root is on sys.path for absolute imports
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.neo4j import get_driver, close_driver, get_session
from utils.cypher_validator import validate_cypher, CypherValidationError, ReadOnlyViolationError
from ai.schema.schema_utils import get_cached_schema, fetch_schema_from_neo4j
from ai.terminology.loader import load as load_terminology, as_text as terminology_as_text
from ai.fewshots.loader import load_text as load_examples_text
from ai.fewshots.vector_store import get_vector_store
from ai.llmops.langfuse_client import create_completion, get_prompt_from_langfuse
from openai import OpenAI  # type: ignore
from dotenv import load_dotenv  # type: ignore


def run_cypher(query: str):
    """Execute a Cypher query after validation.
    
    Validates the query using CyVer before execution. If validation fails,
    raises CypherValidationError. If CyVer is not available, raises RuntimeError
    unless SKIP_CYPHER_VALIDATION environment variable is set.
    """
    # Check if validation should be skipped
    skip_validation = os.environ.get("SKIP_CYPHER_VALIDATION", "").lower() in {"1", "true", "yes"}
    
    if not skip_validation:
        # Validate query before execution (includes read-only check)
        try:
            is_valid, validation_details = validate_cypher(query, strict=True, enforce_read_only=True)
            if not is_valid:
                raise CypherValidationError(
                    "Cypher query validation failed",
                    validation_details
                )
        except (CypherValidationError, ReadOnlyViolationError):
            # Re-raise validation errors (including read-only violations)
            raise
        except RuntimeError as e:
            # If CyVer is not installed and validation is required, raise error
            error_msg = str(e)
            if "not installed" in error_msg or "not available" in error_msg.lower():
                raise RuntimeError(
                    f"Cypher validation is required but CyVer is not available: {e}. "
                    "Install with: pip install CyVer, or set SKIP_CYPHER_VALIDATION=true to skip validation."
                ) from e
            raise
    
    # Open a new session and execute the query, return list of dict rows
    with get_session() as session:  # type: ignore
        result = session.run(query)
        return [record.data() for record in result]


def summarize_results(question: str, cypher: str, rows) -> str:
    """Summarize Cypher query results using LLM.
    
    Uses Langfuse prompt management for the summarization prompt.
    Falls back to naive summary if LLM is not available.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if OpenAI is None or not api_key:
        # Fallback naive summary
        if not rows:
            return "No results found."
        if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict) and len(rows[0]) == 1:
            key, value = next(iter(rows[0].items()))
            return f"{key}: {value}"
        count = len(rows) if isinstance(rows, list) else 0
        return f"Returned {count} rows. Showing first: {rows[:1]}"
    
    # Get model name
    model = os.environ.get("OPENAI_MODEL")
    
    # Fetch summarization prompt from Langfuse
    prompt_label = os.environ.get("PROMPT_LABEL")
    if not prompt_label:
        raise RuntimeError(
            "PROMPT_LABEL not set. Please set PROMPT_LABEL in .env file."
        )
    summary_prompt = get_prompt_from_langfuse("graph-result-summarizer", label=prompt_label)
    params = summary_prompt.config or {}
    temperature = float(params.get("temperature", 0.0))
    max_tokens = int(params.get("max_tokens", 600))
    
    # Compile prompt with variables
    preview = rows[:10] if isinstance(rows, list) else rows
    import json as _json
    rendered = summary_prompt.compile(
        question=question,
        cypher=cypher,
        results=_json.dumps(preview, ensure_ascii=False),
    )
    
    # Use Langfuse tracing for summarization too
    return create_completion(
        rendered,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        langfuse_prompt=summary_prompt,  # Link prompt to observation
    )


def main() -> None:
    # 1) Get schema (formatted string) - cached by default
    # Load .env from project root early so OPEN_AI_KEY/OPEN_AI_MODEL are available
    if load_dotenv is not None:
        try:
            load_dotenv(dotenv_path=str(ROOT / ".env"))
        except Exception:
            pass

    # Fetch schema (from cache or Neo4j based on UPDATE_NEO4J_SCHEMA flag)
    schema_string = get_cached_schema(
        force_update=False,  # Controlled by UPDATE_NEO4J_SCHEMA env var
        fetch_schema_fn=fetch_schema_from_neo4j,
    )

    # Schema-only mode (CLI flag or env var)
    schema_only_env = os.environ.get("SCHEMA_ONLY", "").lower()
    if any(arg in {"--schema", "-s"} for arg in sys.argv[1:]) or \
       schema_only_env in {"1", "true", "yes"}:
        print(schema_string)
        return

    # 2) Load terminology
    terminology_dict = load_terminology("v1")
    terminology_str = terminology_as_text(terminology_dict)

    # 3) Load prompt from Langfuse (single source of truth)
    try:
        prompt_label = os.environ.get("PROMPT_LABEL")
        if not prompt_label:
            raise RuntimeError(
                "PROMPT_LABEL not set. Please set PROMPT_LABEL in .env file."
            )
        prompt = get_prompt_from_langfuse("graph.text_to_cypher", langfuse_client=None, label=prompt_label)
        params = prompt.config or {}
    except Exception as e:
        raise RuntimeError(
            f"Failed to fetch prompt from Langfuse: {e}. "
            "Ensure Langfuse is configured (LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY) "
            "and the prompt has been synced. Run: python3 ai/prompts/sync_prompts.py"
        ) from e

    # Prefer CLI positional argument: python3 text_to_cypher.py "Your question here"
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
    else:
        question = os.environ.get("QUESTION")
        if not question:
            raise RuntimeError(
                "QUESTION not provided. Either pass as command-line argument or set QUESTION in .env file."
            )

    # 4) Load examples using Neo4j vector similarity search or fallback to static examples
    use_vector_search_str = os.environ.get("USE_VECTOR_SEARCH")
    if use_vector_search_str is None:
        raise RuntimeError(
            "USE_VECTOR_SEARCH not set. Please set USE_VECTOR_SEARCH in .env file (true/false)."
        )
    use_vector_search = use_vector_search_str.lower() in {"1", "true", "yes"}
    examples_str = ""
    
    if use_vector_search:
        try:
            # Use Neo4j vector store for similarity search
            top_k_str = os.environ.get("VECTOR_SEARCH_TOP_K")
            if not top_k_str:
                raise RuntimeError(
                    "VECTOR_SEARCH_TOP_K not set. Please set VECTOR_SEARCH_TOP_K in .env file."
                )
            top_k = int(top_k_str)
            vector_store = get_vector_store()
            # Get detailed results with similarity scores
            results = vector_store.search(query=question, top_k=top_k)
            if results:
                print(f"✓ Found {len(results)} similar examples using vector search:")
                for i, (example, similarity) in enumerate(results, 1):
                    print(f"  {i}. [{similarity:.3f}] {example['question']}...")
                # Format examples as text for prompt injection
                examples_str = vector_store.get_examples_text(query=question, top_k=top_k)
            else:
                print("⚠️  No similar examples found, falling back to static examples")
                use_vector_search = False
        except Exception as e:
            print(f"⚠️  Neo4j vector search failed: {e}, falling back to static examples")
            use_vector_search = False
    
    if not use_vector_search or not examples_str:
        # Fallback to static examples from YAML
        examples_str = load_examples_text(
            "v1", prompt_id="graph.text_to_cypher", include_tags=None, limit=None
        )

    # Compile prompt with variables using Langfuse's compile method
    rendered = prompt.compile(
        schema=schema_string,
        terminology=terminology_str,
        examples=examples_str,
        question=question,
    )

    # Optionally debug-print the rendered prompt
    debug_prompt_env = os.environ.get("DEBUG_PROMPT", "").lower()
    if debug_prompt_env in {"1", "true", "yes"}:
        print(rendered)

    # 4) If OpenAI is available and API key is set, call the model
    # Check for Azure OpenAI first, then standard OpenAI
    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    azure_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    
    # Prefer OPEN_AI_* (project naming), fallback to OPENAI_* (SDK naming)
    model = (
        os.environ.get("OPEN_AI_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or "gpt-4o"
    )
    
    if OpenAI is not None and (azure_endpoint and azure_api_key or openai_api_key):
        temperature = float(params.get("temperature", 0.0))
        max_tokens = int(params.get("max_tokens", 1200))

        output = create_completion(
            rendered, 
            model=model, 
            temperature=temperature, 
            max_tokens=max_tokens,
            langfuse_prompt=prompt,  # Link prompt to observation
        )
        print(output)
        # Execute returned Cypher by default; allow opt-out via env flag
        flag = os.environ.get("EXECUTE_CYPHER") or os.environ.get("RUN_CYPHER")
        execute = True if flag is None else str(flag).lower() not in {"0", "false", "no"}
        if execute and output:
            try:
                rows = run_cypher(output)
                mode = (os.environ.get("OUTPUT_MODE") or "json").lower()
                import json as _json
                if mode in {"json", "both"}:
                    print(_json.dumps(rows, indent=2, ensure_ascii=False))
                if mode in {"chat", "both"}:
                    summary = summarize_results(question, output, rows)
                    print(summary)
            except Exception as e:
                print(f"Execution error: {e}", file=sys.stderr)
        return

    # Fallback: if no OpenAI, print the rendered prompt (for inspection/copy-paste)
    print(rendered)


if __name__ == "__main__":
    main()