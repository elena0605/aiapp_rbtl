from pathlib import Path
import os
import sys

# Ensure project root is on sys.path for absolute imports
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils_neo4j import get_driver, close_driver, get_session
from ai.schema.schema_utils import get_cached_schema, fetch_schema_from_neo4j
from ai.terminology.loader import load as load_terminology, as_text as terminology_as_text
from ai.examples.loader import load_text as load_examples_text
from ai.llmops.langfuse_client import create_completion, get_prompt_from_langfuse
from openai import OpenAI  # type: ignore
from dotenv import load_dotenv  # type: ignore


def run_cypher(query: str):
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
    prompt_label = os.environ.get("PROMPT_LABEL", "production")
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
    if any(arg in {"--schema", "-s"} for arg in sys.argv[1:]) or \
       str(os.environ.get("SCHEMA_ONLY", "")).lower() in {"1", "true", "yes"}:
        print(schema_string)
        return

    # 2) Load terminology and examples as text blocks
    terminology_dict = load_terminology("v1")
    terminology_str = terminology_as_text(terminology_dict)

    examples_str = load_examples_text(
        "v1", prompt_id="graph.text_to_cypher", include_tags=None, limit=None
    )

    # 3) Load prompt from Langfuse (single source of truth)
    try:
        prompt_label = os.environ.get("PROMPT_LABEL", "production")
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
        question = os.environ.get("QUESTION", "Return 10 A to B relationships")

    # Compile prompt with variables using Langfuse's compile method
    rendered = prompt.compile(
        schema=schema_string,
        terminology=terminology_str,
        examples=examples_str,
        question=question,
    )

    # Optionally debug-print the rendered prompt
    if os.environ.get("DEBUG_PROMPT", "").lower() in {"1", "true", "yes"}:
        print(rendered)

    # 4) If OpenAI is available and API key is set, call the model
    # Prefer OPEN_AI_* (project naming), fallback to OPENAI_* (SDK naming)
    api_key = os.environ.get("OPENAI_API_KEY")
    if OpenAI is not None and api_key:
        model = (
            os.environ.get("OPEN_AI_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or "gpt-4o"
        )
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