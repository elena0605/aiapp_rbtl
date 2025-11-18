"""Neo4j-based vector store for semantic similarity search over query examples.

This module provides:
- Embedding generation using OpenAI embeddings API
- Vector storage in Neo4j with native vector indexes
- Similarity search using Neo4j's db.index.vector.queryNodes()

Benefits:
- Uses existing Neo4j infrastructure (no additional services)
- Shared across all application instances
- Persistent and cloud-ready
- Native vector index support (Neo4j 5.11+)
- Scales with your Neo4j instance
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neo4j import Driver  # type: ignore
from openai import OpenAI  # type: ignore

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None  # type: ignore

# Import Neo4j utilities
import sys
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from utils_neo4j import get_driver, get_session  # type: ignore

# Load .env file at module level so environment variables are available for constants
if load_dotenv is not None:
    load_dotenv(dotenv_path=str(ROOT / ".env"))

# Environment variables (must be set in .env file, no defaults)
def _get_required_env(key: str) -> str:
    """Get required environment variable, raise error if not set."""
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{key}' not found. "
            f"Please set it in your .env file."
        )
    return value

DEFAULT_EMBEDDING_MODEL = _get_required_env("EMBEDDING_MODEL")
DEFAULT_INDEX_NAME = _get_required_env("VECTOR_INDEX_NAME")
DEFAULT_NODE_LABEL = _get_required_env("VECTOR_NODE_LABEL")


class VectorStore:
    """Vector store for query examples with similarity search using Neo4j."""
    
    def __init__(
        self,
        examples_file: Optional[Path] = None,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        index_name: str = DEFAULT_INDEX_NAME,
        node_label: str = DEFAULT_NODE_LABEL,
        database: Optional[str] = None,
    ):
        """Initialize the vector store.
        
        Args:
            examples_file: Path to query_examples.json file
            embedding_model: OpenAI embedding model to use
            index_name: Name of the vector index in Neo4j
            node_label: Label for nodes storing examples
            database: Neo4j database name (None for default)
        """
        # Determine examples file path
        if examples_file is None:
            fewshots_dir = Path(__file__).resolve().parent
            examples_file = fewshots_dir / "query_examples.json"
        
        self.examples_file = Path(examples_file)
        self.embedding_model = embedding_model
        self.index_name = index_name
        self.node_label = node_label
        self.database = database
        
        # Load .env if available
        if load_dotenv is not None:
            project_root = self.examples_file.resolve().parents[2]
            load_dotenv(dotenv_path=str(project_root / ".env"))
        
        # Initialize OpenAI client
        self.openai_client = None
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            self.openai_client = OpenAI(api_key=api_key)
        else:
            raise RuntimeError(
                "OPENAI_API_KEY not found. Set OPENAI_API_KEY in .env or environment variables."
            )
        
        # Get Neo4j driver
        self.driver = get_driver()
        
        # Initialize vector index
        self._ensure_vector_index()
        
        # Load and sync examples
        self._load_and_sync_examples()
    
    def _ensure_vector_index(self) -> None:
        """Create vector index if it doesn't exist."""
        # Get embedding dimension (text-embedding-3-small is 1536 dimensions)
        embedding_dim = 1536  # Default for text-embedding-3-small
        if "large" in self.embedding_model.lower():
            embedding_dim = 3072
        elif "3" in self.embedding_model and "small" in self.embedding_model.lower():
            embedding_dim = 1536
        
        with get_session(database=self.database) as session:
            # Check if index exists
            check_query = f"""
            SHOW INDEXES
            YIELD name, type, state
            WHERE name = $index_name AND type = 'VECTOR'
            RETURN name
            """
            result = session.run(check_query, {"index_name": self.index_name})
            exists = result.single() is not None
            
            if not exists:
                # Create vector index
                create_query = f"""
                CREATE VECTOR INDEX {self.index_name}
                FOR (n:{self.node_label})
                ON n.embedding
                OPTIONS {{
                    indexConfig: {{
                        `vector.dimensions`: {embedding_dim},
                        `vector.similarity_function`: 'cosine'
                    }}
                }}
                """
                try:
                    session.run(create_query)
                    print(f"✓ Created vector index '{self.index_name}' in Neo4j")
                except Exception as e:
                    # Index might already exist or Neo4j version doesn't support it
                    if "already exists" in str(e).lower() or "exist" in str(e).lower():
                        print(f"✓ Vector index '{self.index_name}' already exists")
                    else:
                        raise RuntimeError(
                            f"Failed to create vector index. "
                            f"Ensure Neo4j version 5.11+ is installed. Error: {e}"
                        ) from e
            else:
                print(f"✓ Vector index '{self.index_name}' exists")
    
    def _load_and_sync_examples(self) -> None:
        """Load examples from JSON and sync with Neo4j."""
        if not self.examples_file.exists():
            raise FileNotFoundError(
                f"Examples file not found: {self.examples_file}. "
                "Run generate_examples.py to create query examples first."
            )
        
        try:
            content = json.loads(self.examples_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {self.examples_file}: {e}") from e
        
        # Flatten examples from all categories
        examples = []
        if isinstance(content, list):
            for category in content:
                category_name = category.get("category_name", "")
                category_examples = category.get("examples", [])
                for ex in category_examples:
                    question = ex.get("question", "").strip()
                    cypher = ex.get("cypher", "").strip()
                    if question and cypher:
                        examples.append({
                            "question": question,
                            "cypher": cypher,
                            "category_name": category_name,
                            "added_at": ex.get("added_at"),
                        })
        
        if len(examples) == 0:
            raise ValueError(
                f"No valid examples found in {self.examples_file}. "
                "Ensure the file contains examples with 'question' and 'cypher' fields."
            )
        
        print(f"Loaded {len(examples)} examples from {self.examples_file}")
        
        # Sync with Neo4j
        self._sync_examples_to_neo4j(examples)
    
    def _sync_examples_to_neo4j(self, examples: List[Dict[str, Any]]) -> None:
        """Sync examples to Neo4j, updating embeddings if needed."""
        with get_session(database=self.database) as session:
            # Get existing examples from Neo4j
            # Use OPTIONAL MATCH to avoid warnings if nodes don't exist yet
            existing_query = f"""
            MATCH (n:{self.node_label})
            WHERE n.question IS NOT NULL
            RETURN n.question AS question, n.cypher AS cypher, n.embedding AS embedding
            """
            existing = {}
            try:
                for row in session.run(existing_query):
                    if row["question"]:
                        existing[row["question"]] = row
            except Exception as e:
                # If query fails (e.g., no nodes exist yet), start with empty dict
                print(f"  Note: No existing examples found in Neo4j (this is normal on first run)")
                existing = {}
            
            # Process examples in batches
            batch_size = 50
            new_count = 0
            updated_count = 0
            skipped_count = 0
            
            for i in range(0, len(examples), batch_size):
                batch = examples[i:i + batch_size]
                
                for ex in batch:
                    question = ex["question"]
                    cypher = ex["cypher"]
                    category_name = ex.get("category_name", "")
                    added_at = ex.get("added_at", "")
                    
                    # Check if example exists and needs update
                    existing_ex = existing.get(question)
                    needs_update = (
                        existing_ex is None or
                        existing_ex["cypher"] != cypher or
                        existing_ex["embedding"] is None
                    )
                    
                    if not needs_update:
                        skipped_count += 1
                        continue
                    
                    # Generate embedding
                    try:
                        response = self.openai_client.embeddings.create(
                            model=self.embedding_model,
                            input=[question],  # Embed only the question for similarity
                        )
                        embedding = response.data[0].embedding
                    except Exception as e:
                        print(f"⚠️  Error generating embedding for example: {e}")
                        continue
                    
                    # Upsert node
                    upsert_query = f"""
                    MERGE (n:{self.node_label} {{question: $question}})
                    SET n.cypher = $cypher,
                        n.embedding = $embedding,
                        n.category_name = $category_name,
                        n.added_at = $added_at
                    """
                    session.run(upsert_query, {
                        "question": question,
                        "cypher": cypher,
                        "embedding": embedding,
                        "category_name": category_name,
                        "added_at": added_at,
                    })
                    
                    if existing_ex is None:
                        new_count += 1
                    else:
                        updated_count += 1
                
                # Neo4j auto-commits on session.run(), no explicit commit needed
            
            print(f"✓ Synced examples to Neo4j: {new_count} new, {updated_count} updated, {skipped_count} unchanged")
    
    def search(
        self,
        query: str,
        top_k: int = 5,
        min_similarity: float = 0.0,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Search for similar examples using Neo4j vector index.
        
        Args:
            query: User query text to search for
            top_k: Number of top results to return
            min_similarity: Minimum cosine similarity threshold (0.0 to 1.0)
        
        Returns:
            List of tuples (example_dict, similarity_score) sorted by similarity (highest first)
        """
        # Generate embedding for query
        try:
            response = self.openai_client.embeddings.create(
                model=self.embedding_model,
                input=[query],
            )
            query_embedding = response.data[0].embedding
        except Exception as e:
            print(f"⚠️  Error generating query embedding: {e}")
            return []
        
        # Search using Neo4j vector index
        with get_session(database=self.database) as session:
            search_query = f"""
            CALL db.index.vector.queryNodes(
                $index_name,
                $top_k,
                $query_embedding
            )
            YIELD node, score
            WHERE score >= $min_similarity
            RETURN node.question AS question,
                   node.cypher AS cypher,
                   node.category_name AS category_name,
                   node.added_at AS added_at,
                   score
            ORDER BY score DESC
            LIMIT $top_k
            """
            
            try:
                result = session.run(search_query, {
                    "index_name": self.index_name,
                    "top_k": top_k,
                    "query_embedding": query_embedding,
                    "min_similarity": min_similarity,
                })
                
                results = []
                for row in result:
                    example = {
                        "question": row["question"],
                        "cypher": row["cypher"],
                        "metadata": {
                            "category_name": row.get("category_name"),
                            "added_at": row.get("added_at"),
                        },
                    }
                    similarity = float(row["score"])
                    results.append((example, similarity))
                
                return results
            except Exception as e:
                # Fallback if vector index query fails (e.g., older Neo4j version)
                print(f"⚠️  Vector index query failed: {e}")
                print("  Falling back to manual similarity calculation...")
                return self._fallback_search(query, query_embedding, top_k, min_similarity)
    
    def _fallback_search(
        self,
        query: str,
        query_embedding: List[float],
        top_k: int,
        min_similarity: float,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Fallback search using manual cosine similarity calculation."""
        import numpy as np
        
        with get_session(database=self.database) as session:
            # Get all examples with embeddings
            get_all_query = f"""
            MATCH (n:{self.node_label})
            WHERE n.embedding IS NOT NULL
            RETURN n.question AS question,
                   n.cypher AS cypher,
                   n.embedding AS embedding,
                   n.category_name AS category_name,
                   n.added_at AS added_at
            """
            result = session.run(get_all_query)
            
            query_vec = np.array(query_embedding, dtype=np.float32)
            query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
            
            similarities = []
            for row in result:
                embedding = row["embedding"]
                if embedding is None:
                    continue
                
                emb_vec = np.array(embedding, dtype=np.float32)
                emb_norm = emb_vec / (np.linalg.norm(emb_vec) + 1e-10)
                similarity = float(np.dot(emb_norm, query_norm))
                
                if similarity >= min_similarity:
                    example = {
                        "question": row["question"],
                        "cypher": row["cypher"],
                        "metadata": {
                            "category_name": row.get("category_name"),
                            "added_at": row.get("added_at"),
                        },
                    }
                    similarities.append((example, similarity))
            
            # Sort by similarity and return top_k
            similarities.sort(key=lambda x: x[1], reverse=True)
            return similarities[:top_k]
    
    def get_examples_text(self, query: str, top_k: int = 5) -> str:
        """Get similar examples formatted as text for prompt injection.
        
        Args:
            query: User query text
            top_k: Number of examples to return
        
        Returns:
            Formatted text string with Question/Cypher pairs
        """
        results = self.search(query, top_k=top_k)
        
        if not results:
            return ""
        
        pairs = []
        for example, similarity in results:
            question = example["question"]
            cypher = example["cypher"]
            pairs.append(f"Question: {question}\nCypher: {cypher}")
        
        return "\n".join(pairs)


# Global singleton instance (lazy-loaded)
_vector_store_instance: Optional[VectorStore] = None


def get_vector_store(
    examples_file: Optional[Path] = None,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    index_name: str = DEFAULT_INDEX_NAME,
    node_label: str = DEFAULT_NODE_LABEL,
    database: Optional[str] = None,
    force_reload: bool = False,
) -> VectorStore:
    """Get or create the global vector store instance.
    
    Args:
        examples_file: Path to query_examples.json (only used on first call)
        embedding_model: Embedding model to use (only used on first call)
        index_name: Vector index name (only used on first call)
        node_label: Node label (only used on first call)
        database: Neo4j database name (only used on first call)
        force_reload: Force reload even if instance exists
    
    Returns:
        VectorStore instance
    """
    global _vector_store_instance
    
    if _vector_store_instance is None or force_reload:
        _vector_store_instance = VectorStore(
            examples_file=examples_file,
            embedding_model=embedding_model,
            index_name=index_name,
            node_label=node_label,
            database=database,
        )
    
    return _vector_store_instance

