# Testing Strategy

Testing currently focuses on scripted smoke tests plus manual validation through the chat UI. Content from `TESTING_GUIDE.md` lives here so the docs site is authoritative.

## Prerequisites

- `.env` populated with Neo4j, OpenAI, Langfuse, and MongoDB credentials.
- Python 3.13+ virtual environment activated (`source venv/bin/activate`).
- Node.js 18+ installed.
- Neo4j instance reachable; Langfuse service running (external repo or Langfuse Cloud) if prompts are fetched from Langfuse.

## Scripted Workflow

### Manual Bring-Up

1. **Activate venv**
   ```bash
   source venv/bin/activate
   ```
2. **Install backend deps**
   ```bash
   pip install -r requirements.txt
   ```
3. **Start FastAPI**
   ```bash
   uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
   ```
4. **Install frontend deps**
   ```bash
   cd frontend
   npm install
   ```
5. **Create `frontend/.env.local`**
   ```
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```
6. **Run Next.js dev server**
   ```bash
   npm run dev  # defaults to http://localhost:3000 (or 3002 based on port availability)
   ```

## Manual Validation Scenarios

1. **Cypher Generation CLI**
   ```bash
   python ai/text_to_cypher.py "Return 5 Person nodes"
   EXECUTE_CYPHER=true OUTPUT_MODE=json python ai/text_to_cypher.py "Return 5 Person nodes"
   EXECUTE_CYPHER=true OUTPUT_MODE=chat python ai/text_to_cypher.py "Return 5 Person nodes"
   ```
2. **Chat UI**
   - Visit `http://localhost:3000`.
   - Ask multi-turn questions, confirm progress cards indicate whether analytics agent was used.
3. **Knowledge Base**
   - Favorite or edit categories in the UI; verify MongoDB entries update.
4. **Langfuse Traces**
   - Check `http://localhost:3001` to confirm prompts and tool calls are recorded with the correct label.

## Troubleshooting

- **Backend won’t start**: double-check env vars, ensure Neo4j credentials are valid, reinstall dependencies.
- **Frontend can’t reach backend**: verify FastAPI is running on `http://localhost:8000`, update `NEXT_PUBLIC_API_URL`, and confirm CORS settings.
- **API errors**: read backend logs, test endpoints via curl/Postman, or hit `http://localhost:8000/docs`.

## Additional Testing

For MCP analytics agent verification, use `python ai/mcp_client.py --interactive` to manually test tool discovery and invocation.

## Future Work

- Adopt pytest for backend unit/integration tests plus Playwright for frontend e2e.
- Run scripts inside CI pipelines that gate merges.
- Capture fixture graph snapshots for deterministic regression tests.

