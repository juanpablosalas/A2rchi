from __future__ import annotations

from typing import List, Any
from src.utils.logging import get_logger
from src.utils.config_loader import load_config

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain.tools import BaseTool

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

    all_tools: List[BaseTool] = []
    failed_servers: dict[str, str] = {}

    for name in mcp_servers.keys():
        try:
            async with client.session(name) as session:
                tools = await load_mcp_tools(session)
                all_tools.extend(tools)
        except Exception as e:
            failed_servers[name] = str(e)

    logger.info(f"Active MCP servers: {[n for n in mcp_servers if n not in failed_servers]}")
    logger.warning(f"Failed MCP servers: {list(failed_servers.keys())}")

    return client, all_tools
