"""Consolidated schema utilities for Neo4j graph database.

This module handles both schema extraction from Neo4j and caching.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, Dict, List, Callable

import neo4j
from neo4j.exceptions import ClientError

# Optional project utility; ignore if unavailable
try:
    from utils import chat  # type: ignore
except Exception:
    chat = None  # not required for schema export

# Import driver utilities for Neo4j connection
try:
    from utils.neo4j import get_driver, close_driver  # type: ignore
except Exception:
    get_driver = None  # type: ignore
    close_driver = None  # type: ignore


# ============================================================================
# Property Exclusion List
# ============================================================================

# Properties to exclude from schema (sensitive data or unnecessary for query generation)
EXCLUDED_PROPERTIES: Dict[str, List[str]] = {
    "Person": [
        "UserID",  # Sensitive data - never return in queries
        # Add other Person properties to exclude here if needed
        # Example: "youtube_use", "tiktok_use", etc.
    ],
    # Add other node types and their excluded properties here if needed
    # "TikTokUser": ["some_property"],
}


def _should_exclude_property(node_label: str, property_name: str) -> bool:
    """Check if a property should be excluded from the schema."""
    excluded = EXCLUDED_PROPERTIES.get(node_label, [])
    return property_name in excluded


# ============================================================================
# Schema Extraction
# ============================================================================

NODE_PROPERTIES_QUERY = """
CALL apoc.meta.data()
YIELD label, other, elementType, type, property
WHERE NOT type = "RELATIONSHIP" AND elementType = "node"
WITH label AS nodeLabels, collect({property:property, type:type}) AS properties
RETURN {labels: nodeLabels, properties: properties} AS output
"""

REL_PROPERTIES_QUERY = """
CALL apoc.meta.data()
YIELD label, other, elementType, type, property
WHERE NOT type = "RELATIONSHIP" AND elementType = "relationship"
WITH label AS relType, collect({property:property, type:type}) AS properties
RETURN {type: relType, properties: properties} AS output
"""

REL_QUERY = """
CALL apoc.meta.data()
YIELD label, other, elementType, type, property
WHERE type = "RELATIONSHIP" AND elementType = "node"
UNWIND other AS other_node
RETURN {start: label, type: property, end: toString(other_node)} AS output
"""


def query_database(
    driver: neo4j.Driver, query: str, params: dict[str, Any] = None
) -> list[dict[str, Any]]:
    if params is None:
        params = {}
    data = driver.execute_query(query, params)
    return [r.data() for r in data.records]


def _get_schema_via_apoc(driver: neo4j.Driver) -> dict[str, Any]:
    node_labels_response = driver.execute_query(NODE_PROPERTIES_QUERY)
    node_properties = [
        data["output"] for data in [r.data() for r in node_labels_response.records]
    ]

    rel_properties_query_response = driver.execute_query(REL_PROPERTIES_QUERY)
    rel_properties = [
        data["output"]
        for data in [r.data() for r in rel_properties_query_response.records]
    ]

    rel_query_response = driver.execute_query(REL_QUERY)
    relationships = [
        data["output"] for data in [r.data() for r in rel_query_response.records]
    ]

    # Filter out excluded properties
    filtered_node_props = {}
    for el in node_properties:
        label = el["labels"]
        props = el["properties"]
        filtered_props = [
            prop for prop in props
            if not _should_exclude_property(label, prop.get("property", ""))
        ]
        if filtered_props:  # Only add if there are properties left
            filtered_node_props[label] = filtered_props

    return {
        "node_props": filtered_node_props,
        "rel_props": {el["type"]: el["properties"] for el in rel_properties},
        "relationships": relationships,
    }


def _get_schema_via_builtin(driver: neo4j.Driver) -> dict[str, Any]:
    """Fallback using db.schema.* procedures (no APOC required)."""
    # Node properties
    node_rows = driver.execute_query("CALL db.schema.nodeTypeProperties()")
    node_dict: Dict[str, List[Dict[str, Any]]] = {}
    for rec in node_rows.records:
        row = rec.data()
        label = row.get("nodeType") or "Unknown"
        prop_name = row.get("propertyName") or "property"
        # Filter out excluded properties
        if _should_exclude_property(label, prop_name):
            continue
        prop_types = row.get("propertyTypes")
        prop_type_str = ",".join(prop_types) if isinstance(prop_types, list) else str(prop_types)
        node_dict.setdefault(label, []).append({"property": prop_name, "type": prop_type_str})

    # Relationship properties
    rel_rows = driver.execute_query("CALL db.schema.relTypeProperties()")
    rel_dict: Dict[str, List[Dict[str, Any]]] = {}
    for rec in rel_rows.records:
        row = rec.data()
        rtype = row.get("relType") or "RELATES_TO"
        prop_name = row.get("propertyName") or "property"
        prop_types = row.get("propertyTypes")
        prop_type_str = ",".join(prop_types) if isinstance(prop_types, list) else str(prop_types)
        rel_dict.setdefault(rtype, []).append({"property": prop_name, "type": prop_type_str})

    # Relationships (topology)
    rels: List[Dict[str, str]] = []
    # Use a data-driven scan to derive (start,type,end) triples with concrete labels
    relq = (
        "MATCH (a)-[r]->(b) "
        "RETURN DISTINCT head(labels(a)) AS start, type(r) AS type, head(labels(b)) AS end "
        "LIMIT 500"
    )
    rel_rows = driver.execute_query(relq)
    for rec in rel_rows.records:
        row = rec.data()
        start = row.get("start") or "Node"
        rtype = row.get("type") or "RELATES_TO"
        end = row.get("end") or "Node"
        rels.append({"start": str(start), "type": str(rtype), "end": str(end)})

    return {"node_props": node_dict, "rel_props": rel_dict, "relationships": rels}


def get_schema(
    driver: neo4j.Driver,
) -> str:
    structured_schema = get_structured_schema(driver)

    def _format_props(props: list[dict[str, Any]]) -> str:
        return ", ".join([f"{prop['property']}: {prop['type']}" for prop in props])

    formatted_node_props = [
        f"{label} {{{_format_props(props)}}}"
        for label, props in structured_schema["node_props"].items()
    ]

    formatted_rel_props = [
        f"{rel_type} {{{_format_props(props)}}}"
        for rel_type, props in structured_schema["rel_props"].items()
    ]

    formatted_rels = [
        f"(:{element['start']})-[:{element['type']}]->(:{element['end']})"
        for element in structured_schema["relationships"]
    ]

    return "\n".join(
        [
            "Node properties:",
            "\n".join(formatted_node_props),
            "Relationship properties:",
            "\n".join(formatted_rel_props),
            "The relationships:",
            "\n".join(formatted_rels),
        ]
    )


def get_structured_schema(driver: neo4j.Driver) -> dict[str, Any]:
    # Try APOC first; fallback to built-in procedures
    try:
        structured = _get_schema_via_apoc(driver)
    except ClientError as e:
        if "ProcedureNotFound" in str(e) or "There is no procedure" in str(e):
            structured = _get_schema_via_builtin(driver)
        else:
            raise

    # Also produce a human-readable multi-line string
    def _format_props(props: list[dict[str, Any]]) -> str:
        return ", ".join([f"{p.get('property')}: {p.get('type')}" for p in props])

    formatted_node_props = [
        f"{label} {{{_format_props(props)}}}"
        for label, props in structured.get("node_props", {}).items()
    ]

    formatted_rel_props = [
        f"{rel_type} {{{_format_props(props)}}}"
        for rel_type, props in structured.get("rel_props", {}).items()
    ]

    formatted_rels = [
        f"(:{element.get('start')})-[:{element.get('type')}]->(:{element.get('end')})"
        for element in structured.get("relationships", [])
    ]

    structured["formatted"] = "\n".join(
        [
            "Node properties:",
            "\n".join(formatted_node_props),
            "Relationship properties:",
            "\n".join(formatted_rel_props),
            "The relationships:",
            "\n".join(formatted_rels),
        ]
    )

    return structured


# ============================================================================
# Schema Caching
# ============================================================================

def get_schema_cache_path() -> Path:
    """Get the path to the schema cache file."""
    schema_dir = Path(__file__).resolve().parent
    return schema_dir / "schema.txt"


def load_cached_schema() -> Optional[str]:
    """Load cached schema string from file.
    
    Returns:
        Cached schema string, or None if cache doesn't exist
    """
    cache_path = get_schema_cache_path()
    if cache_path.exists():
        try:
            return cache_path.read_text(encoding="utf-8")
        except Exception:
            return None
    return None


def save_schema_cache(schema_string: str) -> None:
    """Save schema string to cache file.
    
    Args:
        schema_string: The formatted schema string to cache
    """
    cache_path = get_schema_cache_path()
    try:
        cache_path.write_text(schema_string, encoding="utf-8")
    except Exception as e:
        # Log but don't fail if cache write fails
        import sys
        print(f"Warning: Failed to write schema cache: {e}", file=sys.stderr)


def get_cached_schema(
    *,
    force_update: bool = False,
    fetch_schema_fn: Optional[Callable[[], str]] = None,
) -> str:
    """Get schema string, using cache if available.
    
    Args:
        force_update: If True, fetch from Neo4j and update cache
        fetch_schema_fn: Optional function to fetch schema from Neo4j
        
    Returns:
        Schema string (from cache or freshly fetched)
    """
    # Check if we should update (UPDATE_NEO4J_SCHEMA env var)
    update_flag = os.environ.get("UPDATE_NEO4J_SCHEMA", "false").lower() in {"1", "true", "yes"}
    
    if not force_update and not update_flag:
        # Try to load from cache (default behavior)
        cached = load_cached_schema()
        if cached is not None:
            return cached
    
    # Cache miss or update requested - fetch from Neo4j
    if fetch_schema_fn is None:
        raise RuntimeError("fetch_schema_fn is required when cache is unavailable or update is requested")
    
    schema_string = fetch_schema_fn()
    
    # Always save to cache after fetching (stored in ai/schema/schema.txt)
    save_schema_cache(schema_string)
    
    # Also update visualization when schema is updated
    # This happens automatically when UPDATE_NEO4J_SCHEMA=true or force_update=True
    try:
        from ai.schema.update_visualization import update_visualization
        # Silently update visualization (verbose=False to avoid noise during schema updates)
        update_visualization(database=None, verbose=False)
    except ImportError:
        # update_visualization module might not be available in all contexts
        pass
    except Exception as e:
        # Don't fail schema update if visualization update fails
        # Log warning but continue
        import sys
        print(f"Warning: Failed to update visualization during schema update: {e}", file=sys.stderr)
    
    return schema_string


# ============================================================================
# Convenience Functions
# ============================================================================

def fetch_schema_from_neo4j() -> str:
    """Fetch schema from Neo4j and return formatted string.
    
    This is a convenience function that handles driver initialization
    and cleanup automatically.
    
    Returns:
        Formatted schema string
    """
    if get_driver is None:
        raise RuntimeError("utils.neo4j.get_driver is required. Ensure utils/neo4j.py is available.")
    
    driver = get_driver()
    try:
        structured = get_structured_schema(driver)
        return structured.get("formatted") or get_schema(driver)
    finally:
        if close_driver is not None:
            try:
                close_driver()
            except Exception:
                pass
