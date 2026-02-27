"""Shared helpers for worker workflows (process_message, cron_task).

Eliminates duplication of provider creation, MCP connection, and
response sanitization across workflow processors.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any

from loguru import logger


# --- Error boundary ---

_ERROR_PREFIXES = ("Error calling LLM:", "Error: tool execution failed:")
_FALLBACK_MESSAGE = "Xin lỗi, mình đang gặp sự cố. Vui lòng thử lại sau nhé."


def sanitize_response(content: str | None, finish_reason: str = "stop") -> str:
    """Strip internal errors from LLM response before sending to user.

    Catches raw error strings from litellm_provider and processor,
    replacing them with a user-friendly fallback message.
    """
    if not content:
        return _FALLBACK_MESSAGE
    if finish_reason == "error" or any(content.startswith(p) for p in _ERROR_PREFIXES):
        logger.warning(f"Sanitized error response: {content[:200]}")
        return _FALLBACK_MESSAGE
    return content


# --- Provider creation ---

def create_provider(
    config_overrides: dict[str, Any],
    fallback_model: str,
    fallback_api_key: str,
    fallback_api_base: str | None,
) -> tuple[Any, str]:
    """Create LLMProvider from workspace config_overrides.

    Resolves *_env references from os.environ at runtime.
    Returns (provider, model_string).
    """
    from miu_bot.config.bots import _resolve_env_fields
    from miu_bot.providers.litellm_provider import LiteLLMProvider

    provider_cfg = config_overrides.get("provider", {})
    resolved = _resolve_env_fields(provider_cfg)
    model = resolved.get("model", fallback_model)
    api_key = resolved.get("api_key", fallback_api_key)
    api_base = resolved.get("api_base", fallback_api_base)

    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=model,
    )
    return provider, model


# --- MCP connection ---

async def connect_mcp(
    config_overrides: dict[str, Any],
    tools: Any,
    stack: AsyncExitStack,
) -> int:
    """Connect HTTP MCP servers from workspace config_overrides.

    V1: HTTP/SSE MCP only — stdio MCP deferred.
    Resolves *_env references (headers_env) from worker's env vars.
    Returns the number of successfully connected servers.
    """
    from miu_bot.config.bots import _resolve_env_fields
    from miu_bot.config.schema import MCPServerConfig
    from miu_bot.agent.tools.mcp import connect_mcp_servers

    mcp_raw = config_overrides.get("tools", {}).get("mcp_servers", {})
    if not mcp_raw:
        return 0

    mcp_servers: dict[str, MCPServerConfig] = {}
    for name, cfg_dict in mcp_raw.items():
        resolved = _resolve_env_fields(cfg_dict)
        cfg = MCPServerConfig.model_validate(resolved)
        if cfg.url:
            mcp_servers[name] = cfg
        elif cfg.command:
            logger.info(f"Skipping stdio MCP '{name}' (deferred to V2)")

    if not mcp_servers:
        return 0

    return await connect_mcp_servers(mcp_servers, tools, stack)


async def connect_skill_mcp(
    skill_mcp: dict[str, Any],
    tools: Any,
    stack: AsyncExitStack,
) -> int:
    """Connect skill-provided MCP servers.

    Returns the number of additional servers connected.
    """
    from miu_bot.config.bots import _resolve_env_fields
    from miu_bot.config.schema import MCPServerConfig
    from miu_bot.agent.tools.mcp import connect_mcp_servers

    count = 0
    for name, cfg_dict in skill_mcp.items():
        resolved = _resolve_env_fields(cfg_dict)
        cfg = MCPServerConfig.model_validate(resolved)
        if cfg.url:
            extra = await connect_mcp_servers({name: cfg}, tools, stack)
            count += extra
    return count
