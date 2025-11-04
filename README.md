# rbtl_graphrag

GraphRAG (Graph Retrieval-Augmented Generation) project for querying Neo4j graph databases using natural language.

## Overview

This project provides a natural language interface to Neo4j graph databases. It uses LLMs to convert user questions into Cypher queries, executes them, and provides conversational summaries of the results.

## Features

- **Natural Language to Cypher**: Convert questions into Cypher queries using LLMs
- **Schema-Aware**: Uses Neo4j schema to generate accurate queries
- **Prompt Management**: Prompts stored and versioned in Langfuse
- **Observability**: Full tracing of LLM calls via Langfuse
- **Conversational Results**: Natural language summaries of query results

## Testing Guide

Quick setup guide to get the project up and running.

### Step 1: Create Virtual Environment

```bash
cd /Users/bojansimoski/dev/rbtl_graphrag
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate  # On Windows
```

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Create .env File

Create a `.env` file in the project root with the following variables:

```bash
# Neo4j Configuration
NEO4J_URI=neo4j+s://your-db-id.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password

# Langfuse Configuration (for self-hosted via Docker)
LANGFUSE_HOST=http://localhost:3001
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...

# OpenAI Configuration
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-4o  # Optional, defaults to gpt-4o

# Optional Configuration
PROMPT_LABEL=production  # Optional, defaults to production
```

**To get Langfuse keys (if you are not provided with keys already):**
1. Start Langfuse (Step 4)
2. Go to http://localhost:3001
3. Create an account/login
4. Go to Settings → API Keys
5. Create a new API key and copy the public and secret keys

### Step 4: Start Langfuse with Docker

```bash
docker-compose -f docker-compose.langfuse.yml up -d
```

Wait for services to be healthy (about 30 seconds), then verify:
- Langfuse UI: http://localhost:3001
- PostgreSQL: localhost:5433
- ClickHouse: localhost:8123

**To stop Langfuse:**
```bash
docker-compose -f docker-compose.langfuse.yml down
```

**To view logs:**
```bash
docker-compose -f docker-compose.langfuse.yml logs -f
```

### Step 5: Test the Setup

#### Test 1: Generate Cypher (Dry Run)

```bash
python ai/text_to_cypher.py "Return 5 Person nodes"
```

**Expected output:**
- Generated Cypher query (e.g., `MATCH (p:Person) RETURN p LIMIT 5`)
- No execution errors

#### Test 2: Generate and Execute Cypher (JSON Output)

```bash
EXECUTE_CYPHER=true OUTPUT_MODE=json python ai/text_to_cypher.py "Return 5 Person nodes"
```

**Expected output:**
- Generated Cypher query
- JSON results from Neo4j
- No errors

#### Test 3: Generate and Execute with Chat Summary

```bash
EXECUTE_CYPHER=true OUTPUT_MODE=chat python ai/text_to_cypher.py "Return 5 Person nodes"
```

**Expected output:**
- Generated Cypher query
- JSON results
- Natural language summary of results

#### Test 4: View Schema Only

```bash
python ai/text_to_cypher.py --schema
```

**Expected output:**
- Neo4j schema information
- No errors

#### Test 5: Debug Prompt

```bash
DEBUG_PROMPT=true python ai/text_to_cypher.py "Return 5 Person nodes"
```

**Expected output:**
- Full rendered prompt sent to LLM
- Generated Cypher query

### Troubleshooting

#### Import Errors
```bash
# Ensure virtual environment is activated
source venv/bin/activate
pip install -r requirements.txt
```

#### Neo4j Connection Failed
- Check `.env` file has correct `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
- Verify Neo4j instance is running and accessible
- Test connection: `neo4j://...` or `neo4j+s://...` format

#### Langfuse Connection Failed
- Ensure Docker containers are running: `docker-compose -f docker-compose.langfuse.yml ps`
- Check `.env` file has correct `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`
- Verify Langfuse UI is accessible: http://localhost:3001
- Ensure prompts exist in Langfuse with correct names and labels

#### OpenAI API Errors
- Check `.env` file has valid `OPENAI_API_KEY`
- Verify API key has credits/quota
- Check model name is correct (e.g., `gpt-4o`)

#### Prompt Not Found
- Ensure prompts are synced to Langfuse
- Check prompt names match (dots become dashes: `graph.text_to_cypher` → `graph-text-to-cypher`)
- Verify prompt has the `production` label (or set `PROMPT_LABEL` in `.env`)

### Quick Reference

**Environment Variables:**
- `EXECUTE_CYPHER=true/false` - Execute generated Cypher (default: true)
- `OUTPUT_MODE=json/chat/both` - Output format (default: json)
- `DEBUG_PROMPT=true/false` - Show full prompt (default: false)
- `SCHEMA_ONLY=true/false` - Show schema only (default: false)
- `UPDATE_NEO4J_SCHEMA=true` - Force schema refresh from Neo4j

**Common Commands:**
```bash
# Activate venv
source venv/bin/activate

# Start Langfuse
docker-compose -f docker-compose.langfuse.yml up -d

# Stop Langfuse
docker-compose -f docker-compose.langfuse.yml down

# Run basic test
python ai/text_to_cypher.py "Return 5 Person nodes"

# Run with execution and chat summary
EXECUTE_CYPHER=true OUTPUT_MODE=chat python ai/text_to_cypher.py "Return 5 Person nodes"
```

## Project Structure

```
rbtl_graphrag/
├── ai/
│   ├── examples/          # Example queries in YAML format
│   ├── llmops/           # Langfuse client and tracing
│   ├── prompts/          # Prompt templates (YAML)
│   ├── schema/           # Neo4j schema utilities
│   ├── terminology/       # Domain terminology definitions
│   └── text_to_cypher.py # Main entry point
├── docker-compose.langfuse.yml  # Langfuse Docker setup
├── requirements.txt      # Python dependencies
└── utils_neo4j.py       # Neo4j connection utilities
```

## Usage

See the Testing Guide section above for detailed usage examples. The main command is:

```bash
python ai/text_to_cypher.py "Your question here"
```

For more examples and advanced usage, refer to the Testing Guide section above.

## Dependencies

- **neo4j** - Neo4j database driver
- **langfuse** - LLM observability and prompt management
- **openai** - OpenAI SDK
- **python-dotenv** - Environment variable management
- **pyyaml** - YAML parsing for prompts and examples

## License

[Add your license here]

## Contributing

[Add contribution guidelines here]

