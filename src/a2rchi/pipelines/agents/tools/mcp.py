import asyncio
from typing import Callable
from langchain.tools import tool
from mcp import ClientSession
from mcp.client.sse import sse_client

def create_mcp_ping_tool(
    server_url: str = "http://submit76.mit.edu:7760/sse",
    *,
    name: str = "mcp_ping",
    description: str = "Ping the external MCP server to verify connectivity and status.",
) -> Callable:
    """
    Create a LangChain tool that pings a Model Context Protocol (MCP) server.

    Args:
        server_url: The URL of the MCP server's SSE endpoint.
        name: The name of the tool provided to the LLM.
        description: The tool description provided to the LLM.
    """

    async def _run_ping_logic() -> str:
        """Internal async logic to connect and ping."""
        try:
            # Connect to the MCP server via SSE
            async with sse_client(server_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    # Call the ping tool as requested
                    result = await session.call_tool("ping", {})

                    # Return the result as a string for the agent
                    return str(result)
        except Exception as e:
            return f"Failed to ping MCP server at {server_url}. Error: {e}"

    @tool(name, description=description)
    def _mcp_ping(query: str = "") -> str:
        """
        Connects to the MCP server and executes the 'ping' tool.
        The 'query' argument is ignored but kept for tool compatibility.
        """
        try:
            # Run the async logic in a new event loop
            return asyncio.run(_run_ping_logic())
        except RuntimeError as e:
            # Handle cases where an event loop is already running (e.g., Jupyter, some web apps)
            if "event loop is already running" in str(e):
                try:
                    import nest_asyncio
                    nest_asyncio.apply()
                    return asyncio.run(_run_ping_logic())
                except ImportError:
                    return (
                        f"Error: An event loop is already running, and 'nest_asyncio' is not installed. "
                        f"Could not execute async MCP tool synchronously. Detail: {e}"
                    )
            return f"Runtime error executing MCP tool: {e}"

    return _mcp_ping
