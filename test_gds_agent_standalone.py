"""Minimal test to verify gds-agent works standalone.

This script tests if gds-agent can be run and communicates via MCP protocol.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    print("ERROR: MCP SDK not installed. Install with: pip install mcp")
    sys.exit(1)


async def test_gds_agent_standalone():
    """Test gds-agent as a standalone MCP server."""
    print("=" * 80)
    print("Testing gds-agent standalone MCP server")
    print("=" * 80)
    
    # Get Neo4j credentials from environment
    neo4j_uri = os.environ.get("NEO4J_URI")
    neo4j_username = os.environ.get("NEO4J_USERNAME") or os.environ.get("NEO4J_USER")
    neo4j_password = os.environ.get("NEO4J_PASSWORD")
    neo4j_database = os.environ.get("NEO4J_DATABASE")
    
    if not neo4j_uri or not neo4j_username or not neo4j_password:
        print("ERROR: Neo4j credentials not found in environment")
        print("Required: NEO4J_URI, NEO4J_USERNAME (or NEO4J_USER), NEO4J_PASSWORD")
        return False
    
    print(f"\nNeo4j URI: {neo4j_uri}")
    print(f"Neo4j Username: {neo4j_username}")
    print(f"Neo4j Database: {neo4j_database or 'default'}")
    
    # Find uvx command
    import shutil
    uvx_path = shutil.which("uvx")
    if not uvx_path:
        print("\nERROR: uvx not found in PATH")
        print("Install uvx or use python3 -m gds_agent")
        return False
    
    print(f"\nUsing uvx: {uvx_path}")
    
    # Set up server parameters
    env = {
        "NEO4J_URI": neo4j_uri,
        "NEO4J_USERNAME": neo4j_username,
        "NEO4J_PASSWORD": neo4j_password,
    }
    if neo4j_database:
        env["NEO4J_DATABASE"] = neo4j_database
    
    server_params = StdioServerParameters(
        command=uvx_path,
        args=["gds-agent"],
        env=env,
    )
    
    print("\n" + "=" * 80)
    print("Step 1: Starting gds-agent server...")
    print("=" * 80)
    
    try:
        # Use stdio_client as an async context manager
        async with stdio_client(server_params) as (read_stream, write_stream):
            print("✓ Server process started")
            print(f"  Read stream: {type(read_stream)}")
            print(f"  Write stream: {type(write_stream)}")
            
            # Give server time to connect to Neo4j
            print("\nWaiting 3 seconds for server to connect to Neo4j...")
            await asyncio.sleep(3)
            
            print("\n" + "=" * 80)
            print("Step 2: Creating MCP ClientSession...")
            print("=" * 80)
            
            session = ClientSession(read_stream, write_stream)
            print("✓ ClientSession created")
            
            print("\n" + "=" * 80)
            print("Step 3: Initializing MCP session...")
            print("=" * 80)
            print("(This should receive the server's initialization message)")
            
            try:
                # Try to initialize with a timeout
                init_result = await asyncio.wait_for(
                    session.initialize(),
                    timeout=20.0
                )
                print("✓ Session initialized successfully!")
                print(f"  Server name: {init_result.server_info.name if hasattr(init_result, 'server_info') else 'N/A'}")
                print(f"  Server version: {init_result.server_info.version if hasattr(init_result, 'server_info') else 'N/A'}")
                
                print("\n" + "=" * 80)
                print("Step 4: Listing available tools...")
                print("=" * 80)
                
                tools_result = await session.list_tools()
                print(f"✓ Found {len(tools_result.tools)} tools:")
                for tool in tools_result.tools[:5]:  # Show first 5
                    print(f"  - {tool.name}: {tool.description[:60]}...")
                if len(tools_result.tools) > 5:
                    print(f"  ... and {len(tools_result.tools) - 5} more")
                
                print("\n" + "=" * 80)
                print("✓ SUCCESS: gds-agent is working correctly!")
                print("=" * 80)
                return True
                
            except asyncio.TimeoutError:
                print("\n✗ FAILED: Session initialization timed out")
                print("  The server is not sending MCP initialization messages")
                print("  This suggests a problem with gds-agent or the MCP protocol")
                return False
            except Exception as e:
                print(f"\n✗ FAILED: Session initialization error: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                return False
                
    except Exception as e:
        print(f"\n✗ FAILED: Error starting server: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_gds_agent_standalone())
    sys.exit(0 if success else 1)

