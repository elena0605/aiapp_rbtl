"""Test gds-agent when run from cloned source using uv run.

This script tests if gds-agent works when run from the cloned repository
using `uv run gds-agent` instead of `uvx gds-agent`.
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


async def test_gds_agent_from_source():
    """Test gds-agent when run from cloned source."""
    print("=" * 80)
    print("Testing gds-agent from cloned source (uv run gds-agent)")
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
    
    # Find uv command and gds-agent source directory
    import shutil
    uv_path = shutil.which("uv")
    if not uv_path:
        print("\nERROR: uv not found in PATH")
        return False
    
    # Path to cloned gds-agent repository
    gds_agent_dir = Path("/Users/bojansimoski/dev/gds-agent/mcp_server")
    if not gds_agent_dir.exists():
        print(f"\nERROR: gds-agent source directory not found: {gds_agent_dir}")
        print("Please clone the repository: git clone https://github.com/neo4j-contrib/gds-agent.git")
        return False
    
    print(f"\nUsing uv: {uv_path}")
    print(f"gds-agent source: {gds_agent_dir}")
    
    # Set up server parameters
    env = {
        "NEO4J_URI": neo4j_uri,
        "NEO4J_USERNAME": neo4j_username,
        "NEO4J_PASSWORD": neo4j_password,
    }
    if neo4j_database:
        env["NEO4J_DATABASE"] = neo4j_database
    
    # Use uv run gds-agent from the cloned source
    # According to GitHub README: run from /mcp_server directory
    server_params = StdioServerParameters(
        command=uv_path,
        args=["run", "gds-agent"],
        env=env,
        cwd=str(gds_agent_dir),  # Set working directory to mcp_server
    )
    
    print(f"  Working directory: {gds_agent_dir}")
    print(f"  Command: {uv_path} run gds-agent")
    
    print("\n" + "=" * 80)
    print("Step 1: Starting gds-agent server from source...")
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
                print("✓ SUCCESS: gds-agent is working correctly from source!")
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
    success = asyncio.run(test_gds_agent_from_source())
    sys.exit(0 if success else 1)

