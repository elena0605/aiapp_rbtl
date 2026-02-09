#!/usr/bin/env python3
"""Update the graph visualization JSON file from Neo4j.

This script calls Neo4j's db.schema.visualization() procedure and saves
the result to ai/schema/visualization.json for use by the frontend.
"""

import json
import sys
from pathlib import Path


class Neo4jJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles Neo4j Node and Relationship objects."""
    def default(self, obj):
        # Check for Neo4j Relationship objects
        if hasattr(obj, 'type') and (hasattr(obj, 'start_node') or hasattr(obj, 'nodes')):
            converted = _convert_relationship_to_array(obj)
            if converted:
                return converted
        # Check for Neo4j Node objects
        if hasattr(obj, 'labels'):
            try:
                labels = list(obj.labels) if obj.labels else []
                return labels[0] if labels else "Unknown"
            except Exception:
                return str(obj)
        elif obj.__class__.__name__ == 'Node':
            return str(obj)
        # Let the base class handle other types
        return super().default(obj)

# Add project root to path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from utils.neo4j import get_driver, close_driver

# Load environment variables
load_dotenv(dotenv_path=ROOT / ".env")

# Path to visualization file
VISUALIZATION_FILE = Path(__file__).resolve().parent / "visualization.json"


def _convert_node_to_label(obj):
    """Convert Neo4j Node object to its label string."""
    try:
        # Check if it's a Neo4j Node object by checking for 'labels' attribute
        # or by checking the class name
        if hasattr(obj, 'labels'):
            labels = list(obj.labels) if obj.labels else []
            return labels[0] if labels else "Unknown"
        elif obj.__class__.__name__ == 'Node':
            # Fallback: if it's a Node but labels attribute doesn't work
            return str(obj)
    except Exception:
        pass
    return obj


def _convert_relationship_to_array(rel_obj):
    """Convert Neo4j Relationship object to [startNode, type, endNode] array."""
    try:
        # Neo4j Relationship objects have 'start_node', 'type', and 'end_node' attributes
        if hasattr(rel_obj, 'start_node') and hasattr(rel_obj, 'end_node') and hasattr(rel_obj, 'type'):
            start_node = _convert_node_to_label(rel_obj.start_node)
            rel_type = rel_obj.type if isinstance(rel_obj.type, str) else str(rel_obj.type)
            end_node = _convert_node_to_label(rel_obj.end_node)
            return [start_node, rel_type, end_node]
        # Alternative: check for 'nodes' attribute (tuple of start, end)
        elif hasattr(rel_obj, 'nodes') and hasattr(rel_obj, 'type'):
            nodes = rel_obj.nodes
            if len(nodes) >= 2:
                start_node = _convert_node_to_label(nodes[0])
                rel_type = rel_obj.type if isinstance(rel_obj.type, str) else str(rel_obj.type)
                end_node = _convert_node_to_label(nodes[1])
                return [start_node, rel_type, end_node]
    except Exception:
        pass
    return None


def _make_json_serializable(obj):
    """Recursively convert Neo4j objects to JSON-serializable format."""
    # Check for Neo4j Relationship objects first
    if not isinstance(obj, (str, int, float, bool, type(None))):
        # Check if it's a Neo4j Relationship object
        if hasattr(obj, 'type') and (hasattr(obj, 'start_node') or hasattr(obj, 'nodes')):
            converted = _convert_relationship_to_array(obj)
            if converted:
                return converted
        # Check if it's a Neo4j Node object
        elif hasattr(obj, 'labels') or obj.__class__.__name__ == 'Node':
            return _convert_node_to_label(obj)
    
    # Handle collections
    if isinstance(obj, dict):
        return {key: _make_json_serializable(value) for key, value in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_make_json_serializable(item) for item in obj]
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        # Fallback: convert to string for any other type
        return str(obj)


def update_visualization(database: str = None, verbose: bool = True):
    """Fetch schema visualization from Neo4j and save to file.
    
    Args:
        database: Neo4j database name (default: use default database)
        verbose: If True, print success messages (default: True)
    
    Returns:
        True if successful, False otherwise
    """
    driver = get_driver()
    
    try:
        with driver.session(database=database) as session:
            # Call Neo4j's schema visualization procedure
            # The procedure returns a single record with 'nodes' and 'relationships' keys
            result = session.run("CALL db.schema.visualization()")
            records = list(result)
            
            if not records:
                if verbose:
                    print("Error: No visualization data returned from Neo4j")
                return False
            
            # The procedure returns a single record with the visualization data
            record = records[0]
            
            # Extract the visualization data
            # The record contains keys like 'nodes' and 'relationships'
            visualization_data = dict(record)
            
            # Ensure we have the expected structure
            if "nodes" not in visualization_data or "relationships" not in visualization_data:
                if verbose:
                    print(f"Error: Unexpected visualization format. Keys: {list(visualization_data.keys())}")
                return False
            
            # Process nodes array - preserve object structure with name, indexes, constraints
            # Only convert Node objects that appear within node objects (if any)
            nodes = visualization_data.get("nodes", [])
            serializable_nodes = []
            for node in nodes:
                if isinstance(node, dict):
                    # Already a dict with name, indexes, constraints - just ensure it's serializable
                    serializable_node = {
                        "name": node.get("name", ""),
                        "indexes": _make_json_serializable(node.get("indexes", [])),
                        "constraints": _make_json_serializable(node.get("constraints", []))
                    }
                    serializable_nodes.append(serializable_node)
                elif hasattr(node, 'name') or hasattr(node, 'labels'):
                    # Node object - convert to dict format
                    node_name = ""
                    if hasattr(node, 'name'):
                        node_name = str(node.name)
                    elif hasattr(node, 'labels'):
                        labels = list(node.labels) if node.labels else []
                        node_name = labels[0] if labels else "Unknown"
                    else:
                        node_name = str(node)
                    
                    serializable_node = {
                        "name": node_name,
                        "indexes": _make_json_serializable(getattr(node, 'indexes', [])),
                        "constraints": _make_json_serializable(getattr(node, 'constraints', []))
                    }
                    serializable_nodes.append(serializable_node)
                else:
                    # String or other - keep as is but wrap in object format
                    node_name = str(node) if not isinstance(node, str) else node
                    serializable_nodes.append({
                        "name": node_name,
                        "indexes": [],
                        "constraints": []
                    })
            
            # Process relationships - convert Node objects to strings
            relationships = visualization_data.get("relationships", [])
            serializable_relationships = _make_json_serializable(relationships)
            
            serializable_data = {
                "nodes": serializable_nodes,
                "relationships": serializable_relationships
            }
            
            # Save to file
            VISUALIZATION_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(VISUALIZATION_FILE, "w") as f:
                # Use custom encoder as fallback in case any Node objects slip through
                json.dump(serializable_data, f, indent=2, ensure_ascii=False, cls=Neo4jJSONEncoder)
            
            if verbose:
                node_count = len(serializable_data.get("nodes", []))
                rel_count = len(serializable_data.get("relationships", []))
                print(f"✓ Visualization updated successfully!")
                print(f"  - Nodes: {node_count}")
                print(f"  - Relationships: {rel_count}")
                print(f"  - Saved to: {VISUALIZATION_FILE}")
            
            return True
            
    except Exception as e:
        if verbose:
            print(f"Error updating visualization: {e}")
        raise  # Re-raise so caller can handle it
    finally:
        close_driver()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Update graph visualization from Neo4j schema"
    )
    parser.add_argument(
        "--database",
        type=str,
        default=None,
        help="Neo4j database name (default: use default database)"
    )
    
    args = parser.parse_args()
    
    success = update_visualization(database=args.database)
    sys.exit(0 if success else 1)
