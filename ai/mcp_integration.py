"""Integration example: Using MCP client with GraphRAG.

This module shows how to use the Neo4j GDS Agent MCP client alongside
the GraphRAG text-to-cypher functionality.

NOTE: This module is currently non-functional due to issues with the MCP SDK
implementation in `mcp_client.py`. 

WORKING ALTERNATIVE: See `example_mcp_client.py` for a working MCP client
implementation. This integration module could be updated to use that approach
instead of `mcp_client.py`.

This is kept as a reference for future integration.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from ai.mcp_client import Neo4jGDSAgentClient


async def query_with_gds_agent(
    question: str,
    use_graph_algorithms: bool = False,
) -> Dict[str, Any]:
    """Query Neo4j using both GraphRAG and GDS Agent.
    
    Args:
        question: Natural language question
        use_graph_algorithms: Whether to use GDS algorithms for complex queries
        
    Returns:
        Query results
    """
    # For simple queries, use the existing text_to_cypher functionality
    # For complex graph analysis, use GDS Agent
    
    if use_graph_algorithms:
        # Use GDS Agent for graph algorithms
        client = Neo4jGDSAgentClient()
        
        try:
            await client.connect()
            
            # List available tools
            tools = await client.list_tools()
            print(f"Available GDS tools: {[t.name for t in tools]}")
            
            # Example: If question asks for shortest path, use appropriate algorithm
            if "shortest path" in question.lower() or "path" in question.lower():
                # This is a simplified example - you'd need to parse the question
                # and extract parameters
                result = await client.call_tool(
                    "shortest_path",  # Tool name may vary
                    {
                        # Extract parameters from question
                        # This is simplified - real implementation would parse the question
                    }
                )
                return {"type": "gds_algorithm", "result": result}
            
        finally:
            await client.close()
    
    # For regular queries, use existing text_to_cypher
    # This would call your existing ai/text_to_cypher.py functionality
    return {"type": "cypher_query", "message": "Use text_to_cypher for regular queries"}


if __name__ == "__main__":
    # Example usage
    result = asyncio.run(query_with_gds_agent("Find shortest path between two nodes"))
    print(result)

