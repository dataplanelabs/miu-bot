"""LiteLLM provider implementation for multi-provider support."""

import json
import json_repair
import os
import time
from typing import Any

import httpx
import litellm
from litellm import acompletion
from loguru import logger
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    retry_if_exception_type,
)

from miu_bot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from miu_bot.providers.registry import find_by_model, find_gateway


class LiteLLMProvider(LLMProvider):
    """
    LLM provider using LiteLLM for multi-provider support.
    
    Supports OpenRouter, Anthropic, OpenAI, Gemini, MiniMax, and many other providers through
    a unified interface.  Provider-specific logic is driven by the registry
    (see providers/registry.py) — no if-elif chains needed here.
    """
    
    def __init__(
        self, 
        api_key: str | None = None, 
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        extra_headers: dict[str, str] | None = None,
        provider_name: str | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}
        
        # Detect gateway / local deployment.
        # provider_name (from config key) is the primary signal;
        # api_key / api_base are fallback for auto-detection.
        self._gateway = find_gateway(provider_name, api_key, api_base)
        
        # Configure environment variables
        if api_key:
            self._setup_env(api_key, api_base, default_model)
        
        if api_base:
            litellm.api_base = api_base
        
        # Disable LiteLLM logging noise
        litellm.suppress_debug_info = True
        # Drop unsupported parameters for providers (e.g., gpt-5 rejects some params)
        litellm.drop_params = True
    
    def _setup_env(self, api_key: str, api_base: str | None, model: str) -> None:
        """Set environment variables based on detected provider."""
        spec = self._gateway or find_by_model(model)
        if not spec:
            return

        # Gateway/local overrides existing env; standard provider doesn't
        if self._gateway:
            os.environ[spec.env_key] = api_key
        else:
            os.environ.setdefault(spec.env_key, api_key)

        # Resolve env_extras placeholders:
        #   {api_key}  → user's API key
        #   {api_base} → user's api_base, falling back to spec.default_api_base
        effective_base = api_base or spec.default_api_base
        for env_name, env_val in spec.env_extras:
            resolved = env_val.replace("{api_key}", api_key)
            resolved = resolved.replace("{api_base}", effective_base)
            os.environ.setdefault(env_name, resolved)
    
    def _resolve_model(self, model: str) -> str:
        """Resolve model name by applying provider/gateway prefixes."""
        if self._gateway:
            # Gateway mode: apply gateway prefix, skip provider-specific prefixes
            prefix = self._gateway.litellm_prefix
            if self._gateway.strip_model_prefix:
                model = model.split("/")[-1]
            if prefix and not model.startswith(f"{prefix}/"):
                model = f"{prefix}/{model}"
            return model
        
        # Standard mode: auto-prefix for known providers
        spec = find_by_model(model)
        if spec and spec.litellm_prefix:
            if not any(model.startswith(s) for s in spec.skip_prefixes):
                model = f"{spec.litellm_prefix}/{model}"
        
        return model
    
    def _apply_model_overrides(self, model: str, kwargs: dict[str, Any]) -> None:
        """Apply model-specific parameter overrides from the registry."""
        model_lower = model.lower()
        spec = find_by_model(model)
        if spec:
            for pattern, overrides in spec.model_overrides:
                if pattern in model_lower:
                    kwargs.update(overrides)
                    return
    
    def _record_metrics(self, model: str, elapsed: float, response: Any) -> None:
        """Record OTel metrics for an LLM call."""
        try:
            from miu_bot.observability.metrics import llm_latency, llm_tokens

            llm_latency.record(elapsed, {"model": model})
            if response.usage:
                llm_tokens.add(
                    response.usage.get("total_tokens", 0),
                    {"model": model},
                )
        except Exception:
            pass

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request via LiteLLM.
        
        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (e.g., 'anthropic/claude-sonnet-4-5').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
        
        Returns:
            LLMResponse with content and/or tool calls.
        """
        model = self._resolve_model(model or self.default_model)
        
        # Clamp max_tokens to at least 1 — negative or zero values cause
        # LiteLLM to reject the request with "max_tokens must be at least 1".
        max_tokens = max(1, max_tokens)
        
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        
        # Apply model-specific overrides (e.g. kimi-k2.5 temperature)
        self._apply_model_overrides(model, kwargs)
        
        # Pass api_key directly — more reliable than env vars alone
        if self.api_key:
            kwargs["api_key"] = self.api_key
        
        # Pass api_base for custom endpoints
        if self.api_base:
            kwargs["api_base"] = self.api_base
        
        # Pass extra headers (e.g. APP-Code for AiHubMix)
        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers
        
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        
        try:
            start = time.monotonic()
            response = await self._call_with_retry(**kwargs)
            elapsed = time.monotonic() - start
            parsed = self._parse_response(response)
            self._record_metrics(model, elapsed, parsed)
            return parsed
        except Exception as e:
            logger.warning(f"LiteLLM failed after retries: {type(e).__name__}: {str(e)[:200]}")
            # Fallback: if litellm can't parse the response (e.g. non-standard
            # finish_reason from Z.ai), make a direct httpx call and parse manually.
            if self.api_base and self.api_key:
                try:
                    logger.debug(f"Trying direct HTTP fallback to {self.api_base}")
                    return await self._direct_chat(kwargs)
                except Exception as fallback_err:
                    logger.error(f"Direct HTTP fallback also failed: {fallback_err}")
            # Return concise error for graceful handling
            short_error = str(e).split('\n')[0][:300]
            return LLMResponse(
                content=f"Error calling LLM: {short_error}",
                finish_reason="error",
            )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((
            litellm.RateLimitError,
            litellm.APIConnectionError,
            litellm.ServiceUnavailableError,
            litellm.Timeout,
        )),
        reraise=True,
        before_sleep=lambda retry_state: logger.warning(
            f"LLM retry {retry_state.attempt_number}/3 "
            f"after {type(retry_state.outcome.exception()).__name__}"
        ),
    )
    async def _call_with_retry(self, **kwargs: Any) -> Any:
        """Call acompletion with tenacity retry on transient errors."""
        return await acompletion(**kwargs)

    async def _direct_chat(self, kwargs: dict[str, Any]) -> LLMResponse:
        """Direct HTTP fallback when LiteLLM can't parse the provider's response."""
        url = f"{self.api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.extra_headers:
            headers.update(self.extra_headers)

        # Build OpenAI-compatible request body
        body: dict[str, Any] = {
            "model": kwargs["model"].split("/")[-1],  # strip litellm prefix
            "messages": kwargs["messages"],
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7),
        }
        if kwargs.get("tools"):
            body["tools"] = kwargs["tools"]
            body["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code >= 400:
                logger.error(f"LLM API error {resp.status_code}: {resp.text[:500]}")
            resp.raise_for_status()
            data = resp.json()

        return self._parse_raw_response(data)

    def _parse_raw_response(self, data: dict[str, Any]) -> LLMResponse:
        """Parse a raw OpenAI-compatible JSON response dict."""
        choice = data["choices"][0]
        message = choice.get("message", {})

        tool_calls = []
        for tc in (message.get("tool_calls") or []):
            args = tc["function"]["arguments"]
            if isinstance(args, str):
                args = json_repair.loads(args)
            tool_calls.append(ToolCallRequest(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=args,
            ))

        usage = {}
        if "usage" in data and data["usage"]:
            usage = {
                "prompt_tokens": data["usage"].get("prompt_tokens", 0),
                "completion_tokens": data["usage"].get("completion_tokens", 0),
                "total_tokens": data["usage"].get("total_tokens", 0),
            }

        # Map non-standard finish_reasons to 'stop'
        finish_reason = choice.get("finish_reason", "stop")
        if finish_reason not in ("stop", "tool_calls", "length", "content_filter"):
            logger.debug(f"Non-standard finish_reason '{finish_reason}', mapping to 'stop'")
            finish_reason = "stop"

        return LLMResponse(
            content=message.get("content") or "",
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            reasoning_content=message.get("reasoning_content"),
        )

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse LiteLLM response into our standard format."""
        choice = response.choices[0]
        message = choice.message
        
        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                # Parse arguments from JSON string if needed
                args = tc.function.arguments
                if isinstance(args, str):
                    args = json_repair.loads(args)
                
                tool_calls.append(ToolCallRequest(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))
        
        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        
        reasoning_content = getattr(message, "reasoning_content", None)
        
        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
            reasoning_content=reasoning_content,
        )
    
    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ):
        """Stream chat completion, yielding partial content and tool calls.

        Yields dicts with keys:
          - {"type": "content", "delta": "text chunk"}
          - {"type": "tool_calls", "tool_calls": [...]}
          - {"type": "done", "usage": {...}, "finish_reason": "stop"|"tool_calls"}
        """
        model = self._resolve_model(model or self.default_model)
        max_tokens = max(1, max_tokens)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        self._apply_model_overrides(model, kwargs)
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await acompletion(**kwargs)
        accumulated_tool_calls: dict[int, dict[str, str]] = {}
        usage: dict[str, int] = {}

        async for chunk in response:
            choice = chunk.choices[0] if chunk.choices else None
            if not choice:
                continue

            delta = choice.delta
            finish_reason = choice.finish_reason

            if hasattr(delta, "content") and delta.content:
                yield {"type": "content", "delta": delta.content}

            if hasattr(delta, "tool_calls") and delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in accumulated_tool_calls:
                        accumulated_tool_calls[idx] = {
                            "id": "", "name": "", "arguments": ""
                        }
                    tc = accumulated_tool_calls[idx]
                    if tc_delta.id:
                        tc["id"] = tc_delta.id
                    if hasattr(tc_delta, "function") and tc_delta.function:
                        if tc_delta.function.name:
                            tc["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tc["arguments"] += tc_delta.function.arguments

            if hasattr(chunk, "usage") and chunk.usage:
                usage = {
                    "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(chunk.usage, "completion_tokens", 0),
                    "total_tokens": getattr(chunk.usage, "total_tokens", 0),
                }

            if finish_reason:
                if accumulated_tool_calls:
                    tool_calls_list = []
                    for tc in accumulated_tool_calls.values():
                        args = json_repair.loads(tc["arguments"]) if tc["arguments"] else {}
                        tool_calls_list.append(ToolCallRequest(
                            id=tc["id"], name=tc["name"], arguments=args,
                        ))
                    yield {"type": "tool_calls", "tool_calls": tool_calls_list}
                yield {
                    "type": "done",
                    "usage": usage,
                    "finish_reason": finish_reason,
                }
                return

    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
