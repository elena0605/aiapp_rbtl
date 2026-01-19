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
    
    For environment switching:
      - Set ENVIRONMENT=development to use LANGFUSE_HOST_DEV, LANGFUSE_PUBLIC_KEY_DEV, LANGFUSE_SECRET_KEY_DEV
      - Set ENVIRONMENT=production (or omit) to use LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
    
    Returns:
        Initialized Langfuse client
    """
    if Langfuse is None:
        raise RuntimeError("Langfuse is required. Install with: pip install langfuse")
    
    # Load .env from project root
    if load_dotenv is not None:
        project_root = Path(__file__).resolve().parents[2]  # Go up to project root
        load_dotenv(dotenv_path=str(project_root / ".env"))
    
    # Get environment
    environment = os.environ.get("ENVIRONMENT", "production").lower()
    
    # Select environment-specific credentials
    if environment == "development":
        host = os.environ.get("LANGFUSE_HOST_DEV") or os.environ.get("LANGFUSE_HOST")
        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY_DEV") or os.environ.get("LANGFUSE_PUBLIC_KEY")
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY_DEV") or os.environ.get("LANGFUSE_SECRET_KEY")
    else:
        host = os.environ.get("LANGFUSE_HOST")
        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    
    if not all([host, public_key, secret_key]):
        raise RuntimeError(
            f"Langfuse credentials not found (environment={environment}). "
            f"Set LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, and LANGFUSE_SECRET_KEY "
            f"(or _DEV variants for development) in .env or environment variables."
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
    response_format: Optional[Dict[str, Any]] = None,
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
        response_format: Optional response format (e.g., {"type": "json_object"} or JSON schema)
    """
    # Try Langfuse OpenAI wrapper first if keys are provided
    # Get environment-specific credentials
    environment = os.environ.get("ENVIRONMENT", "production").lower()
    if environment == "development":
        langfuse_host = os.environ.get("LANGFUSE_HOST_DEV") or os.environ.get("LANGFUSE_HOST")
        langfuse_public_key = os.environ.get("LANGFUSE_PUBLIC_KEY_DEV") or os.environ.get("LANGFUSE_PUBLIC_KEY")
        langfuse_secret_key = os.environ.get("LANGFUSE_SECRET_KEY_DEV") or os.environ.get("LANGFUSE_SECRET_KEY")
    else:
        langfuse_host = os.environ.get("LANGFUSE_HOST")
        langfuse_public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
        langfuse_secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    
    use_langfuse = bool(langfuse_host and langfuse_public_key and langfuse_secret_key)

    if use_langfuse:
        try:
            # Check for Azure OpenAI configuration
            # Note: If FORCE_OPENAI is set, Azure env vars may have been deleted
            azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
            azure_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
            # Default to latest GA version (2024-06-01) for production stability
            # Note: JSON schema support requires 2024-08-01-preview or later
            azure_api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01")
            openai_api_key = os.environ.get("OPENAI_API_KEY")
            
            # Debug: Show which API will be used
            if azure_endpoint and azure_api_key:
                print(f"Langfuse: Azure OpenAI configured (endpoint: {azure_endpoint[:50]}...)")
            elif openai_api_key:
                print(f"Langfuse: Standard OpenAI configured")
            else:
                print(f"Langfuse: No API keys found")
            
            # Clean up Azure endpoint (remove trailing /models if present)
            if azure_endpoint:
                azure_endpoint = azure_endpoint.rstrip('/')
                if azure_endpoint.endswith('/models'):
                    azure_endpoint = azure_endpoint[:-7]  # Remove '/models'
            
            # Requires: pip install langfuse
            from langfuse.openai import OpenAI, AzureOpenAI  # type: ignore
            
            # Initialize Langfuse client using shared function
            langfuse = _init_langfuse_client()
            
            # Build kwargs for the API call
            # Use Azure OpenAI if configured, otherwise standard OpenAI
            if azure_endpoint and azure_api_key:
                # Azure OpenAI uses max_completion_tokens instead of max_tokens
                # Azure OpenAI (GPT-5-mini) only supports default temperature (1.0)
                kwargs = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_completion_tokens": max_tokens,
                }
                # Azure OpenAI only supports default temperature (1.0), so skip temperature parameter
                # This lets it use the default value
                # Add response format if provided
                if response_format:
                    kwargs["response_format"] = response_format
                # Link the prompt to the observation if provided
                if langfuse_prompt is not None:
                    kwargs["langfuse_prompt"] = langfuse_prompt
                # Azure OpenAI via Langfuse wrapper
                azure_client = AzureOpenAI(
                    azure_endpoint=azure_endpoint,
                    api_key=azure_api_key,
                    api_version=azure_api_version,
                )
                res = azure_client.chat.completions.create(**kwargs)
            elif openai_api_key:
                # Standard OpenAI - some newer models require max_completion_tokens
                # Check environment variable or model name to determine which to use
                use_max_completion = os.environ.get("USE_MAX_COMPLETION_TOKENS", "").lower() in {"1", "true", "yes"}
                if not use_max_completion:
                    # Auto-detect based on model name - newer models need max_completion_tokens
                    # gpt-5 models (including gpt-5-mini) require max_completion_tokens
                    model_lower = model.lower()
                    use_max_completion = any(x in model_lower for x in ["gpt-4o", "gpt-4-turbo", "o1", "o3", "gpt-5", "gpt-5-mini"])
                
                kwargs = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                }
                # Some models only support default temperature (1.0), skip temperature parameter
                # gpt-4o and some newer models may have temperature restrictions
                model_lower = model.lower()
                supports_custom_temp = not any(x in model_lower for x in ["gpt-4o", "gpt-5", "o1", "o3"])
                if supports_custom_temp and temperature != 1.0:
                    kwargs["temperature"] = temperature
                # Use the appropriate parameter based on model requirements
                # Default to max_completion_tokens for newer models
                if use_max_completion:
                    kwargs["max_completion_tokens"] = max_tokens
                else:
                    kwargs["max_tokens"] = max_tokens
                # Add response format if provided
                if response_format:
                    kwargs["response_format"] = response_format
                # Link the prompt to the observation if provided
                if langfuse_prompt is not None:
                    kwargs["langfuse_prompt"] = langfuse_prompt
                # Standard OpenAI via Langfuse wrapper (class-based approach avoids ambiguity)
                openai_client = OpenAI(api_key=openai_api_key)
                
                # Try with the selected parameter, retry with corrected parameters if it fails
                try:
                    res = openai_client.chat.completions.create(**kwargs)
                except Exception as e:
                    error_str = str(e)
                    # Check if this is a max_tokens/max_completion_tokens error
                    is_token_param_error = (
                        "max_tokens" in error_str and "max_completion_tokens" in error_str
                    ) or (
                        "unsupported parameter" in error_str.lower() and 
                        ("max_tokens" in error_str or "max_completion_tokens" in error_str)
                    ) or (
                        "unsupported_parameter" in error_str.lower() and 
                        ("max_tokens" in error_str or "max_completion_tokens" in error_str)
                    )
                    
                    # Check if this is a temperature error
                    is_temp_error = (
                        "temperature" in error_str.lower() and 
                        ("unsupported value" in error_str.lower() or "unsupported_value" in error_str.lower())
                    )
                    
                    if is_token_param_error:
                        # Switch to the other parameter
                        if "max_tokens" in kwargs:
                            del kwargs["max_tokens"]
                            kwargs["max_completion_tokens"] = max_tokens
                            print(f"Retrying with max_completion_tokens instead of max_tokens", file=sys.stderr)
                        elif "max_completion_tokens" in kwargs:
                            del kwargs["max_completion_tokens"]
                            kwargs["max_tokens"] = max_tokens
                            print(f"Retrying with max_tokens instead of max_completion_tokens", file=sys.stderr)
                        # Retry with the corrected parameter (without langfuse_prompt to avoid double tracing)
                        langfuse_prompt_backup = kwargs.pop("langfuse_prompt", None)
                        res = openai_client.chat.completions.create(**kwargs)
                        # Note: We lose Langfuse tracing on retry, but that's acceptable
                    elif is_temp_error:
                        # Remove temperature parameter and retry (model only supports default)
                        if "temperature" in kwargs:
                            del kwargs["temperature"]
                            print(f"Retrying without temperature parameter (model only supports default)", file=sys.stderr)
                        # Retry with the corrected parameter (without langfuse_prompt to avoid double tracing)
                        langfuse_prompt_backup = kwargs.pop("langfuse_prompt", None)
                        res = openai_client.chat.completions.create(**kwargs)
                    else:
                        # Re-raise if it's not a parameter error
                        raise
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
    # Default to latest GA version (2024-06-01) for production stability
    # Note: JSON schema support requires 2024-08-01-preview or later
    azure_api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01")
    
    # Clean up Azure endpoint (remove trailing /models if present)
    if azure_endpoint:
        azure_endpoint = azure_endpoint.rstrip('/')
        if azure_endpoint.endswith('/models'):
            azure_endpoint = azure_endpoint[:-7]  # Remove '/models'
    
    # Check for standard OpenAI configuration
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    
    if azure_endpoint and azure_api_key:
        # Use Azure OpenAI (uses max_completion_tokens instead of max_tokens)
        # Azure OpenAI (GPT-5-mini) only supports default temperature (1.0), not 0.0
        client = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=azure_api_key,
            api_version=azure_api_version,
        )
        create_kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_completion_tokens": max_tokens,
        }
        # Azure OpenAI only supports default temperature (1.0), so skip temperature parameter
        # This lets it use the default value
        # Add response format if provided
        if response_format:
            create_kwargs["response_format"] = response_format
        resp = client.chat.completions.create(**create_kwargs)
    elif openai_api_key:
        # Use standard OpenAI - some newer models require max_completion_tokens
        client = OpenAI(api_key=openai_api_key)
        # Check environment variable or model name to determine which to use
        use_max_completion = os.environ.get("USE_MAX_COMPLETION_TOKENS", "").lower() in {"1", "true", "yes"}
        if not use_max_completion:
            # Auto-detect based on model name
            use_max_completion = any(x in model.lower() for x in ["gpt-4o", "gpt-4-turbo", "o1", "o3", "gpt-5"])
        
        create_kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        # Some models only support default temperature (1.0), skip temperature parameter
        # gpt-4o and some newer models may have temperature restrictions
        model_lower = model.lower()
        supports_custom_temp = not any(x in model_lower for x in ["gpt-4o", "gpt-5", "o1", "o3"])
        if supports_custom_temp and temperature != 1.0:
            create_kwargs["temperature"] = temperature
        # Use the appropriate parameter based on model requirements
        if use_max_completion:
            create_kwargs["max_completion_tokens"] = max_tokens
        else:
            create_kwargs["max_tokens"] = max_tokens
        # Add response format if provided
        if response_format:
            create_kwargs["response_format"] = response_format
        
        try:
            resp = client.chat.completions.create(**create_kwargs)
        except Exception as e:
            # If max_tokens fails, try max_completion_tokens (or vice versa)
            if "max_tokens" in str(e) or "max_completion_tokens" in str(e):
                if "max_tokens" in create_kwargs:
                    del create_kwargs["max_tokens"]
                    create_kwargs["max_completion_tokens"] = max_tokens
                elif "max_completion_tokens" in create_kwargs:
                    del create_kwargs["max_completion_tokens"]
                    create_kwargs["max_tokens"] = max_tokens
                resp = client.chat.completions.create(**create_kwargs)
            else:
                raise
    else:
        raise RuntimeError(
            "Either AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY or "
            "OPENAI_API_KEY is required when Langfuse is not configured."
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

