"""MCP client: connects to MCP servers and wraps their tools as native miu_bot tools."""

import asyncio
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




MCP_CONNECT_TIMEOUT = 60  # seconds per server


async def connect_mcp_servers(
    mcp_servers: dict, registry: ToolRegistry, stack: AsyncExitStack
) -> int:
    """Connect to configured MCP servers and register their tools.

    Uses per-server AsyncExitStack to isolate failures — a timeout or error
    on one server won't leave zombie context managers on the shared stack.

    Returns the number of successfully connected servers.
    """
    from mcp import ClientSession

    connected = 0

    for name, cfg in mcp_servers.items():
        if not cfg.command and not cfg.url:
            logger.warning(f"MCP '{name}': no command or url, skipping")
            continue

        # Per-server stack isolates connection failures from the shared stack
        server_stack = AsyncExitStack()
        await server_stack.__aenter__()

        try:
            async def _connect(_cfg=cfg, _name=name):
                if _cfg.command:
                    from mcp import StdioServerParameters
                    from mcp.client.stdio import stdio_client
                    params = StdioServerParameters(
                        command=_cfg.command, args=_cfg.args, env=_cfg.env or None
                    )
                    read, write = await server_stack.enter_async_context(
                        stdio_client(params)
                    )
                elif _cfg.url:
                    from mcp.client.streamable_http import streamable_http_client
                    import httpx
                    # Always include MCP-required Accept header; merge with
                    # user-supplied headers (e.g. Authorization)
                    all_headers = {
                        "Accept": "text/event-stream, application/json",
                        **(_cfg.headers or {}),
                    }
                    http_client = await server_stack.enter_async_context(
                        httpx.AsyncClient(headers=all_headers)
                    )
                    read, write, _ = await server_stack.enter_async_context(
                        streamable_http_client(_cfg.url, http_client=http_client)
                    )
                else:
                    return

                session = await server_stack.enter_async_context(
                    ClientSession(read, write)
                )
                await session.initialize()

                tools = await session.list_tools()
                for tool_def in tools.tools:
                    wrapper = MCPToolWrapper(session, _name, tool_def)
                    registry.register(wrapper)

                logger.info(
                    f"MCP '{_name}': connected, {len(tools.tools)} tools registered"
                )

            await asyncio.wait_for(_connect(), timeout=MCP_CONNECT_TIMEOUT)
            # Success — transfer cleanup responsibility to the main stack
            stack.push_async_callback(_safe_aclose, server_stack)
            connected += 1

        except asyncio.TimeoutError:
            logger.error(f"MCP '{name}': timed out after {MCP_CONNECT_TIMEOUT}s")
            await _safe_aclose(server_stack)
        except asyncio.CancelledError:
            logger.error(f"MCP '{name}': cancelled during connect")
            await _safe_aclose(server_stack)
        except Exception as e:
            logger.error(f"MCP '{name}': failed: {e}")
            await _safe_aclose(server_stack)

    return connected


async def _safe_aclose(stack: AsyncExitStack) -> None:
    """Close an AsyncExitStack, suppressing anyio cancel-scope errors."""
    try:
        await stack.aclose()
    except (RuntimeError, asyncio.CancelledError) as e:
        if isinstance(e, asyncio.CancelledError) or "cancel scope" in str(e):
            logger.debug(f"Suppressed cancel-scope error during MCP cleanup: {e}")
        else:
            raise
