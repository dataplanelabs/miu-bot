"""Stateless message processing loop extracted from AgentLoop."""

from __future__ import annotations

import asyncio
import json
from typing import Any, TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from miu_bot.providers.base import LLMProvider
    from miu_bot.agent.tools.registry import ToolRegistry


async def run_agent_loop(
    provider: "LLMProvider",
    messages: list[dict[str, Any]],
    tools: "ToolRegistry",
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    max_iterations: int = 20,
) -> tuple[str | None, list[str]]:
    """Run the iterative LLM + tool execution loop.

    Returns:
        Tuple of (final_content, tools_used_names).
    """
    iteration = 0
    final_content = None
    tools_used: list[str] = []

    while iteration < max_iterations:
        iteration += 1
        try:
            response = await asyncio.wait_for(
                provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ),
                timeout=180,
            )
        except asyncio.TimeoutError:
            logger.warning("LLM call timed out after 180s")
            return "Sorry, the response took too long. Please try again.", tools_used

        if response.usage:
            logger.debug(f"LLM usage: {response.usage}")

        if response.has_tool_calls:
            tool_call_dicts = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in response.tool_calls
            ]
            messages.append({
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": tool_call_dicts,
            })

            for tool_call in response.tool_calls:
                tools_used.append(tool_call.name)
                logger.info(f"Tool call: {tool_call.name}")
                try:
                    result = await tools.execute(tool_call.name, tool_call.arguments)
                except Exception as e:
                    logger.warning(f"Tool '{tool_call.name}' failed: {e}")
                    result = f"Error: tool execution failed: {e}"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "content": result,
                })

            messages.append({"role": "user", "content": "Reflect on the results and decide next steps."})
        else:
            final_content = response.content
            break

    return final_content, tools_used
