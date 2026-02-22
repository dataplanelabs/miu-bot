"""MCP client: connects to MCP servers and wraps their tools as native miu_bot tools."""

from contextlib import AsyncExitStack
from typing import Any

from loguru import logger

from miu_bot.agent.tools.base import Tool
from miu_bot.agent.tools.registry import ToolRegistry


class MCPToolWrapper(Tool):
    """Wraps a single MCP server tool as a miu_bot Tool."""

    def __init__(self, session, server_name: str, tool_def):
        self._session = session
        self._original_name = tool_def.name
        self._name = f"mcp_{server_name}_{tool_def.name}"
        self._description = tool_def.description or tool_def.name
        self._parameters = tool_def.inputSchema or {"type": "object", "properties": {}}

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    MCP_TOOL_TIMEOUT = 120  # seconds

    async def execute(self, **kwargs: Any) -> str:
        import asyncio
        from mcp import types

        # Filter to only params defined in schema (prevents additionalProperties errors)
        allowed = set(self._parameters.get("properties", {}).keys())
        if allowed:
            kwargs = {k: v for k, v in kwargs.items() if k in allowed}

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(self._original_name, arguments=kwargs),
                timeout=self.MCP_TOOL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(f"MCP tool '{self._original_name}' timed out after {self.MCP_TOOL_TIMEOUT}s")
            return f"Error: MCP tool call timed out after {self.MCP_TOOL_TIMEOUT}s"
        except asyncio.CancelledError:
            return "Error: MCP tool call cancelled (server shutting down)"
        except Exception as e:
            return f"Error: MCP tool call failed: {e}"
        parts = []
        for block in result.content:
            if isinstance(block, types.TextContent):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts) or "(no output)"


    MCP_CONNECT_TIMEOUT = 30  # seconds per server


async def connect_mcp_servers(
    mcp_servers: dict, registry: ToolRegistry, stack: AsyncExitStack
) -> None:
    """Connect to configured MCP servers and register their tools."""
    import asyncio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    for name, cfg in mcp_servers.items():
        try:
            async def _connect():
                if cfg.command:
                    params = StdioServerParameters(
                        command=cfg.command, args=cfg.args, env=cfg.env or None
                    )
                    read, write = await stack.enter_async_context(stdio_client(params))
                elif cfg.url:
                    from mcp.client.streamable_http import streamable_http_client
                    http_client = None
                    if cfg.headers:
                        import httpx
                        http_client = await stack.enter_async_context(
                            httpx.AsyncClient(headers=cfg.headers)
                        )
                    read, write, _ = await stack.enter_async_context(
                        streamable_http_client(cfg.url, http_client=http_client)
                    )
                else:
                    return

                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()

                tools = await session.list_tools()
                for tool_def in tools.tools:
                    wrapper = MCPToolWrapper(session, name, tool_def)
                    registry.register(wrapper)
                    logger.debug(f"MCP: registered tool '{wrapper.name}' from server '{name}'")

                logger.info(f"MCP server '{name}': connected, {len(tools.tools)} tools registered")

            if not cfg.command and not cfg.url:
                logger.warning(f"MCP server '{name}': no command or url configured, skipping")
                continue

            await asyncio.wait_for(_connect(), timeout=MCP_CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error(f"MCP server '{name}': connection timed out after {MCP_CONNECT_TIMEOUT}s")
        except Exception as e:
            logger.error(f"MCP server '{name}': failed to connect: {e}")
