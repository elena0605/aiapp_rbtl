"""Helper function to update category information in Neo4j nodes."""

import os
from typing import Optional
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from utils_neo4j import get_session  # type: ignore

# Load environment variables
from dotenv import load_dotenv
load_dotenv(dotenv_path=str(ROOT / ".env"))

VECTOR_NODE_LABEL = os.getenv("VECTOR_NODE_LABEL", "QueryExample")


def update_category_in_neo4j(
    category_name: str,
    new_category_name: Optional[str] = None,
    category_description: Optional[str] = None,
    database: Optional[str] = None
) -> None:
    """Update category information in all Neo4j nodes with this category.
    
    Args:
        category_name: Current category name
        new_category_name: New category name (if renaming)
        category_description: New category description
        database: Neo4j database name (None for default)
    """
    with get_session(database=database) as session:
        # Build update query dynamically
        updates = []
        params = {"old_name": category_name}
        
        if new_category_name and new_category_name != category_name:
            updates.append("n.category_name = $new_name")
            params["new_name"] = new_category_name
        
        if category_description is not None:
            updates.append("n.category_description = $category_description")
            params["category_description"] = category_description
        
        if not updates:
            return  # Nothing to update
        
        update_query = f"""
        MATCH (n:{VECTOR_NODE_LABEL} {{category_name: $old_name}})
        SET {', '.join(updates)}
        """
        session.run(update_query, params)

