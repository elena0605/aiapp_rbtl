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
# Environment Selection
ENVIRONMENT=production  # Set to "development" to use _DEV variables (default: production)

# Neo4j Configuration (Production)
NEO4J_URI=neo4j+s://your-db-id.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password

# Neo4j Configuration (Development - Optional)
# When ENVIRONMENT=development, these will be used instead of production values
# If not set, falls back to production values
NEO4J_URI_DEV=neo4j://127.0.0.1:7687
NEO4J_USER_DEV=neo4j
NEO4J_PASSWORD_DEV=local-password

# Langfuse Configuration (Production)
LANGFUSE_HOST=http://localhost:3001
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...

# Langfuse Configuration (Development - Optional)
# When ENVIRONMENT=development, these will be used instead of production values
# If not set, falls back to production values
LANGFUSE_HOST_DEV=http://localhost:3001
LANGFUSE_PUBLIC_KEY_DEV=pk-lf-dev-...
LANGFUSE_SECRET_KEY_DEV=sk-lf-dev-...

# OpenAI Configuration
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-4o  # Optional, defaults to gpt-4o

# Optional Configuration
PROMPT_LABEL=production  # Optional, defaults to production

# Graph Analytics Agent (Experimental)
ENABLE_ANALYTICS_AGENT=false  # Set to true to enable graph analytics tools (leiden, article_rank, bridges, etc.)
                              # Default: false (all questions use text-to-Cypher route)

# MongoDB Configuration (Production)
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority
MONGODB_DATABASE=graphrag  # Optional, defaults to graphrag

# MongoDB Configuration (Development - Optional)
# When ENVIRONMENT=development, these will be used instead of production values
# If not set, falls back to production values
MONGODB_URI_DEV=mongodb://localhost:27017
MONGODB_DATABASE_DEV=social_media  # or MONGODB_DB_DEV=social_media
```

#### Environment Switching

The application supports switching between **development** and **production** environments using the `ENVIRONMENT` variable:

- **Production (default)**: Set `ENVIRONMENT=production` or omit it. Uses standard variable names (`NEO4J_URI`, `MONGODB_URI`, etc.)
- **Development**: Set `ENVIRONMENT=development`. Uses `_DEV` suffixed variables (`NEO4J_URI_DEV`, `MONGODB_URI_DEV`, etc.)

**How it works:**
- When `ENVIRONMENT=development`, the app looks for `_DEV` variables first
- If `_DEV` variables are not set, it falls back to production variables
- This allows you to override only the variables you need for local development

**Example:** To use a local Neo4j instance for development while keeping production MongoDB:
```bash
ENVIRONMENT=development
NEO4J_URI_DEV=neo4j://127.0.0.1:7687
NEO4J_USER_DEV=neo4j
NEO4J_PASSWORD_DEV=local-password
# MongoDB will use production MONGODB_URI since MONGODB_URI_DEV is not set
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
│   ├── fewshots/          # Few-shot examples in YAML format
│   │   ├── generate_query_categories.py # Generate query categories using query-category-builder
│   │   └── generate_examples.py # Generate query examples for each category
│   ├── llmops/           # Langfuse client and tracing
│   ├── prompts/          # Prompt templates (YAML)
│   ├── schema/           # Neo4j schema utilities
│   ├── terminology/       # Domain terminology definitions
│   └── text_to_cypher.py # Main entry point
├── docker-compose.langfuse.yml  # Langfuse Docker setup
├── requirements.txt      # Python dependencies
└── utils/               # Shared utilities
    └── neo4j.py         # Neo4j connection utilities
```

## Usage

See the Testing Guide section above for detailed usage examples. The main command is:

```bash
python ai/text_to_cypher.py "Your question here"
```

### Generate Query Categories

Generate query categories using the query-category-builder prompt:

```bash
# Generate query categories (saves to ai/fewshots/graph_categories.json by default)
python ai/fewshots/generate_query_categories.py

# With custom output file
OUTPUT_FILE=my_categories.json python ai/fewshots/generate_query_categories.py

# With debug output
DEBUG_PROMPT=true python ai/fewshots/generate_query_categories.py

# Force schema refresh
UPDATE_NEO4J_SCHEMA=true python ai/fewshots/generate_query_categories.py
```

**Structured JSON Output:**

The script uses `response_format={"type": "json_object"}` which ensures the model returns valid JSON. Make sure your Langfuse prompt template instructs the model to return JSON in the desired format (e.g., with `category_name` and `category_description` fields).

### Generate Query Examples

Generate query examples for each category using the query-examples-builder prompt:

```bash
# Generate query examples (reads from ai/fewshots/graph_categories.json by default)
python ai/fewshots/generate_examples.py

# With custom categories file
CATEGORIES_FILE=ai/fewshots/graph_categories_v2.json python ai/fewshots/generate_examples.py

# With custom output file
OUTPUT_FILE=my_examples.json python ai/fewshots/generate_examples.py
```

This script:
1. Reads categories from a JSON file (default: `ai/fewshots/graph_categories.json`)
2. For each category, calls the `query-examples-builder` prompt with `category_name` and `category_description`
3. Generates question-cypher pairs (natural language question + corresponding Cypher query) for each category
4. Outputs JSON with `category_name` and `examples` list (each example has `question` and `cypher`)
5. Saves to `ai/fewshots/query_examples.json` by default

**Output Format:**
```json
[
  {
    "category_name": "Entity lookup and profiling",
    "examples": [
      {
        "question": "Return all Person nodes with their properties",
        "cypher": "MATCH (p:Person) RETURN p LIMIT 100"
      },
      {
        "question": "Find TikTokUser accounts with verification status",
        "cypher": "MATCH (t:TikTokUser) WHERE t.is_verified = true RETURN t"
      },
      ...
    ]
  },
  ...
]
```

For more examples and advanced usage, refer to the Testing Guide section above.

## Graph Analytics Agent (Experimental)

The project includes an experimental graph analytics agent that can route questions to graph algorithms (community detection, influence ranking, etc.) using the Neo4j GDS Agent via MCP.

### Configuration

By default, the analytics agent is **disabled**. All questions will use the text-to-Cypher route.

To enable the analytics agent for testing:

1. **Set environment variable** in your `.env` file:
   ```bash
   ENABLE_ANALYTICS_AGENT=true
   ```

2. **Restart the backend server**

3. **Test with analytics questions**:
   - "Find communities of people in Rotterdam"
   - "Which influencers are most important?"
   - "Show me bridge connections in the network"

### How It Works

When enabled, the system will:
1. First attempt to route the question to an analytics tool (if appropriate)
2. If no analytics tool is suitable, fall back to text-to-Cypher
3. The progress card in the UI shows which route was taken

### Current Status

- **Production**: Analytics agent is disabled by default
- **Testing**: Enable with `ENABLE_ANALYTICS_AGENT=true` to test graph algorithms
- **Available Tools**: `leiden` (community detection), `article_rank` (influence ranking), `bridges` (critical connections), `count_nodes` (statistics)

For more details, see [GRAPH_ANALYTICS_GUIDE.md](GRAPH_ANALYTICS_GUIDE.md).

## MCP Client Integration

This project can connect as an MCP client to other MCP servers, such as the [Neo4j GDS Agent](https://github.com/neo4j-contrib/gds-agent) for graph data science algorithms.

### Using Neo4j GDS Agent

1. **Install the GDS Agent** (if using as standalone):
   ```bash
   pip install gds-agent
   ```

2. **Use the MCP client**:
   ```bash
   # Normal mode (one-time test)
   python ai/mcp_client.py
   
   # Interactive mode (continuous testing)
   python ai/mcp_client.py --interactive
   ```
   
   Or use it in your code:
   ```python
   from ai.mcp_client import create_client
   import asyncio
   
   async def main():
       client = await create_client()
       tools = await client.list_tools()
       result = await client.call_tool("get_node_labels", {})
       await client.close()  # Don't forget to close!
       
       # List available tools
       tools = await client.list_tools()
       for tool in tools:
           print(f"{tool.name}: {tool.description}")
       
       # Call a tool
       result = await client.call_tool("tool_name", {"param": "value"})
       print(result)
       
       await client.close()
   
   asyncio.run(main())
   ```

3. **Configuration**: The client uses the same Neo4j credentials from your `.env` file:
   - `NEO4J_URI`
   - `NEO4J_USERNAME` or `NEO4J_USER`
   - `NEO4J_PASSWORD`
   - `NEO4J_DATABASE` (optional)

For more details, see the [GDS Agent documentation](https://github.com/neo4j-contrib/gds-agent).

## Dependencies

- **neo4j** - Neo4j database driver
- **langfuse** - LLM observability and prompt management
- **openai** - OpenAI SDK
- **python-dotenv** - Environment variable management
- **pyyaml** - YAML parsing for prompts and examples
- **mcp** - MCP (Model Context Protocol) Client SDK

## License

[Add your license here]

## Contributing

[Add contribution guidelines here]

