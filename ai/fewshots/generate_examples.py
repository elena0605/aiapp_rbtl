"""Generate query examples for each category using query-examples-builder prompt from Langfuse.

This script reads query categories from a JSON file and for each category, calls the
query-examples-builder prompt to generate example queries.
"""

from pathlib import Path
import os
import sys
import json
import time
from datetime import datetime

# Ensure project root is on sys.path for absolute imports
# From ai/fewshots/generate_examples.py, go up 2 levels to reach project root
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.llmops.langfuse_client import get_prompt_from_langfuse, create_completion
from ai.schema.schema_utils import get_cached_schema, fetch_schema_from_neo4j
from ai.terminology.loader import load as load_terminology, as_text as terminology_as_text
from dotenv import load_dotenv


def load_categories(categories_file: Path) -> list[dict]:
    """Load categories from JSON file."""
    if not categories_file.exists():
        raise FileNotFoundError(f"Categories file not found: {categories_file}")
    
    content = json.loads(categories_file.read_text())
    
    # Handle different JSON structures
    if isinstance(content, dict) and "categories" in content:
        categories = content["categories"]
    elif isinstance(content, list):
        categories = content
    else:
        raise ValueError(f"Unexpected JSON structure in {categories_file}")
    
    return categories


def load_existing_examples(output_path: Path) -> dict[str, list[dict]]:
    """Load existing query examples from file, organized by category_name.
    
    Returns:
        Dictionary mapping category_name to list of examples
    """
    if not output_path.exists():
        return {}
    
    try:
        content = json.loads(output_path.read_text(encoding="utf-8"))
        if isinstance(content, list):
            # Convert list of {category_name, examples} to dict
            result = {}
            for item in content:
                if isinstance(item, dict) and "category_name" in item:
                    category_name = item["category_name"]
                    examples = item.get("examples", [])
                    result[category_name] = examples
            return result
        elif isinstance(content, dict):
            # If it's already a dict, return as-is
            return content
        else:
            return {}
    except (json.JSONDecodeError, Exception) as e:
        print(f"⚠️  Warning: Could not load existing examples from {output_path}: {e}")
        return {}


def merge_examples(existing: list[dict], new: list[dict]) -> list[dict]:
    """Merge new examples with existing ones, avoiding exact duplicates.
    
    Args:
        existing: List of existing examples (may have timestamps)
        new: List of new examples (will have timestamps added)
    
    Returns:
        Merged list with all unique examples
    """
    # Create a set of (question, cypher) tuples from existing examples for deduplication
    existing_keys = set()
    merged = list(existing)  # Start with existing examples
    
    for ex in existing:
        question = ex.get("question", "").strip()
        cypher = ex.get("cypher", "").strip()
        if question and cypher:
            existing_keys.add((question.lower(), cypher.strip()))
    
    # Add new examples that don't already exist
    for ex in new:
        question = ex.get("question", "").strip()
        cypher = ex.get("cypher", "").strip()
        if question and cypher:
            key = (question.lower(), cypher.strip())
            if key not in existing_keys:
                merged.append(ex)
                existing_keys.add(key)  # Prevent duplicates within new examples too
    
    return merged


def generate_examples_for_category(
    category: dict,
    prompt,
    model: str,
    temperature: float,
    max_tokens: int,
    schema_string: str,
    terminology_str: str,
) -> list[dict]:
    """Generate query examples (question-cypher pairs) for a single category."""
    category_name = category.get("category_name", "")
    category_description = category.get("category_description", "")
    
    if not category_name:
        print(f"⚠️  Warning: Category missing 'category_name', skipping...")
        return []
    
    print(f"\n  Processing: {category_name}")
    if category_description:
        print(f"    Description: {category_description[:80]}...")
    
    # Compile prompt with category variables, schema, and terminology
    rendered = prompt.compile(
        category_name=category_name,
        category_description=category_description,
        schema=schema_string,
        terminology=terminology_str,
    )
    
    # Don't use response_format - let the prompt instruct the model to return JSON
    # This avoids the requirement that the prompt must contain the word "json"
    response_format = None
    
    # Call the model
    try:
        # Optionally debug the prompt
        if os.environ.get("DEBUG_PROMPT", "").lower() in {"1", "true", "yes"}:
            print(f"    Debug - Prompt (first 500 chars): {rendered[:500]}")
            print(f"    Debug - Prompt length: {len(rendered)} chars")
        
        # Add retry logic for API calls
        max_retries = 3
        retry_delay = 2  # seconds
        output = None
        
        for attempt in range(max_retries):
            try:
                output = create_completion(
                    rendered,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    langfuse_prompt=prompt,
                    response_format=response_format,
                )
                break  # Success, exit retry loop
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"    ⚠️  API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                    print(f"    Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    print(f"    ⚠️  API call failed after {max_retries} attempts: {e}")
                    raise
        
        # Check if output is empty
        if not output or len(output.strip()) == 0:
            print(f"    ⚠️  Error: Empty response from model")
            print(f"    Model: {model}")
            print(f"    Max tokens: {max_tokens}")
            print(f"    Temperature: {temperature}")
            print(f"    Prompt length: {len(rendered)} chars")
            print(f"    This might indicate:")
            print(f"      - Model hit token limit")
            print(f"      - API error (check Langfuse logs)")
            print(f"      - Prompt too long for model context")
            return []
        
        # Print raw output for debugging
        print(f"    Raw response ({len(output)} chars, first 500): {output[:500]}")
    except Exception as e:
        print(f"    ⚠️  Error calling model: {e}")
        print(f"    Model: {model}")
        import traceback
        traceback.print_exc()
        return []
    
    # Parse the JSON response
    try:
        # Try to clean the output if it has markdown code blocks
        cleaned_output = output.strip()
        if cleaned_output.startswith("```json"):
            # Remove markdown code block markers
            cleaned_output = cleaned_output.replace("```json", "").replace("```", "").strip()
        elif cleaned_output.startswith("```"):
            # Remove generic code block markers
            cleaned_output = cleaned_output.replace("```", "").strip()
        
        result = json.loads(cleaned_output)
        
        # Extract examples from the response
        # Handle different possible response structures
        examples = []
        if isinstance(result, dict):
            if "examples" in result:
                examples = result["examples"]
            elif "queries" in result:
                examples = result["queries"]
            elif "query_examples" in result:
                examples = result["query_examples"]
            else:
                # If the response is a dict but no known key, try to extract list values
                list_values = [v for v in result.values() if isinstance(v, list)]
                examples = list_values[0] if list_values else []
        elif isinstance(result, list):
            examples = result
        else:
            examples = []
        
        # Validate and clean examples (should be dicts with question and cypher)
        # Add timestamp to each example
        timestamp = datetime.now().isoformat()
        valid_examples = []
        for ex in examples:
            if isinstance(ex, dict):
                question = ex.get("question", "").strip()
                cypher = ex.get("cypher", "").strip()
                if question and cypher:
                    valid_examples.append({
                        "question": question,
                        "cypher": cypher,
                        "added_at": timestamp
                    })
        
        # Print generated examples
        if valid_examples:
            print(f"    ✓ Generated {len(valid_examples)} question-cypher pairs:")
            for i, ex in enumerate(valid_examples, 1):
                print(f"      {i}. Q: {ex['question'][:80]}...")
                print(f"         C: {ex['cypher'][:80]}...")
        else:
            print(f"    ⚠️  Warning: No valid examples found in response")
            print(f"    Response structure: {type(result)}")
            if isinstance(result, dict):
                print(f"    Response keys: {list(result.keys())}")
        
        return valid_examples
    except json.JSONDecodeError as e:
        print(f"    ⚠️  Error: Failed to parse JSON response: {e}")
        print(f"    Full response ({len(output)} chars):")
        print("    " + "="*76)
        print("    " + output[:1000].replace("\n", "\n    "))
        if len(output) > 1000:
            print(f"    ... (truncated, showing first 1000 of {len(output)} chars)")
        print("    " + "="*76)
        return []


def main() -> None:


    # Load .env from project root
    if load_dotenv is not None:
        try:
            load_dotenv(dotenv_path=str(ROOT / ".env"))
        except Exception:
            pass

    # Fetch schema (from cache or Neo4j)
    print("Fetching schema...")
    schema_string = get_cached_schema(
        force_update=False,  # Controlled by UPDATE_NEO4J_SCHEMA env var
        fetch_schema_fn=fetch_schema_from_neo4j,
    )
    print(f"✓ Schema loaded ({len(schema_string)} characters)")

    # Load terminology
    print("Loading terminology...")
    terminology_dict = load_terminology("v1")
    terminology_str = terminology_as_text(terminology_dict)
    print(f"✓ Terminology loaded ({len(terminology_str)} characters)")

    # Determine categories file path
    categories_file_env = os.environ.get("CATEGORIES_FILE")
    if categories_file_env:
        categories_file = Path(categories_file_env)
    else:
        # Default to graph_categories.json in the fewshots folder
        fewshots_dir = Path(__file__).resolve().parent
        categories_file = fewshots_dir / "graph_categories.json"
    
    print(f"\nLoading categories from: {categories_file}")
    categories = load_categories(categories_file)
    print(f"✓ Loaded {len(categories)} categories")

    # Load query-examples-builder prompt from Langfuse
    print("\nFetching query-examples-builder prompt from Langfuse...")
    try:
        prompt_label = os.environ.get("PROMPT_LABEL", "production")
        prompt = get_prompt_from_langfuse("query-examples-builder", langfuse_client=None, label=prompt_label)
        params = prompt.config or {}
        print("✓ Prompt loaded from Langfuse")
    except Exception as e:
        raise RuntimeError(
            f"Failed to fetch prompt from Langfuse: {e}. "
            "Ensure Langfuse is configured (LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY) "
            "and the prompt 'query-examples-builder' has been synced."
        ) from e

    # Check if OpenAI/Azure OpenAI is available
    # Allow forcing standard OpenAI even if Azure is configured
    force_openai = os.environ.get("FORCE_OPENAI", "").lower() in {"1", "true", "yes"}
    
    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    azure_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    
    # Determine which API to use
    use_azure = False
    if not force_openai and azure_endpoint and azure_api_key:
        use_azure = True
        print("Using Azure OpenAI")
    elif openai_api_key:
        use_azure = False
        print("Using standard OpenAI")
    else:
        raise RuntimeError(
            "No OpenAI API key found. "
            "Set either AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY or OPENAI_API_KEY. "
            "To force standard OpenAI even if Azure is configured, set FORCE_OPENAI=true"
        )
    
    # Temporarily disable Azure if forcing OpenAI
    if force_openai and azure_endpoint:
        print("⚠️  FORCE_OPENAI=true: Using standard OpenAI instead of Azure")
        # Temporarily unset Azure env vars for this process
        if 'AZURE_OPENAI_ENDPOINT' in os.environ:
            del os.environ['AZURE_OPENAI_ENDPOINT']
        if 'AZURE_OPENAI_API_KEY' in os.environ:
            del os.environ['AZURE_OPENAI_API_KEY']

    # Get model configuration
    # If forcing OpenAI, suggest a standard OpenAI model if not set
    model = (
        os.environ.get("OPEN_AI_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or ("gpt-4o" if force_openai else "gpt-4o")
    )
    
    # Warn if using Azure model name with standard OpenAI
    if force_openai and "gpt-5-mini" in model.lower():
        print(f"⚠️  Warning: Model '{model}' is typically an Azure model.")
        print(f"    Consider setting OPENAI_MODEL=gpt-4o for standard OpenAI")
        print(f"    Current model will be used: {model}")
    
    print(f"Using model: {model}")
    temperature = float(params.get("temperature", 0.7))
    max_tokens = int(params.get("max_tokens", 2000))

    # Interactive category selection
    print(f"\n{'='*80}")
    print(f"Found {len(categories)} categories:")
    print(f"{'='*80}")
    for i, category in enumerate(categories, 1):
        name = category.get('category_name', 'Unknown')
        desc = category.get('category_description', '')[:60]
        print(f"  {i:2d}. {name}")
        if desc:
            print(f"      {desc}...")
    
    # Check if we should use interactive mode
    interactive_mode = os.environ.get("INTERACTIVE", "true").lower() in {"1", "true", "yes"}
    
    selected_indices = []
    if interactive_mode:
        print(f"\n{'='*80}")
        print("Select categories to process:")
        print("  - Enter numbers separated by commas (e.g., 1,3,5)")
        print("  - Enter 'all' to process all categories")
        print("  - Enter 'range' to process a range (e.g., 1-5)")
        print("  - Press Enter to process all")
        print(f"{'='*80}")
        
        selection = input("Selection: ").strip()
        
        if not selection or selection.lower() == "all":
            selected_indices = list(range(len(categories)))
        elif selection.lower() == "range":
            start = input("Start number: ").strip()
            end = input("End number: ").strip()
            try:
                start_idx = int(start) - 1
                end_idx = int(end)
                selected_indices = list(range(start_idx, end_idx))
            except ValueError:
                print("Invalid range, processing all categories")
                selected_indices = list(range(len(categories)))
        else:
            # Parse comma-separated numbers
            try:
                selected_indices = [int(x.strip()) - 1 for x in selection.split(",")]
                # Validate indices
                selected_indices = [i for i in selected_indices if 0 <= i < len(categories)]
                if not selected_indices:
                    print("No valid selections, processing all categories")
                    selected_indices = list(range(len(categories)))
            except ValueError:
                print("Invalid selection, processing all categories")
                selected_indices = list(range(len(categories)))
    else:
        # Non-interactive mode: process all
        selected_indices = list(range(len(categories)))
    
    print(f"\nProcessing {len(selected_indices)} selected category/categories...")
    print("="*80)
    
    # Add delay between API calls to avoid rate limiting
    delay_between_calls = float(os.environ.get("API_CALL_DELAY", "1.0"))  # Default 1 second
    
    results = []
    for idx, category_idx in enumerate(selected_indices, 1):
        category = categories[category_idx]
        print(f"\n[{idx}/{len(selected_indices)}] Category: {category.get('category_name', 'Unknown')}")
        
        # Add delay between calls (except for the first one)
        if idx > 1 and delay_between_calls > 0:
            print(f"    Waiting {delay_between_calls}s before API call...")
            time.sleep(delay_between_calls)
        
        queries = generate_examples_for_category(
            category,
            prompt,
            model,
            temperature,
            max_tokens,
            schema_string,
            terminology_str,
        )
        
        if queries:
            results.append({
                "category_name": category.get("category_name", ""),
                "examples": queries
            })
        else:
            print(f"    ⚠️  Skipping category (no examples generated)")
    
    # Output the results
    print("\n" + "="*80)
    print("GENERATED QUERY EXAMPLES:")
    print("="*80)
    output_json = json.dumps(results, indent=2, ensure_ascii=False)
    print(output_json)
    print("="*80)

    # Determine output file path
    output_file = os.environ.get("OUTPUT_FILE")
    if output_file:
        output_path = Path(output_file)
    else:
        # Default to query_examples.json in the fewshots folder
        fewshots_dir = Path(__file__).resolve().parent
        output_path = fewshots_dir / "query_examples.json"
    
    # Load existing examples
    existing_by_category = load_existing_examples(output_path)
    
    # Merge new results with existing examples
    merged_results = []
    all_category_names = set()
    
    # First, add all existing categories (that weren't regenerated)
    for category_name, examples in existing_by_category.items():
        all_category_names.add(category_name)
        # Check if this category was regenerated in this run
        regenerated = any(r["category_name"] == category_name for r in results)
        if not regenerated:
            merged_results.append({
                "category_name": category_name,
                "examples": examples
            })
    
    # Then, merge or add newly generated categories
    for new_result in results:
        category_name = new_result["category_name"]
        new_examples = new_result["examples"]
        
        if category_name in existing_by_category:
            # Merge with existing examples
            existing_examples = existing_by_category[category_name]
            merged_examples = merge_examples(existing_examples, new_examples)
            print(f"  Category '{category_name}': Merged {len(new_examples)} new examples with {len(existing_examples)} existing")
        else:
            # New category
            merged_examples = new_examples
            print(f"  Category '{category_name}': Added {len(new_examples)} new examples")
        
        # Update or add the category
        category_found = False
        for item in merged_results:
            if item["category_name"] == category_name:
                item["examples"] = merged_examples
                category_found = True
                break
        
        if not category_found:
            merged_results.append({
                "category_name": category_name,
                "examples": merged_examples
            })
    
    # Sort by category name for consistent output
    merged_results.sort(key=lambda x: x["category_name"])
    
    # Save merged results
    output_json = json.dumps(merged_results, indent=2, ensure_ascii=False)
    output_path.write_text(output_json, encoding="utf-8")
    
    print(f"\n✓ Query examples saved to: {output_path}")
    print(f"  Total categories: {len(merged_results)}")
    total_examples = sum(len(r['examples']) for r in merged_results)
    new_examples_count = sum(len(r['examples']) for r in results)
    print(f"  Total examples: {total_examples} (added {new_examples_count} new in this run)")


if __name__ == "__main__":
    main()

