"""Langfuse client utilities for tracing and prompt management.

This module handles:
- LLM API calls with automatic Langfuse tracing
- Prompt fetching from Langfuse
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None  # type: ignore

try:
    from langfuse import Langfuse  # type: ignore
except Exception:
    Langfuse = None  # type: ignore


# ============================================================================
# Langfuse Client Initialization
# ============================================================================

def _init_langfuse_client() -> Any:
    """Initialize Langfuse client with credentials from .env.
    
    Returns:
        Initialized Langfuse client
    """
    if Langfuse is None:
        raise RuntimeError("Langfuse is required. Install with: pip install langfuse")
    
    # Load .env from project root
    if load_dotenv is not None:
        project_root = Path(__file__).resolve().parents[2]  # Go up to project root
        load_dotenv(dotenv_path=str(project_root / ".env"))
    
    # Get credentials
    host = os.environ.get("LANGFUSE_HOST")
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    
    if not all([host, public_key, secret_key]):
        raise RuntimeError(
            "Langfuse credentials not found. Set LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, "
            "and LANGFUSE_SECRET_KEY in .env or environment variables."
        )
    
    # Initialize client explicitly
    return Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=host,
    )


# ============================================================================
# LLM API Calls with Tracing
# ============================================================================

def create_completion(
    prompt: str, 
    *, 
    model: str, 
    temperature: float, 
    max_tokens: int,
    langfuse_prompt: Any = None,
) -> str:
    """Create a chat completion using Langfuse OpenAI wrapper when configured.

    Falls back to official OpenAI client if Langfuse wrapper is not available.
    Returns the assistant message text.
    
    Args:
        prompt: The prompt text to send to the model
        model: Model name (e.g., "gpt-4o")
        temperature: Temperature parameter
        max_tokens: Maximum tokens to generate
        langfuse_prompt: Optional Langfuse prompt object to link to the observation
    """
    # Try Langfuse OpenAI wrapper first if keys are provided
    langfuse_host = os.environ.get("LANGFUSE_HOST")
    langfuse_public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    
    use_langfuse = bool(langfuse_host and langfuse_public_key and langfuse_secret_key)

    if use_langfuse:
        try:
            # Check for Azure OpenAI configuration
            azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
            azure_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
            azure_api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
            openai_api_key = os.environ.get("OPENAI_API_KEY")
            
            # Requires: pip install langfuse
            from langfuse.openai import OpenAI, AzureOpenAI  # type: ignore
            
            # Initialize Langfuse client using shared function
            langfuse = _init_langfuse_client()
            
            # Build kwargs for the API call
            kwargs = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            
            # Link the prompt to the observation if provided
            if langfuse_prompt is not None:
                kwargs["langfuse_prompt"] = langfuse_prompt
            
            # Use Azure OpenAI if configured, otherwise standard OpenAI
            if azure_endpoint and azure_api_key:
                # Azure OpenAI via Langfuse wrapper
                azure_client = AzureOpenAI(
                    azure_endpoint=azure_endpoint,
                    api_key=azure_api_key,
                    api_version=azure_api_version,
                )
                res = azure_client.chat.completions.create(**kwargs)
            elif openai_api_key:
                # Standard OpenAI via Langfuse wrapper (class-based approach avoids ambiguity)
                openai_client = OpenAI(api_key=openai_api_key)
                res = openai_client.chat.completions.create(**kwargs)
            else:
                raise RuntimeError(
                    "Either AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY or "
                    "OPENAI_API_KEY is required."
                )
            
            return (res.choices[0].message.content or "").strip()
        except Exception as e:
            # Log error but fall through to official client
            import sys
            print(f"Langfuse tracing error: {e}", file=sys.stderr)
            pass

    # Fallback: official OpenAI client (supports both OpenAI and Azure OpenAI)
    from openai import OpenAI, AzureOpenAI  # type: ignore

    # Check for Azure OpenAI configuration
    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    azure_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    azure_api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
    
    # Check for standard OpenAI configuration
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    
    if azure_endpoint and azure_api_key:
        # Use Azure OpenAI
        client = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=azure_api_key,
            api_version=azure_api_version,
        )
    elif openai_api_key:
        # Use standard OpenAI
        client = OpenAI(api_key=openai_api_key)
    else:
        raise RuntimeError(
            "Either AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY or "
            "OPENAI_API_KEY is required when Langfuse is not configured."
        )
    
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


# ============================================================================
# Prompt Management
# ============================================================================

def get_prompt_from_langfuse(
    prompt_id: str,
    *,
    langfuse_client: Optional[Any] = None,
    label: Optional[str] = None,
    version: Optional[int] = None,
) -> Any:
    """Fetch a prompt from Langfuse.
    
    Args:
        prompt_id: Prompt ID (e.g., "graph.text_to_cypher")
        langfuse_client: Optional Langfuse client (creates one if not provided)
        label: Optional label to fetch (defaults to "production")
        version: Optional version number to fetch
        
    Returns:
        Langfuse prompt object with .compile() method
        
    Raises:
        RuntimeError: If prompt cannot be found in Langfuse
    """
    if Langfuse is None:
        raise RuntimeError("Langfuse is required. Install with: pip install langfuse")

    if langfuse_client is None:
        langfuse_client = _init_langfuse_client()

    # Convert ID to Langfuse name (replace dots with dashes)
    prompt_name = prompt_id.replace(".", "-")

    # Fetch prompt with retry logic
    try:
        if version is not None:
            prompt = langfuse_client.get_prompt(prompt_name, version=version)  # type: ignore
        elif label:
            prompt = langfuse_client.get_prompt(prompt_name, label=label)  # type: ignore
        else:
            # Default to production label
            prompt = langfuse_client.get_prompt(prompt_name)  # type: ignore
    except Exception as e:
        # If fetching by label failed, try fetching latest version without label
        if label and version is None:
            try:
                prompt = langfuse_client.get_prompt(prompt_name)  # type: ignore
            except Exception as e2:
                raise RuntimeError(
                    f"Prompt '{prompt_id}' (name: '{prompt_name}') not found in Langfuse. "
                    f"Tried label '{label}' and latest version. "
                    f"Original error: {e}. Fallback error: {e2}. "
                    f"Ensure the prompt has been synced to Langfuse."
                ) from e2
        else:
            raise RuntimeError(
                f"Prompt '{prompt_id}' (name: '{prompt_name}') not found in Langfuse. "
                f"Error: {e}. Ensure the prompt has been synced to Langfuse."
            ) from e

    return prompt

