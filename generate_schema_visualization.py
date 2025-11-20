#!/usr/bin/env python3
"""Generate Neo4j schema visualization once and save as JSON."""

import json
import sys
from pathlib import Path

from utils_neo4j import get_session

SCHEMA_DIR = Path(__file__).parent / "ai" / "schema"
VISUALIZATION_FILE = SCHEMA_DIR / "visualization.json"


def generate_visualization():
    """Call db.schema.visualization() and save the result."""
    print("Connecting to Neo4j...")
    
    with get_session() as session:
        print("Calling db.schema.visualization()...")
        result = session.run("CALL db.schema.visualization()")
        records = list(result)
        
        if not records:
            print("ERROR: No data returned from db.schema.visualization()")
            sys.exit(1)
        
        # Extract the visualization data
        # The procedure typically returns one record with 'nodes' and 'relationships' fields
        visualization_data = {}
        
        for record in records:
            data = record.data()
            # Merge all fields from all records
            for key, value in data.items():
                if key in visualization_data:
                    # If key exists, try to merge lists
                    if isinstance(visualization_data[key], list) and isinstance(value, list):
                        visualization_data[key].extend(value)
                    elif isinstance(visualization_data[key], list):
                        visualization_data[key].append(value)
                    else:
                        visualization_data[key] = [visualization_data[key], value]
                else:
                    visualization_data[key] = value
        
        # Ensure we have nodes and relationships
        if "nodes" not in visualization_data and "relationships" not in visualization_data:
            # Try to find them in nested structures
            for key, value in visualization_data.items():
                if isinstance(value, dict):
                    if "nodes" in value:
                        visualization_data["nodes"] = value["nodes"]
                    if "relationships" in value:
                        visualization_data["relationships"] = value["relationships"]
        
        # Save to file
        SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
        
        with open(VISUALIZATION_FILE, "w") as f:
            json.dump(visualization_data, f, indent=2, default=str)
        
        node_count = len(visualization_data.get("nodes", []))
        rel_count = len(visualization_data.get("relationships", []))
        
        print(f"✓ Visualization saved to {VISUALIZATION_FILE}")
        print(f"  - Nodes: {node_count}")
        print(f"  - Relationships: {rel_count}")
        
        if node_count == 0 and rel_count == 0:
            print("\nWARNING: No nodes or relationships found in visualization data.")
            print("The raw data structure is:")
            print(json.dumps(visualization_data, indent=2, default=str)[:500])


if __name__ == "__main__":
    try:
        generate_visualization()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

