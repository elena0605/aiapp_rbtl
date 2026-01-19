"""
Example MCP client for connecting to the GDS Agent server.

This demonstrates how to connect to the MCP server as a client.
The server uses stdio transport, so the client must start it as a subprocess.
"""

import asyncio
import json
import os
import sys
from pathlib import Path


class MCPClient:
    """Simple MCP client for communicating with the GDS Agent server via stdio."""

    def __init__(self, process):
        self.process = process
        self.request_id = 0
        self._stderr_task = None
    
    async def close(self):
        """Close the connection and stop the server."""
        if self._stderr_task:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
        if self.process and self.process.returncode is None:
            self.process.terminate()
            await self.process.wait()

    async def send_request(self, method, params=None):
        """Send a JSON-RPC request to the MCP server."""
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params or {},
        }

        # Send request
        request_str = json.dumps(request) + "\n"
        self.process.stdin.write(request_str.encode())
        await self.process.stdin.drain()

        # Read response - use readline with increased limit
        # The subprocess limit is set to 10MB, so readline should handle large responses
        try:
            response_line = await asyncio.wait_for(
                self.process.stdout.readline(),
                timeout=60.0  # Longer timeout for graph operations
            )
        except asyncio.TimeoutError:
            raise RuntimeError("Timeout waiting for response from MCP server")

        if not response_line:
            raise RuntimeError("No response from MCP server")

        # Decode and parse response
        try:
            response_text = response_line.decode().strip()
            response = json.loads(response_text)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise RuntimeError(f"Failed to parse response: {e}")

        return response

    async def initialize(self):
        """Initialize the MCP connection."""
        response = await self.send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "example-client", "version": "1.0.0"},
            },
        )

        # Send initialized notification
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        notification_str = json.dumps(notification) + "\n"
        self.process.stdin.write(notification_str.encode())
        await self.process.stdin.drain()

        return response

    async def list_tools(self):
        """List available tools."""
        response = await self.send_request("tools/list")
        return response.get("result", {}).get("tools", [])

    async def call_tool(self, name, arguments=None):
        """Call a tool by name with arguments."""
        response = await self.send_request(
            "tools/call", {"name": name, "arguments": arguments or {}}
        )
        return response.get("result", {}).get("content", [])


async def create_client(
    neo4j_uri: str = None,
    neo4j_user: str = None,
    neo4j_password: str = None,
) -> MCPClient:
    """Create and initialize an MCP client connected to GDS Agent.
    
    Args:
        neo4j_uri: Neo4j URI (defaults to NEO4J_URI env var)
        neo4j_user: Neo4j username (defaults to NEO4J_USER or NEO4J_USERNAME env var)
        neo4j_password: Neo4j password (defaults to NEO4J_PASSWORD env var)
    
    Returns:
        Initialized MCPClient instance
        
    Example:
        ```python
        client = await create_client()
        tools = await client.list_tools()
        result = await client.call_tool("get_node_labels", {})
        await client.close()  # Don't forget to close!
        ```
    """
    from dotenv import load_dotenv
    
    project_root = Path(__file__).parent.parent
    load_dotenv(project_root / ".env")
    
    # Get environment for environment-specific credentials
    environment = os.environ.get("ENVIRONMENT", "production").lower()
    
    # Get credentials from args or environment (with environment switching support)
    if not neo4j_uri:
        if environment == "development":
            neo4j_uri = os.environ.get("NEO4J_URI_DEV") or os.environ.get("NEO4J_URI")
        else:
            neo4j_uri = os.environ.get("NEO4J_URI")
    
    if not neo4j_user:
        if environment == "development":
            neo4j_user = os.environ.get("NEO4J_USER_DEV") or os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "neo4j")
        else:
            neo4j_user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "neo4j")
    
    if not neo4j_password:
        if environment == "development":
            neo4j_password = os.environ.get("NEO4J_PASSWORD_DEV") or os.environ.get("NEO4J_PASSWORD")
        else:
            neo4j_password = os.environ.get("NEO4J_PASSWORD")
    
    if not neo4j_uri or not neo4j_password:
        raise ValueError(
            f"NEO4J_URI and NEO4J_PASSWORD must be set in .env file or passed as arguments "
            f"(environment={environment})"
        )
    
    # Find gds-agent executable
    venv_bin = project_root / "venv" / "bin"
    gds_agent = venv_bin / "gds-agent"
    
    if not gds_agent.exists():
        raise FileNotFoundError(
            f"gds-agent not found at {gds_agent}. "
            "Please install the package in venv."
        )
    
    # Start the MCP server as a subprocess
    proc = await asyncio.create_subprocess_exec(
        str(gds_agent),
        "--db-url", neo4j_uri,
        "--username", neo4j_user,
        "--password", neo4j_password,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=1024 * 1024 * 10,  # 10MB buffer limit
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    
    # Read stderr in background
    async def read_stderr():
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
    
    stderr_task = asyncio.create_task(read_stderr())
    
    # Wait for server to initialize
    await asyncio.sleep(2)
    
    # Check if process died
    if proc.returncode is not None:
        stderr_output = await proc.stderr.read()
        raise RuntimeError(f"Server process died: {stderr_output.decode()}")
    
    # Create client
    client = MCPClient(proc)
    client._stderr_task = stderr_task
    
    # Initialize connection
    await client.initialize()
    
    return client


async def main():
    """Main function demonstrating client usage."""
    print("Starting MCP server and connecting...")
    
    try:
        client = await create_client()
        print("✓ Connected to MCP server\n")
    except Exception as e:
        print(f"✗ Failed to connect: {e}")
        sys.exit(1)

    try:
        # List available tools
        print("Fetching available tools...")
        tools = await client.list_tools()
        print(f"✓ Found {len(tools)} tools\n")
    except Exception as e:
        print(f"✗ Failed to list tools: {e}")
        await client.close()
        return

    # Example: Get node labels (fast - uses direct Cypher query)
    print("Example: Getting node labels from the graph...")
    try:
        result = await client.call_tool("get_node_labels", {})
        if result:
            result_text = result[0].get('text', 'No result')
            print(f"Result: {result_text}\n")
    except Exception as e:
        print(f"✗ Tool call failed: {e}\n")
    
    # Example: Count nodes (may timeout on large databases - uses graph projection)
    print("Example: Counting nodes in the graph...")
    print("(This may take a moment or timeout if the database is very large)")
    try:
        result = await client.call_tool("count_nodes", {})
        if result:
            # Truncate long results for display
            result_text = result[0].get('text', 'No result')
            if len(result_text) > 200:
                print(f"Result: {result_text[:200]}... (truncated)\n")
            else:
                print(f"Result: {result_text}\n")
    except Exception as e:
        print(f"Note: Tool call timed out or failed: {e}")
        print("This is normal if the database query takes longer than 60 seconds.")
        print("The server connection is working - you can see it listed tools above.\n")

    # Example: List a few tool names
    print("Available tools (first 10):")
    for tool in tools[:10]:
        print(f"  - {tool.get('name')}")
    
    print(f"\nTotal tools available: {len(tools)}")
    print("\n✓ Client connection test successful!")
    print("  The server is running and responding to requests.")
    print("  Tool calls may take time depending on your database size.")

    # Cleanup
    print("\nClosing connection...")
    await client.close()
    print("✓ Done")


async def interactive_mode():
    """Interactive mode for testing tools continuously."""
    print("=" * 60)
    print("MCP Client - Interactive Mode")
    print("=" * 60)
    print("\nStarting server and connecting...")
    
    client = await create_client()
    print("✓ Connected to MCP server\n")
    
    try:
        # List tools once
        tools = await client.list_tools()
        print(f"Available tools: {len(tools)}")
        print("\nFirst 10 tools:")
        for tool in tools[:10]:
            print(f"  - {tool.get('name')}")
        print(f"\n... and {len(tools) - 10} more\n")
        
        # Interactive loop
        print("=" * 60)
        print("Interactive Tool Testing")
        print("=" * 60)
        print("Commands:")
        print("  list                    - List all available tools")
        print("  call <name> [args]      - Call a tool (args as JSON)")
        print("  help <name>             - Show tool details")
        print("  quit                    - Exit")
        print()
        
        while True:
            try:
                command = input("mcp> ").strip()
                
                if not command:
                    continue
                
                if command == "quit" or command == "exit":
                    break
                
                elif command == "list":
                    print(f"\nAvailable tools ({len(tools)}):")
                    for i, tool in enumerate(tools, 1):
                        name = tool.get('name', 'unknown')
                        desc = tool.get('description', 'No description')
                        print(f"  {i:2d}. {name}")
                        if desc:
                            print(f"      {desc[:80]}")
                    print()
                
                elif command.startswith("call "):
                    parts = command[5:].strip().split(None, 1)
                    tool_name = parts[0]
                    args_str = parts[1] if len(parts) > 1 else "{}"
                    
                    try:
                        args = json.loads(args_str)
                        print(f"\nCalling {tool_name} with args: {args}")
                        result = await client.call_tool(tool_name, args)
                        print(f"Result: {json.dumps(result, indent=2)}\n")
                    except json.JSONDecodeError as e:
                        print(f"Error: Invalid JSON in arguments: {e}\n")
                    except Exception as e:
                        print(f"Error: {e}\n")
                
                elif command.startswith("help "):
                    tool_name = command[5:].strip()
                    tool = next((t for t in tools if t.get('name') == tool_name), None)
                    if tool:
                        print(f"\nTool: {tool.get('name')}")
                        print(f"Description: {tool.get('description', 'No description')}")
                        if 'inputSchema' in tool:
                            print(f"Schema: {json.dumps(tool['inputSchema'], indent=2)}")
                        print()
                    else:
                        print(f"Tool '{tool_name}' not found\n")
                
                else:
                    print(f"Unknown command: {command}")
                    print("Type 'quit' to exit\n")
            
            except KeyboardInterrupt:
                print("\n\nExiting...")
                break
            except EOFError:
                break
    
    finally:
        print("\nClosing connection...")
        await client.close()
        print("✓ Done")


if __name__ == "__main__":
    import sys
    
    # Check for interactive mode flag
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        asyncio.run(interactive_mode())
    else:
        asyncio.run(main())

