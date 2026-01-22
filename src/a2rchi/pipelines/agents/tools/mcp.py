from __future__ import annotations

from typing import List, Any
from src.utils.logging import get_logger
from src.utils.config_loader import load_config


from langchain_mcp_adapters.client import MultiServerMCPClient

logger = get_logger(__name__)

async def initialize_mcp_client() -> Tuple[MultiServerMCPClient, List[BaseTool]]:
    """
    Initializes the MCP client and fetches tool definitions.
    Returns:
        client: The active client instance (must be kept alive by the caller).
        tools: The list of LangChain-compatible tools.
    """

    config = load_config()
    mcp_servers = config["a2rchi"]["mcp_servers"] or {}
    client = MultiServerMCPClient(mcp_servers)

    tools = await client.get_tools()

    return client, tools
