# MCP Server Not Responding to Initialization Request (Programmatic Usage)

## Problem

When using `gds-agent` as an MCP server programmatically (not via Claude Desktop), the server successfully connects to Neo4j but does not respond to MCP protocol initialization requests, causing the client to hang indefinitely.

## Environment

- **Python**: 3.13
- **MCP SDK**: 1.21.0 (also tested with 1.8.0 - same issue)
- **graphdatascience**: 1.17 (also tested with 1.14 - same issue)
- **gds-agent**: 0.5.1 (installed via `uvx gds-agent`)
- **Neo4j**: Connected successfully (bolt+ssc://rbl-neo4j.ecda.ai:7687)
- **OS**: macOS

## Steps to Reproduce

1. Install dependencies:
   ```bash
   pip install mcp[cli]>=1.11.0 graphdatascience>=1.16
   ```

2. Set environment variables:
   ```bash
   export NEO4J_URI="bolt://your-neo4j:7687"
   export NEO4J_USERNAME="neo4j"
   export NEO4J_PASSWORD="your-password"
   ```

3. Run the test script (see below)

4. Observe: Server connects to Neo4j but never responds to MCP initialization

## Expected Behavior

The MCP server should:
1. Start and connect to Neo4j ✅ (works)
2. Respond to the client's `initialize()` request ✅ (fails)
3. Complete the MCP protocol handshake ✅ (fails)

## Actual Behavior

1. Server starts successfully ✅
2. Server connects to Neo4j ✅ (logs show: "Successfully connected to Neo4j database")
3. Server **never responds** to MCP initialization request ❌
4. Client hangs at `ClientSession.initialize()` until timeout ❌

## Debug Output

```
2025-11-13 15:21:43,181 - mcp_server_neo4j_gds - INFO - Starting MCP Server for bolt+ssc://rbl-neo4j.ecda.ai:7687 with username neo4j
2025-11-13 15:21:48,059 - mcp_server_neo4j_gds - INFO - Successfully connected to Neo4j database
Connecting to Neo4j GDS Agent MCP server...
Creating Neo4jGDSAgentClient...
✓ Client created
Calling client.connect()...
DEBUG: Creating server params with command: /path/to/uvx, args: ['gds-agent']
DEBUG: Creating stdio_client...
DEBUG: Entering stdio context...
DEBUG: Got stdio_transport, type: <class 'tuple'>
DEBUG: Unpacked tuple - read_stream: <class 'anyio.streams.memory.MemoryObjectReceiveStream'>, write_stream: <class 'anyio.streams.memory.MemoryObjectSendStream'>
DEBUG: Waiting 2 seconds for server to initialize...
DEBUG: Creating ClientSession...
DEBUG: Initializing session (sending client init request, waiting for server response)...
ERROR: Session initialization timed out after 15 seconds
This might indicate the MCP server isn't sending its initialization message
The server may be waiting for something or there's a protocol issue
```

## Test Script

Here's a minimal reproduction script:

```python
"""Minimal test to verify gds-agent works standalone."""

import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import shutil

async def test_gds_agent():
    """Test gds-agent as a standalone MCP server."""
    # Get Neo4j credentials
    neo4j_uri = os.environ.get("NEO4J_URI")
    neo4j_username = os.environ.get("NEO4J_USERNAME") or os.environ.get("NEO4J_USER")
    neo4j_password = os.environ.get("NEO4J_PASSWORD")
    
    if not neo4j_uri or not neo4j_username or not neo4j_password:
        print("ERROR: Neo4j credentials not found")
        return False
    
    # Find uvx
    uvx_path = shutil.which("uvx")
    if not uvx_path:
        print("ERROR: uvx not found")
        return False
    
    # Set up server parameters
    env = {
        "NEO4J_URI": neo4j_uri,
        "NEO4J_USERNAME": neo4j_username,
        "NEO4J_PASSWORD": neo4j_password,
    }
    
    server_params = StdioServerParameters(
        command=uvx_path,
        args=["gds-agent"],
        env=env,
    )
    
    print("Starting gds-agent server...")
    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            print("✓ Server process started")
            
            # Wait for server to connect to Neo4j
            await asyncio.sleep(3)
            
            print("Creating MCP ClientSession...")
            session = ClientSession(read_stream, write_stream)
            
            print("Initializing MCP session...")
            try:
                # This hangs - server never responds
                init_result = await asyncio.wait_for(
                    session.initialize(),
                    timeout=20.0
                )
                print("✓ Session initialized successfully!")
                return True
            except asyncio.TimeoutError:
                print("✗ FAILED: Session initialization timed out")
                print("  The server is not sending MCP initialization messages")
                return False
    except Exception as e:
        print(f"✗ FAILED: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_gds_agent())
    exit(0 if success else 1)
```

## Additional Information

- The server process starts correctly
- Neo4j connection is successful (verified via logs)
- Communication streams are set up correctly (read_stream/write_stream)
- The MCP client code follows the standard MCP protocol
- This works fine when gds-agent is used via Claude Desktop

## Questions

1. Is programmatic usage (not via Claude Desktop) officially supported?
2. Are there any special requirements or environment variables needed?
3. Does the server expect a specific initialization sequence?
4. Is there a known issue with MCP SDK 1.21.0 compatibility?

## Related

- MCP SDK: https://github.com/modelcontextprotocol/python-sdk
- Our implementation follows the standard MCP client pattern

---

**Note**: This issue prevents using gds-agent programmatically in Python applications. The server appears to be designed primarily for Claude Desktop integration, but the documentation suggests it should work standalone.

