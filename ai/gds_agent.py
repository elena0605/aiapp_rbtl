"""Example: Using MCP client to connect to Neo4j GDS Agent.

This example shows how to use the MCP client to connect to the Neo4j GDS Agent
and use graph data science algorithms.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.mcp_client import Neo4jGDSAgentClient


async def main():
    """Example usage of Neo4j GDS Agent MCP client."""
    print("Connecting to Neo4j GDS Agent MCP server...")
    
    # Create client (uses Neo4j credentials from .env)
    print("Creating Neo4jGDSAgentClient...")
    client = Neo4jGDSAgentClient()
    print("✓ Client created")
    
    try:
        # Connect to the MCP server
        print("Calling client.connect()...")
        await client.connect()
        print("✓ Connected to GDS Agent")
        
        # List available tools
        print("\nRequesting available tools...")
        print("Calling client.list_tools()...")
        tools = await client.list_tools()
        print(f"✓ Received {len(tools)} tools")
        
        print("\nAvailable tools:")
        for tool in tools:
            print(f"  - {tool.name}")
            if tool.description:
                print(f"    {tool.description}")
        
        # Example: Call a tool (uncomment and adjust based on available tools)
        # print("\nCalling tool...")
        # result = await client.call_tool(
        #     "tool_name",
        #     {"param1": "value1", "param2": "value2"}
        # )
        # print(f"Result: {result}")
        
    except Exception as e:
        error_msg = str(e)
        print(f"Error: {error_msg}")
        
        # Check for specific GDS-related errors
        if "Graph Data Science library" in error_msg or "gds.version" in error_msg or "GdsNotFound" in error_msg:
            print("\n⚠️  Neo4j Graph Data Science (GDS) library is not installed on your Neo4j database.")
            print("\nTo use the GDS Agent, you need to install the GDS plugin on your Neo4j instance:")
            print("1. For Neo4j Desktop: Install GDS plugin from the Graph Apps section")
            print("2. For Neo4j Aura: GDS is available on AuraDS (not regular Aura)")
            print("3. For self-hosted: Download and install GDS plugin from:")
            print("   https://neo4j.com/docs/graph-data-science/current/installation/")
            print("\nIf you only need regular Cypher queries (not graph algorithms),")
            print("you can use the regular text_to_cypher.py instead of the GDS Agent.")
        else:
            print("\nMake sure:")
            print("1. GDS Agent is installed: pip install gds-agent")
            print("2. Neo4j credentials are set in .env file")
            print("3. Neo4j database is running and accessible")
            print("4. Neo4j Graph Data Science (GDS) plugin is installed on the database")
        
    finally:
        await client.close()
        print("\n✓ Disconnected from GDS Agent")


if __name__ == "__main__":
    asyncio.run(main())

