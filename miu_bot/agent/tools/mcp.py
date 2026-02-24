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

    MCP_TOOL_TIMEOUT = 300  # seconds (was 120; increased for slow MCP servers)

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
            return (
                f"Tool call timed out after {self.MCP_TOOL_TIMEOUT}s but may have "
                f"succeeded on the server. DO NOT retry — the operation may already "
                f"be completed. Inform the user the action was attempted but "
                f"confirmation is pending."
            )
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
MCP_SSE_RETRIES = 2  # extra attempts for flaky SSE connections


def _format_exception_details(e: Exception) -> str:
    """Extract useful details from exceptions, especially ExceptionGroups."""
    if isinstance(e, BaseExceptionGroup):
        sub_msgs = [f"  - {type(sub).__name__}: {sub}" for sub in e.exceptions]
        return f"{e}\n" + "\n".join(sub_msgs)
    return str(e)


async def _try_connect_server(
    name: str, cfg, server_stack: AsyncExitStack, registry: ToolRegistry
) -> None:
    """Connect a single MCP server and register its tools."""
    from mcp import ClientSession

    if cfg.command:
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(
            command=cfg.command, args=cfg.args, env=cfg.env or None
        )
        read, write = await server_stack.enter_async_context(
            stdio_client(params)
        )
    elif cfg.url:
        url = cfg.url
        # SSE transport: sse:// scheme for supergateway-wrapped servers
        if url.startswith("sse://"):
            from mcp.client.sse import sse_client
            http_url = url.replace("sse://", "http://", 1)
            all_headers = {**(cfg.headers or {})}
            read, write = await server_stack.enter_async_context(
                sse_client(http_url, headers=all_headers)
            )
        else:
            # Streamable HTTP (default for native MCP servers)
            from mcp.client.streamable_http import streamable_http_client
            import httpx
            all_headers = {
                "Accept": "text/event-stream, application/json",
                **(cfg.headers or {}),
            }
            http_client = await server_stack.enter_async_context(
                httpx.AsyncClient(headers=all_headers)
            )
            read, write, _ = await server_stack.enter_async_context(
                streamable_http_client(url, http_client=http_client)
            )
    else:
        return

    session = await server_stack.enter_async_context(
        ClientSession(read, write)
    )
    await session.initialize()

    tools = await session.list_tools()
    for tool_def in tools.tools:
        wrapper = MCPToolWrapper(session, name, tool_def)
        registry.register(wrapper)

    logger.info(f"MCP '{name}': connected, {len(tools.tools)} tools registered")


async def connect_mcp_servers(
    mcp_servers: dict, registry: ToolRegistry, stack: AsyncExitStack
) -> int:
    """Connect to configured MCP servers and register their tools.

    Uses per-server AsyncExitStack to isolate failures — a timeout or error
    on one server won't leave zombie context managers on the shared stack.
    SSE connections get retries since supergateway can be flaky.

    Returns the number of successfully connected servers.
    """
    connected = 0

    for name, cfg in mcp_servers.items():
        if not cfg.command and not cfg.url:
            logger.warning(f"MCP '{name}': no command or url, skipping")
            continue

        is_sse = cfg.url and cfg.url.startswith("sse://")
        max_attempts = (1 + MCP_SSE_RETRIES) if is_sse else 1
        last_error = None

        for attempt in range(1, max_attempts + 1):
            # Per-server stack isolates connection failures from the shared stack
            server_stack = AsyncExitStack()
            await server_stack.__aenter__()

            try:
                await asyncio.wait_for(
                    _try_connect_server(name, cfg, server_stack, registry),
                    timeout=MCP_CONNECT_TIMEOUT,
                )
                # Success — transfer cleanup responsibility to the main stack
                stack.push_async_callback(_safe_aclose, server_stack)
                connected += 1
                last_error = None
                break

            except asyncio.TimeoutError:
                logger.error(f"MCP '{name}': timed out after {MCP_CONNECT_TIMEOUT}s (attempt {attempt}/{max_attempts})")
                await _safe_aclose(server_stack)
                last_error = "timeout"
            except asyncio.CancelledError:
                logger.error(f"MCP '{name}': cancelled during connect")
                await _safe_aclose(server_stack)
                raise  # Don't retry on cancellation
            except Exception as e:
                details = _format_exception_details(e)
                logger.error(f"MCP '{name}': failed (attempt {attempt}/{max_attempts}): {details}")
                await _safe_aclose(server_stack)
                last_error = details

            # Brief pause before retry
            if attempt < max_attempts:
                logger.info(f"MCP '{name}': retrying in 2s...")
                await asyncio.sleep(2)

        if last_error:
            logger.warning(f"MCP '{name}': gave up after {max_attempts} attempts")

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
