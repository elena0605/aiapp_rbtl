"""Service to sync query examples between MongoDB and Neo4j vector store."""

import os
from typing import Optional
from openai import OpenAI
from neo4j import Session

# Import Neo4j utilities
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from utils_neo4j import get_session, get_driver  # type: ignore

# Load environment variables
from dotenv import load_dotenv
load_dotenv(dotenv_path=str(ROOT / ".env"))


def _get_required_env(key: str) -> str:
    """Get required environment variable."""
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"Required environment variable '{key}' not found")
    return value


# Get configuration from environment
EMBEDDING_MODEL = _get_required_env("EMBEDDING_MODEL")
VECTOR_INDEX_NAME = _get_required_env("VECTOR_INDEX_NAME")
VECTOR_NODE_LABEL = _get_required_env("VECTOR_NODE_LABEL")


def _get_openai_client() -> OpenAI:
    """Get OpenAI client for embeddings."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not found")
    return OpenAI(api_key=api_key)


def add_example_to_neo4j(
    question: str,
    cypher: str,
    category_name: str,
    added_at: Optional[str] = None,
    category_description: Optional[str] = None,
    created_by: Optional[str] = None,
    database: Optional[str] = None
) -> None:
    """Add a query example to Neo4j vector store.
    
    Args:
        question: User question text
        cypher: Cypher query
        category_name: Category name
        added_at: Timestamp (optional)
        category_description: Category description (optional)
        database: Neo4j database name (None for default)
    """
    # Generate embedding for the question
    openai_client = _get_openai_client()
    try:
        response = openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=[question],
        )
        embedding = response.data[0].embedding
    except Exception as e:
        raise RuntimeError(f"Failed to generate embedding: {str(e)}")
    
    # Add to Neo4j
    with get_session(database=database) as session:
        upsert_query = f"""
        MERGE (n:{VECTOR_NODE_LABEL} {{question: $question}})
        SET n.cypher = $cypher,
            n.embedding = $embedding,
            n.category_name = $category_name,
            n.category_description = $category_description,
            n.added_at = $added_at,
            n.created_by = $created_by
        """
        session.run(upsert_query, {
            "question": question,
            "cypher": cypher,
            "embedding": embedding,
            "category_name": category_name,
            "category_description": category_description or "",
            "added_at": added_at or "",
            "created_by": created_by or "",
        })


def delete_example_from_neo4j(
    question: str,
    database: Optional[str] = None
) -> bool:
    """Delete a query example from Neo4j vector store.
    
    Args:
        question: User question text (used to identify the node)
        database: Neo4j database name (None for default)
    
    Returns:
        True if node was deleted, False if not found
    """
    with get_session(database=database) as session:
        delete_query = f"""
        MATCH (n:{VECTOR_NODE_LABEL} {{question: $question}})
        DELETE n
        RETURN count(n) AS deleted_count
        """
        result = session.run(delete_query, {"question": question})
        record = result.single()
        if record:
            return record["deleted_count"] > 0
        return False


def ensure_vector_index(database: Optional[str] = None) -> None:
    """Ensure the vector index exists in Neo4j."""
    with get_session(database=database) as session:
        # Check if index exists
        check_query = """
        SHOW INDEXES
        YIELD name, type
        WHERE name = $index_name AND type = 'VECTOR'
        RETURN name
        """
        result = session.run(check_query, {"index_name": VECTOR_INDEX_NAME})
        
        if result.single() is None:
            # Create vector index
            create_query = f"""
            CREATE VECTOR INDEX {VECTOR_INDEX_NAME} IF NOT EXISTS
            FOR (n:{VECTOR_NODE_LABEL})
            ON n.embedding
            OPTIONS {{
                indexConfig: {{
                    `vector.dimensions`: 1536,
                    `vector.similarity`: 'cosine'
                }}
            }}
            """
            try:
                session.run(create_query)
                print(f"✓ Created vector index: {VECTOR_INDEX_NAME}")
            except Exception as e:
                # Index might already exist or Neo4j version doesn't support it
                print(f"Note: Could not create vector index (may already exist): {e}")

