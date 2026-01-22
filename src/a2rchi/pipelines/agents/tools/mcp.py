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
    active_servers = {}
    failed_servers = {}
    all_tools = []

    for name, server_cfg in mcp_servers.items():
        try:
            client = MultiServerMCPClient({name: server_cfg})
            tools = await client.get_tools()

            active_servers[name] = server_cfg
            all_tools.extend(tools)

        except Exception as e:
            failed_servers[name] = str(e)


    multi_client = MultiServerMCPClient(active_servers)
    print(f"Active MCP Servers: {list(active_servers.keys())}")
    print(f"Failed MCP Servers: {list(failed_servers.keys())}")

    return multi_client, all_tools
