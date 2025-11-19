"""Graph information endpoints providing schema and terminology overviews."""

from fastapi import APIRouter, HTTPException

from ai.schema.schema_utils import load_cached_schema
from ai.terminology.loader import load as load_terminology, as_text as terminology_as_text

router = APIRouter()


def _parse_schema(schema_text: str):
    """Parse schema.txt into node and relationship metadata without querying Neo4j."""
    nodes = []
    relationships = []

    section = None
    for line in schema_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "Node properties:":
            section = "nodes"
            continue
        if stripped == "Relationship properties:":
            section = "rel_props"
            continue
        if stripped == "The relationships:":
            section = "rels"
            continue

        if section == "nodes":
            if "{" in stripped and stripped.endswith("}"):
                label, props_str = stripped.split("{", 1)
                label = label.strip().lstrip(":").strip("`'\"")
                props_content = props_str.rstrip("}")
                properties = []
                for prop_entry in props_content.split(","):
                    prop_entry = prop_entry.strip()
                    if not prop_entry:
                        continue
                    if ":" in prop_entry:
                        name, ptype = prop_entry.split(":", 1)
                        properties.append(
                            {"property": name.strip(), "type": ptype.strip()}
                        )
                nodes.append(
                    {"label": label or "Node", "properties": properties, "description": ""}
                )

        if section == "rels":
            # Format: (:A)-[:REL]->(:B)
            if stripped.startswith("(:") and ")-[:" in stripped:
                try:
                    start_part, rest = stripped.split(")-[:", 1)
                    rel_type, end_part = rest.split("]->(:", 1)
                    start_label = start_part.lstrip("(:").strip().strip("`'\"") or "Node"
                    rel_label = rel_type.strip().strip("`'\"") or "RELATES_TO"
                    end_label = end_part.rstrip(")").strip().strip("`'\"") or "Node"
                    relationships.append(
                        {
                            "start": start_label,
                            "type": rel_label,
                            "end": end_label,
                            "description": "",
                        }
                    )
                except ValueError:
                    continue

    return nodes, relationships


@router.get("/graph-info")
async def get_graph_info():
    """Return cached schema overview and terminology without live Neo4j queries."""
    schema_text = load_cached_schema()
    if not schema_text:
        raise HTTPException(
            status_code=500,
            detail=(
                "Graph schema cache not found. Please run the schema caching routine "
                "(e.g., set UPDATE_NEO4J_SCHEMA=true and execute text_to_cypher once) "
                "to populate ai/schema/schema.txt."
            ),
        )

    nodes, relationships = _parse_schema(schema_text)

    try:
        terminology = load_terminology("v1")
        terminology_text = terminology_as_text(terminology)
    except Exception:
        terminology = {}
        terminology_text = "Terminology reference unavailable."

    node_descriptions = (terminology.get("nodes") or {}) if isinstance(terminology, dict) else {}
    rel_descriptions = (terminology.get("relationships") or {}) if isinstance(terminology, dict) else {}

    for node in nodes:
        label = node.get("label")
        normalized_label = (label or "").replace("`", "").replace(":", "")
        description = (
            node_descriptions.get(label)
            or node_descriptions.get(normalized_label)
            or node_descriptions.get(label.lower())
            or node_descriptions.get(normalized_label.lower())
            or ""
        )
        node["description"] = description

    for rel in relationships:
        rel_type = rel.get("type")
        normalized_type = (rel_type or "").replace("`", "")
        description = (
            rel_descriptions.get(rel_type)
            or rel_descriptions.get(normalized_type)
            or rel_descriptions.get(rel_type.lower())
            or rel_descriptions.get(normalized_type.lower())
            or ""
        )
        rel["description"] = description

    summary = (
        "This overview is generated from the cached schema under ai/schema/schema.txt. "
        "Use Neo4j Bloom, Graphviz, or D3 to render these nodes and relationships as a graph. "
        "Update the cache by re-running the schema extraction workflow whenever the graph evolves."
    )

    return {
        "schema_text": schema_text,
        "terminology_text": terminology_text,
        "nodes": nodes,
        "relationships": relationships,
        "graph_ready": bool(relationships),
        "summary": summary,
    }

