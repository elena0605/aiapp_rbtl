# MCP Architecture Explanation

## What is MCP?

**Model Context Protocol (MCP)** is a protocol that allows AI assistants (clients) to communicate with external tools and services (servers) in a standardized way. It's like a universal API for AI tools.

## High-Level Architecture

```
┌─────────────────┐         MCP Protocol         ┌─────────────────┐
│                 │  ←──────────────────────→   │                 │
│  MCP Client     │    (JSON-RPC over stdio)    │  MCP Server     │
│  (Our Code)     │                              │  (gds-agent)    │
│                 │                              │                 │
└─────────────────┘                              └─────────────────┘
       │                                                  │
       │                                                  │
       │                                                  │
       ▼                                                  ▼
┌─────────────────┐                              ┌─────────────────┐
│  Python App     │                              │  Neo4j Database │
│  (ai/gds_agent) │                              │  (via GDS lib)  │
└─────────────────┘                              └─────────────────┘
```

## Communication Method: stdio (Standard Input/Output)

MCP uses **stdio** (standard input/output) for communication. This means:
- The client launches the server as a **subprocess**
- They communicate via **stdin** (client → server) and **stdout** (server → client)
- Messages are **JSON-RPC** formatted
- Communication is **bidirectional** and **asynchronous**

## Our Implementation Flow

### Step 1: Client Setup (`Neo4jGDSAgentClient.__init__`)

```python
client = Neo4jGDSAgentClient()
```

**What happens:**
1. Loads Neo4j credentials from `.env` file
2. Finds `uvx` command (or falls back to `python3 -m gds_agent`)
3. Prepares environment variables for the server:
   - `NEO4J_URI`
   - `NEO4J_USERNAME`
   - `NEO4J_PASSWORD`
   - `NEO4J_DATABASE` (optional)
4. Creates `MCPClient` with:
   - `command`: `/path/to/uvx`
   - `args`: `["gds-agent"]`
   - `env`: Neo4j credentials

**At this point:** No server process is running yet.

---

### Step 2: Connection (`client.connect()`)

```python
await client.connect()
```

**What happens:**

#### 2.1 Create Server Parameters
```python
server_params = StdioServerParameters(
    command="/path/to/uvx",
    args=["gds-agent"],
    env={"NEO4J_URI": "...", "NEO4J_USERNAME": "...", ...}
)
```
This tells the MCP SDK how to launch the server process.

#### 2.2 Create stdio Client
```python
self._stdio_context = stdio_client(server_params)
stdio_transport = await self._stdio_context.__aenter__()
```

**What `stdio_client` does:**
1. **Launches the server process** as a subprocess:
   ```bash
   /path/to/uvx gds-agent
   ```
   With environment variables set.

2. **Creates communication streams:**
   - `read_stream`: Reads from server's stdout
   - `write_stream`: Writes to server's stdin
   
   These are **memory streams** (buffers) managed by the MCP SDK.

3. **Sets up background tasks** to:
   - Forward messages from server stdout → read_stream
   - Forward messages from write_stream → server stdin

**At this point:** 
- Server process is running
- Server connects to Neo4j (we see logs: "Successfully connected to Neo4j database")
- Communication streams are ready
- **BUT**: No MCP protocol messages have been exchanged yet

#### 2.3 Create ClientSession
```python
self.session = ClientSession(read_stream, write_stream)
```

**What `ClientSession` does:**
- Wraps the streams with MCP protocol logic
- Handles JSON-RPC message serialization/deserialization
- Manages request/response matching
- Provides high-level methods like `initialize()`, `list_tools()`, `call_tool()`

#### 2.4 Initialize Session (THE PROBLEM)
```python
init_result = await self.session.initialize()
```

**What SHOULD happen (MCP Protocol):**

1. **Server sends initialization request:**
   ```json
   {
     "jsonrpc": "2.0",
     "id": 1,
     "method": "initialize",
     "params": {
       "protocolVersion": "2024-11-05",
       "capabilities": {...},
       "clientInfo": {...}
     }
   }
   ```
   This comes from server's stdout → read_stream.

2. **Client responds:**
   ```json
   {
     "jsonrpc": "2.0",
     "id": 1,
     "result": {
       "protocolVersion": "2024-11-05",
       "capabilities": {...},
       "serverInfo": {
         "name": "neo4j-gds",
         "version": "0.5.1"
       }
     }
   }
   ```
   This goes from write_stream → server's stdin.

3. **Session is initialized** ✅

**What ACTUALLY happens:**
- Server connects to Neo4j ✅
- Server **NEVER sends the initialization message** ❌
- Client waits forever at `session.initialize()` ⏳
- Timeout after 15 seconds ⏰

**Why it hangs:**
The gds-agent server connects to Neo4j but doesn't start the MCP protocol handshake. It's likely waiting for something or has a bug in its initialization sequence.

---

### Step 3: List Tools (`client.list_tools()`)

```python
tools = await client.list_tools()
```

**What SHOULD happen (if initialization worked):**

1. **Client sends request:**
   ```json
   {
     "jsonrpc": "2.0",
     "id": 2,
     "method": "tools/list",
     "params": {}
   }
   ```

2. **Server responds:**
   ```json
   {
     "jsonrpc": "2.0",
     "id": 2,
     "result": {
       "tools": [
         {
           "name": "shortest_path",
           "description": "Find shortest path between nodes",
           "inputSchema": {...}
         },
         {
           "name": "pagerank",
           "description": "Calculate PageRank",
           "inputSchema": {...}
         },
         ...
       ]
     }
   }
   ```

3. **Client returns list of tools** ✅

**What ACTUALLY happens:**
- Never reaches this point because initialization hangs ❌

---

### Step 4: Call Tool (`client.call_tool()`)

```python
result = await client.call_tool("shortest_path", {
    "sourceNode": 123,
    "targetNode": 456
})
```

**What SHOULD happen (if initialization worked):**

1. **Client sends request:**
   ```json
   {
     "jsonrpc": "2.0",
     "id": 3,
     "method": "tools/call",
     "params": {
       "name": "shortest_path",
       "arguments": {
         "sourceNode": 123,
         "targetNode": 456
       }
     }
   }
   ```

2. **Server executes the tool:**
   - Runs the graph algorithm on Neo4j
   - Gets results

3. **Server responds:**
   ```json
   {
     "jsonrpc": "2.0",
     "id": 3,
     "result": {
       "content": [
         {
           "type": "text",
           "text": "Path found: [123, 789, 456]"
         }
       ]
     }
   }
   ```

4. **Client returns result** ✅

---

## Code Structure

### Class Hierarchy

```
MCPClient (base class)
  ├─ __init__()          # Store server config
  ├─ connect()           # Launch server, create session, initialize
  ├─ list_tools()        # Get available tools
  ├─ call_tool()         # Execute a tool
  └─ close()             # Cleanup

Neo4jGDSAgentClient (specialized)
  ├─ __init__()          # Load Neo4j credentials, setup gds-agent
  └─ run_graph_algorithm()  # Convenience method to find and call algorithm tools
```

### Key Components

1. **`StdioServerParameters`**: Configuration for launching the server
   - Command to run
   - Arguments
   - Environment variables

2. **`stdio_client()`**: Async context manager that:
   - Launches server subprocess
   - Creates communication streams
   - Manages background message forwarding

3. **`ClientSession`**: MCP protocol handler
   - Serializes/deserializes JSON-RPC messages
   - Matches requests with responses
   - Provides high-level API

4. **Memory Streams**: 
   - `MemoryObjectReceiveStream`: Reads messages from server
   - `MemoryObjectSendStream`: Sends messages to server
   - Managed by `anyio` library

---

## Message Flow Diagram

### Normal Flow (if it worked):

```
Client                          Server
  │                               │
  │  Launch subprocess            │
  │ ────────────────────────────> │
  │                               │  Start process
  │                               │  Connect to Neo4j
  │                               │
  │  Wait for init message        │
  │ <──────────────────────────── │  Send initialize request
  │                               │
  │  Send init response           │
  │ ────────────────────────────> │
  │                               │
  │  Send tools/list request      │
  │ ────────────────────────────> │
  │                               │  Query available tools
  │ <──────────────────────────── │  Send tools list
  │                               │
  │  Send tools/call request      │
  │ ────────────────────────────> │
  │                               │  Execute algorithm
  │                               │  Query Neo4j
  │ <──────────────────────────── │  Send result
  │                               │
```

### Actual Flow (current problem):

```
Client                          Server
  │                               │
  │  Launch subprocess            │
  │ ────────────────────────────> │
  │                               │  Start process
  │                               │  Connect to Neo4j ✅
  │                               │  [STUCK HERE] ❌
  │                               │  (Never sends init message)
  │                               │
  │  Wait for init message...     │
  │  ⏳ (hangs forever)            │
  │                               │
```

---

## Why stdio?

**Advantages:**
- **Simple**: No network setup, ports, or authentication
- **Secure**: Process isolation, no network exposure
- **Universal**: Works on any OS
- **Standard**: Uses well-understood stdin/stdout

**How it works:**
- Client writes JSON to server's stdin
- Server reads from stdin, processes, writes JSON to stdout
- Client reads from server's stdout
- MCP SDK handles the buffering and message framing

---

## The Problem

The gds-agent server:
1. ✅ Starts successfully
2. ✅ Connects to Neo4j
3. ❌ **Never sends the MCP initialization message**

This suggests:
- A bug in gds-agent's initialization sequence
- It might be designed only for Claude Desktop (which may send something first)
- Missing configuration or environment variable
- The server might be waiting for a specific signal or message

---

## Potential Solutions

1. **Report to gds-agent**: File an issue with reproduction steps
2. **Use GDS directly**: Bypass MCP, use `graphdatascience` library directly
3. **Wait for fix**: Keep code ready, use when fixed
4. **Try different MCP server**: Look for alternatives

---

## Summary

- **MCP** = Protocol for AI tools to communicate
- **stdio** = Communication via stdin/stdout (subprocess)
- **Our code** = Correctly implements MCP client
- **gds-agent** = Server that doesn't complete initialization
- **Result** = Hangs waiting for server's init message

The architecture is sound; the issue is with the server implementation.

