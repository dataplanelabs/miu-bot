"""Stateless message processing loop extracted from AgentLoop."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, TYPE_CHECKING

from loguru import logger

from miu_bot.observability.spans import get_tracer

if TYPE_CHECKING:
    from miu_bot.providers.base import LLMProvider
    from miu_bot.agent.tools.registry import ToolRegistry

MAX_SAME_TOOL_CALLS = 3
_SIDE_EFFECT_PREFIXES = (
    "create_", "update_", "delete_", "send_", "post_",
    "link_", "set_", "remove_", "add_", "unlink_",
)


def _is_side_effect_tool(name: str) -> bool:
    """Check if a tool name suggests side-effect (write) operations.

    Uses prefix matching on the action verb (after stripping MCP namespace).
    E.g. 'mcp_huly_create_issue' → checks 'create_issue'.
    """
    lower = name.lower()
    # Strip common MCP prefixes: mcp_{server}_{action}
    if lower.startswith("mcp_"):
        parts = lower.split("_", 2)
        if len(parts) >= 3:
            lower = parts[2]  # action part after mcp_{server}_
    return any(lower.startswith(p) for p in _SIDE_EFFECT_PREFIXES)


_HEARTBEAT_INTERVAL = 60  # seconds between heartbeats during tool execution


async def _execute_with_heartbeat(
    tools: "ToolRegistry",
    name: str,
    arguments: dict,
    on_heartbeat: Any,
    iteration: int,
) -> str:
    """Execute a tool call with periodic heartbeat pings.

    Sends a heartbeat every 60s while the tool runs, preventing
    Temporal activity heartbeat timeouts on long-running tools.
    """
    if not on_heartbeat:
        return await tools.execute(name, arguments)

    async def _heartbeat_loop() -> None:
        tick = 0
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            tick += 1
            on_heartbeat({
                "phase": "tool_running",
                "iteration": iteration,
                "tool": name,
                "elapsed_s": tick * _HEARTBEAT_INTERVAL,
            })

    hb_task = asyncio.create_task(_heartbeat_loop())
    try:
        return await tools.execute(name, arguments)
    finally:
        hb_task.cancel()
        try:
            await hb_task
        except asyncio.CancelledError:
            pass


async def run_agent_loop(
    provider: "LLMProvider",
    messages: list[dict[str, Any]],
    tools: "ToolRegistry",
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    max_iterations: int = 20,
    on_heartbeat: Any = None,
) -> tuple[str | None, list[str], list[dict[str, Any]]]:
    """Run the iterative LLM + tool execution loop.

    Returns:
        Tuple of (final_content, tools_used_names, trace_events).
    """
    iteration = 0
    final_content = None
    tools_used: list[str] = []
    trace: list[dict[str, Any]] = []
    tracer = get_tracer()
    tool_call_counts: dict[str, int] = {}
    executed_side_effects: dict[str, str] = {}  # call_key → cached result

    while iteration < max_iterations:
        iteration += 1
        t_llm = time.monotonic()

        llm_span = tracer.start_span(f"llm.chat #{iteration}", attributes={"miubot.model": model}) if tracer else None
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
            if llm_span:
                llm_span.set_attribute("error", True)
                llm_span.end()
            trace.append({"event": "llm_timeout", "iteration": iteration})
            return "Sorry, the response took too long. Please try again.", tools_used, trace
        finally:
            if llm_span:
                llm_span.end()

        llm_elapsed = round(time.monotonic() - t_llm, 2)

        # Record LLM call event
        llm_event: dict[str, Any] = {
            "event": "llm_call",
            "iteration": iteration,
            "model": model,
            "latency_s": llm_elapsed,
        }
        if response.usage:
            llm_event["usage"] = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", None),
                "completion_tokens": getattr(response.usage, "completion_tokens", None),
            }
            logger.debug(f"LLM usage: {response.usage}")
        if response.reasoning_content:
            llm_event["reasoning_preview"] = response.reasoning_content[:300]
        trace.append(llm_event)

        if on_heartbeat:
            hb: dict[str, Any] = {
                "phase": "llm_done",
                "iteration": iteration,
                "model": model,
                "latency_s": llm_elapsed,
            }
            if response.reasoning_content:
                hb["reasoning_preview"] = response.reasoning_content[:200]
            if llm_event.get("usage"):
                hb["usage"] = llm_event["usage"]
            on_heartbeat(hb)

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

                # Dedup key for side-effect tools (name + sorted args JSON)
                args_json = json.dumps(tool_call.arguments, sort_keys=True, ensure_ascii=False)
                call_key = f"{tool_call.name}:{args_json}"
                count = tool_call_counts.get(tool_call.name, 0)

                if count >= MAX_SAME_TOOL_CALLS:
                    # Per-tool call cap reached
                    result = (
                        f"Tool '{tool_call.name}' called {count} times already. "
                        f"Limit reached — do not retry."
                    )
                    elapsed = 0.0
                    tool_event = {
                        "event": "tool_call", "iteration": iteration,
                        "tool": tool_call.name, "latency_s": 0, "status": "capped",
                    }
                    logger.warning(f"Tool '{tool_call.name}' capped at {MAX_SAME_TOOL_CALLS} calls")
                elif _is_side_effect_tool(tool_call.name) and call_key in executed_side_effects:
                    # Duplicate side-effect call
                    cached = executed_side_effects[call_key]
                    result = (
                        f"Already executed with same arguments. "
                        f"Previous result: {cached[:500]}"
                    )
                    elapsed = 0.0
                    tool_event = {
                        "event": "tool_call", "iteration": iteration,
                        "tool": tool_call.name, "latency_s": 0, "status": "dedup",
                    }
                    logger.info(f"Dedup hit for '{tool_call.name}'")
                else:
                    # Normal execution with periodic heartbeat for long-running tools
                    t0 = time.monotonic()
                    tool_span = tracer.start_span(
                        f"tool.{tool_call.name}",
                        attributes={"miubot.tool": tool_call.name},
                    ) if tracer else None
                    try:
                        result = await _execute_with_heartbeat(
                            tools, tool_call.name, tool_call.arguments,
                            on_heartbeat, iteration,
                        )
                        elapsed = round(time.monotonic() - t0, 2)
                        _record_tool_latency(tool_call.name, elapsed)
                        if tool_span:
                            tool_span.set_attribute("miubot.tool.latency_s", elapsed)
                        tool_event = {
                            "event": "tool_call",
                            "iteration": iteration,
                            "tool": tool_call.name,
                            "args_preview": json.dumps(tool_call.arguments, ensure_ascii=False)[:200],
                            "result_preview": (result or "")[:200],
                            "latency_s": elapsed,
                            "status": "ok",
                        }
                    except Exception as e:
                        elapsed = round(time.monotonic() - t0, 2)
                        logger.warning(f"Tool '{tool_call.name}' failed: {e}")
                        result = f"Error: tool execution failed: {e}"
                        if tool_span:
                            tool_span.set_attribute("error", True)
                            tool_span.set_attribute("miubot.tool.error", str(e)[:200])
                        tool_event = {
                            "event": "tool_call",
                            "iteration": iteration,
                            "tool": tool_call.name,
                            "latency_s": elapsed,
                            "status": "error",
                            "error": str(e)[:200],
                        }
                    finally:
                        if tool_span:
                            tool_span.end()
                    # Cache side-effect results for dedup
                    if _is_side_effect_tool(tool_call.name):
                        executed_side_effects[call_key] = result or ""

                # Always increment call count (capped/dedup/normal)
                tool_call_counts[tool_call.name] = count + 1
                trace.append(tool_event)
                if on_heartbeat:
                    on_heartbeat({
                        "phase": "tool_done",
                        "iteration": iteration,
                        "tool": tool_call.name,
                        "args_preview": json.dumps(tool_call.arguments, ensure_ascii=False)[:200],
                        "result_preview": (result or "")[:200],
                        "latency_s": elapsed,
                        "status": tool_event.get("status", "ok"),
                    })
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

    return final_content, tools_used, trace


async def run_agent_loop_streaming(
    provider: "LLMProvider",
    messages: list[dict[str, Any]],
    tools: "ToolRegistry",
    model: str,
    on_stream_update: Any = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    max_iterations: int = 20,
    debounce_interval: float = 1.5,
) -> tuple[str | None, list[str]]:
    """Stream-aware agent loop. Calls on_stream_update with partial content."""
    from miu_bot.providers.streaming import StreamBuffer

    iteration = 0
    tools_used: list[str] = []
    buffer = StreamBuffer(debounce_interval=debounce_interval)

    while iteration < max_iterations:
        iteration += 1
        buffer = StreamBuffer(debounce_interval=debounce_interval)

        try:
            stream = provider.chat_stream(
                messages=messages,
                tools=tools.get_definitions(),
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception:
            # Fallback to non-streaming (drop trace for streaming callers)
            content, used, _trace = await run_agent_loop(
                provider, messages, tools, model,
                temperature, max_tokens, max_iterations,
            )
            return content, used

        tool_calls = None

        async for event in stream:
            if event["type"] == "content":
                buffer.append(event["delta"])
                if on_stream_update and buffer.should_flush():
                    await on_stream_update(buffer.flush())

            elif event["type"] == "tool_calls":
                tool_calls = event["tool_calls"]

        if tool_calls:
            # Pause streaming, execute tools, loop again
            messages.append({
                "role": "assistant",
                "content": buffer.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                tools_used.append(tc.name)
                logger.info(f"Tool call (streaming): {tc.name}")
                try:
                    t0 = time.monotonic()
                    result = await tools.execute(tc.name, tc.arguments)
                    _record_tool_latency(tc.name, time.monotonic() - t0)
                except Exception as e:
                    result = f"Error: tool execution failed: {e}"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": result,
                })
            messages.append({
                "role": "user",
                "content": "Reflect on the results and decide next steps.",
            })
            continue
        else:
            # Final content
            final = buffer.finish()
            if on_stream_update:
                await on_stream_update(final)
            return final, tools_used

    return buffer.content if buffer else None, tools_used


def _record_tool_latency(tool_name: str, elapsed: float) -> None:
    """Record OTel metric for tool execution latency."""
    try:
        from miu_bot.observability.metrics import tool_latency

        tool_latency.record(elapsed, {"tool": tool_name})
    except Exception:
        pass
