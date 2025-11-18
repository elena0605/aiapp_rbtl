# Neo4j Vector Store Inspection Queries

Use these queries in Neo4j Browser to inspect your vector database.

## Access Neo4j Browser

1. **Neo4j Aura**: Go to your Aura instance → "Open" button → Opens Neo4j Browser
2. **Self-hosted**: Navigate to `http://localhost:7474` (or your Neo4j URL)

## Useful Queries

### 1. View All Query Examples

```cypher
MATCH (n:QueryExample)
RETURN n.question AS question, 
       n.cypher AS cypher, 
       n.category_name AS category,
       n.added_at AS added_at
LIMIT 20
```

### 2. Count Total Examples

```cypher
MATCH (n:QueryExample)
RETURN count(n) AS total_examples
```

### 3. View Examples by Category

```cypher
MATCH (n:QueryExample)
RETURN n.category_name AS category, 
       count(n) AS example_count
ORDER BY example_count DESC
```

### 4. Check Vector Index Status

```cypher
SHOW INDEXES
YIELD name, type, state, populationPercent
WHERE type = 'VECTOR'
RETURN name, type, state, populationPercent
```

### 5. View Index Details

```cypher
SHOW INDEXES
YIELD name, type, state, populationPercent, properties
WHERE name = 'query_examples_embeddings'
RETURN name, type, state, populationPercent, properties
```

### 6. Test Vector Search (Manual)

Replace `$query_embedding` with an actual embedding vector (1536 dimensions):

```cypher
CALL db.index.vector.queryNodes(
    'query_examples_embeddings',
    5,
    $query_embedding
)
YIELD node, score
RETURN node.question AS question,
       node.cypher AS cypher,
       score
ORDER BY score DESC
```

### 7. View Example with Embedding Dimensions

```cypher
MATCH (n:QueryExample)
RETURN n.question AS question,
       size(n.embedding) AS embedding_dimensions,
       n.category_name AS category
LIMIT 5
```

### 8. Find Examples Without Embeddings

```cypher
MATCH (n:QueryExample)
WHERE n.embedding IS NULL
RETURN n.question AS question, n.cypher AS cypher
```

### 9. View Recent Examples

```cypher
MATCH (n:QueryExample)
WHERE n.added_at IS NOT NULL
RETURN n.question AS question,
       n.category_name AS category,
       n.added_at AS added_at
ORDER BY n.added_at DESC
LIMIT 10
```

### 10. Visualize Example Relationships (if you add relationships later)

```cypher
MATCH (n:QueryExample)
RETURN n
LIMIT 50
```

Then click on nodes in Neo4j Browser to see properties.

## Notes

- **Embeddings are vectors**: The `embedding` property contains a 1536-dimensional vector array (not human-readable)
- **Index name**: Default is `query_examples_embeddings` (configurable via `VECTOR_INDEX_NAME`)
- **Node label**: Default is `QueryExample` (configurable via `VECTOR_NODE_LABEL`)
- **Vector search**: Use `db.index.vector.queryNodes()` for similarity search

## Quick Stats Query

```cypher
MATCH (n:QueryExample)
WITH count(n) AS total,
     collect(DISTINCT n.category_name) AS categories,
     sum(CASE WHEN n.embedding IS NOT NULL THEN 1 ELSE 0 END) AS with_embeddings
RETURN total AS total_examples,
       size(categories) AS unique_categories,
       with_embeddings AS examples_with_embeddings,
       total - with_embeddings AS examples_without_embeddings
```

