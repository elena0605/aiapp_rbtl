"""MCP Client for connecting to MCP servers like Neo4j GDS Agent.

This module provides functionality to connect to MCP servers and use their tools.

KNOWN ISSUE: The gds-agent MCP server currently has a bug where it connects to Neo4j
but doesn't send the MCP initialization message, causing the client to hang.
See MCP_ISSUE.md for details.

Workaround: Use Neo4j GDS library directly instead of via MCP.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None


class MCPClient:
    """MCP Client for connecting to MCP servers."""
    
    def __init__(
        self,
        server_name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ):
        """Initialize MCP client.
        
        Args:
            server_name: Name of the MCP server
            command: Command to run the MCP server (e.g., "uvx" or "python")
            args: Arguments for the command (e.g., ["gds-agent"])
            env: Environment variables to pass to the server
        """
        if ClientSession is None:
            raise RuntimeError(
                "MCP SDK not installed. Install with: pip install mcp"
            )
        
        self.server_name = server_name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.session: Optional[ClientSession] = None
        self._stdio_context = None
        
    async def connect(self) -> None:
        """Connect to the MCP server."""
        print(f"DEBUG: Creating server params with command: {self.command}, args: {self.args}")
        server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env,
        )
        
        print("DEBUG: Creating stdio_client...")
        # stdio_client returns an async context manager
        # We need to enter it and keep it alive
        self._stdio_context = stdio_client(server_params)
        print("DEBUG: Entering stdio context...")
        stdio_transport = await self._stdio_context.__aenter__()
        print(f"DEBUG: Got stdio_transport, type: {type(stdio_transport)}")
        
        # stdio_transport is a tuple of (read_stream, write_stream)
        if isinstance(stdio_transport, tuple) and len(stdio_transport) == 2:
            read_stream, write_stream = stdio_transport
            print(f"DEBUG: Unpacked tuple - read_stream: {type(read_stream)}, write_stream: {type(write_stream)}")
        else:
            # If it's not a tuple, it might be the streams directly
            read_stream, write_stream = stdio_transport, stdio_transport
            print(f"DEBUG: Using transport directly as both streams: {type(stdio_transport)}")
        
        # Give the server a moment to start up and connect to Neo4j
        # The server logs show it connects to Neo4j, but it might need time to initialize
        print("DEBUG: Waiting 2 seconds for server to initialize...")
        await asyncio.sleep(2)
        
        print("DEBUG: Creating ClientSession...")
        self.session = ClientSession(read_stream, write_stream)
        
        # Initialize the session
        # In MCP protocol, the CLIENT sends the initialization request
        # ClientSession.initialize() sends the request and waits for server response
        print("DEBUG: Initializing session (sending client init request, waiting for server response)...")
        try:
            # Add a timeout to see if it's truly hanging
            init_result = await asyncio.wait_for(
                self.session.initialize(),
                timeout=15.0  # Increased timeout to 15 seconds
            )
            print(f"DEBUG: Session initialized successfully: {init_result}")
        except asyncio.TimeoutError:
            print("ERROR: Session initialization timed out after 15 seconds")
            print("This might indicate the MCP server isn't sending its initialization message")
            print("The server may be waiting for something or there's a protocol issue")
            raise
        except Exception as e:
            print(f"ERROR: Session initialization failed: {type(e).__name__}: {e}")
            raise
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools from the MCP server.
        
        Returns:
            List of tool definitions
        """
        if self.session is None:
            print("DEBUG: Session is None, connecting...")
            await self.connect()
        
        print("DEBUG: Calling session.list_tools()...")
        result = await self.session.list_tools()
        print(f"DEBUG: Got result from list_tools, type: {type(result)}")
        print(f"DEBUG: Result has {len(result.tools)} tools")
        return result.tools
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call a tool on the MCP server.
        
        Args:
            tool_name: Name of the tool to call
            arguments: Arguments for the tool
            
        Returns:
            Tool execution result
        """
        if self.session is None:
            await self.connect()
        
        result = await self.session.call_tool(tool_name, arguments or {})
        return result.content
    
    async def close(self) -> None:
        """Close the connection to the MCP server."""
        # ClientSession doesn't have a close() method - it's managed by the stdio context
        # Just clear the reference
        self.session = None
        
        # Exit the stdio context manager
        if self._stdio_context:
            try:
                await self._stdio_context.__aexit__(None, None, None)
            except Exception as e:
                print(f"DEBUG: Error closing stdio context: {e}")
            self._stdio_context = None


class Neo4jGDSAgentClient(MCPClient):
    """Client for Neo4j GDS Agent MCP server.
    
    This is a convenience wrapper for connecting to the Neo4j GDS Agent.
    See: https://github.com/neo4j-contrib/gds-agent
    """
    
    def __init__(
        self,
        neo4j_uri: Optional[str] = None,
        neo4j_username: Optional[str] = None,
        neo4j_password: Optional[str] = None,
        neo4j_database: Optional[str] = None,
        command: Optional[str] = None,
        gds_agent_args: Optional[List[str]] = None,
    ):
        """Initialize Neo4j GDS Agent client.
        
        Args:
            neo4j_uri: Neo4j URI (defaults to NEO4J_URI env var)
            neo4j_username: Neo4j username (defaults to NEO4J_USERNAME or NEO4J_USER env var)
            neo4j_password: Neo4j password (defaults to NEO4J_PASSWORD env var)
            neo4j_database: Neo4j database name (optional)
            command: Command to run gds-agent (default: "uvx")
            gds_agent_args: Additional arguments for gds-agent
        """
        # Load .env file from project root
        if load_dotenv is not None:
            project_root = Path(__file__).resolve().parents[1]
            load_dotenv(dotenv_path=str(project_root / ".env"))
        
        # Get Neo4j credentials from env if not provided
        # Support both NEO4J_USERNAME and NEO4J_USER for compatibility
        neo4j_uri = neo4j_uri or os.environ.get("NEO4J_URI")
        neo4j_username = neo4j_username or os.environ.get("NEO4J_USERNAME") or os.environ.get("NEO4J_USER")
        neo4j_password = neo4j_password or os.environ.get("NEO4J_PASSWORD")
        neo4j_database = neo4j_database or os.environ.get("NEO4J_DATABASE")
        
        if not neo4j_uri or not neo4j_username or not neo4j_password:
            raise ValueError(
                "Neo4j credentials required. Set NEO4J_URI, NEO4J_USERNAME (or NEO4J_USER), "
                "and NEO4J_PASSWORD in your .env file or pass them as arguments."
            )
        
        # Build environment variables
        env = {
            "NEO4J_URI": neo4j_uri,
            "NEO4J_USERNAME": neo4j_username,
            "NEO4J_PASSWORD": neo4j_password,
        }
        if neo4j_database:
            env["NEO4J_DATABASE"] = neo4j_database
        
        # Determine command to use
        # Try to find uvx, or use python -m gds_agent as fallback
        if command is None:
            import shutil
            uvx_path = shutil.which("uvx")
            if uvx_path:
                command = uvx_path
                args = gds_agent_args or ["gds-agent"]
            else:
                # Fallback to python -m if uvx not found
                command = "python3"
                args = gds_agent_args or ["-m", "gds_agent"]
        else:
            args = gds_agent_args or ["gds-agent"]
        
        super().__init__(
            server_name="neo4j-gds",
            command=command,
            args=args,
            env=env,
        )
    
    async def run_graph_algorithm(
        self,
        algorithm_name: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Run a graph algorithm using the GDS Agent.
        
        Args:
            algorithm_name: Name of the algorithm (e.g., "shortest_path", "pagerank")
            **kwargs: Algorithm-specific parameters
            
        Returns:
            Algorithm execution result
        """
        # The tool name format may vary, but typically it's the algorithm name
        # You may need to list tools first to see the exact tool names
        tools = await self.list_tools()
        
        # Find the matching tool
        tool_name = None
        for tool in tools:
            if algorithm_name.lower() in tool.name.lower():
                tool_name = tool.name
                break
        
        if tool_name is None:
            available = [t.name for t in tools]
            raise ValueError(
                f"Algorithm '{algorithm_name}' not found. Available tools: {available}"
            )
        
        return await self.call_tool(tool_name, kwargs)


async def example_usage():
    """Example usage of the MCP client."""
    # Create client
    client = Neo4jGDSAgentClient()
    
    try:
        # Connect
        await client.connect()
        
        # List available tools
        tools = await client.list_tools()
        print("Available tools:")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description}")
        
        # Example: Run a graph algorithm
        # result = await client.run_graph_algorithm("shortest_path", ...)
        # print(result)
        
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(example_usage())

