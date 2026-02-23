"""ProcessMessage workflow — main message processing."""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any, TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from miu_bot.db.backend import MemoryBackend


class ProcessMessageWorkflow:
    """Workflow for processing a single inbound message.

    Per-message: creates provider, tools, MCP from workspace.config_overrides.
    """

    def __init__(
        self,
        backend: "MemoryBackend",
        gateway_url: str = "http://localhost:18790",
        # Fallback defaults (used when workspace has no provider override)
        fallback_model: str = "anthropic/claude-opus-4-6",
        fallback_api_key: str = "",
        fallback_api_base: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        max_iterations: int = 20,
    ):
        self.backend = backend
        self.gateway_url = gateway_url
        self.fallback_model = fallback_model
        self.fallback_api_key = fallback_api_key
        self.fallback_api_base = fallback_api_base
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations

    async def process(self, workflow_input: dict[str, Any]) -> dict[str, Any]:
        """Process a message:received event."""
        import time as _time

        from temporalio import activity

        from miu_bot.workspace.identity import parse_identity
        from miu_bot.agent.context import ContextBuilder
        from miu_bot.agent.processor import run_agent_loop
        from miu_bot.agent.tools.registry import ToolRegistry
        from miu_bot.worker.response import send_response

        t_start = _time.monotonic()

        workspace_id = workflow_input["workspace_id"]
        channel = workflow_input["channel"]
        chat_id = workflow_input["chat_id"]
        content = workflow_input["content"]
        metadata = workflow_input.get("metadata", {})
        bot_name = workflow_input.get("bot_name", "")

        # Load workspace
        workspace = await self.backend.get_workspace(workspace_id)
        if not workspace or workspace.status != "active":
            return {"status": "skipped", "reason": "workspace_inactive"}

        # Ensure session exists (keyed by workspace + channel + chat_id)
        session = await self.backend.get_or_create_session(
            workspace_id, channel, chat_id,
        )
        session_id = session.id

        # Create per-workspace provider
        provider, model = self._create_provider(workspace.config_overrides)

        # Create per-workspace tools (MCP)
        tools = ToolRegistry()
        mcp_stack = AsyncExitStack()
        await mcp_stack.__aenter__()
        try:
            # Build augmented prompt from skills
            augmented_identity = workspace.identity
            skill_dicts = workspace.config_overrides.get("skills", [])
            if skill_dicts:
                from miu_bot.skills.merger import merge_skills_into_prompt
                from miu_bot.skills.schema import SkillConfig

                skills = [SkillConfig.model_validate(s) for s in skill_dicts]
                augmented_identity, _, _ = merge_skills_into_prompt(
                    workspace.identity, skills
                )

            mcp_count = await self._connect_mcp(
                workspace.config_overrides, tools, mcp_stack
            )
            if mcp_count:
                logger.info(f"Connected {mcp_count} MCP server(s) for {bot_name}")

            # Load context
            messages = await self.backend.get_messages(session_id, limit=50)

            # Use tier-based context assembly (BASB)
            from miu_bot.memory.context_assembly import assemble_memory_context

            identity = parse_identity(augmented_identity)
            memories_text = await assemble_memory_context(
                self.backend, workspace_id, query=content
            )
            history = [{"role": m.role, "content": m.content} for m in messages]

            context_builder = ContextBuilder(workspace=None)
            llm_messages = context_builder.build_workspace_messages(
                identity=identity, memories=memories_text, history=history,
                current_message=content, channel=channel, chat_id=chat_id,
            )

            # Run agent loop with heartbeat reporting
            def _heartbeat(data: dict) -> None:
                try:
                    activity.heartbeat(data)
                except Exception:
                    pass  # heartbeat failures are non-fatal

            response_content, tools_used, trace = await run_agent_loop(
                provider=provider, messages=llm_messages, tools=tools,
                model=model, temperature=self.temperature,
                max_tokens=self.max_tokens,
                max_iterations=self.max_iterations,
                on_heartbeat=_heartbeat,
            )

            if response_content is None:
                response_content = (
                    "I've completed processing but have no response to give."
                )

            # Save messages
            await self.backend.save_message(
                session_id, "user", content, metadata
            )
            await self.backend.save_message(
                session_id, "assistant", response_content,
                {"tools_used": tools_used} if tools_used else None,
            )

            # Send response via gateway (include bot_name for routing)
            await send_response(
                self.gateway_url, channel, chat_id,
                response_content, metadata, bot_name=bot_name,
            )

            total_s = round(_time.monotonic() - t_start, 2)
            return {
                "status": "ok",
                "bot": bot_name,
                "model": model,
                "tools_used": tools_used,
                "total_s": total_s,
                "response_preview": response_content[:300],
                "trace": trace,
            }
        finally:
            try:
                await mcp_stack.aclose()
            except RuntimeError as e:
                if "cancel scope" in str(e):
                    logger.debug(f"Suppressed MCP cleanup error: {e}")
                else:
                    raise

    def _create_provider(
        self, config_overrides: dict[str, Any]
    ) -> tuple[Any, str]:
        """Create LLMProvider from workspace config_overrides.

        Resolves *_env references from os.environ at runtime.
        Returns (provider, model_string).
        """
        from miu_bot.config.bots import _resolve_env_fields
        from miu_bot.providers.litellm_provider import LiteLLMProvider

        provider_cfg = config_overrides.get("provider", {})
        # Resolve *_env fields (api_key_env, api_base_env) from worker's env vars
        resolved = _resolve_env_fields(provider_cfg)
        model = resolved.get("model", self.fallback_model)
        api_key = resolved.get("api_key", self.fallback_api_key)
        api_base = resolved.get("api_base", self.fallback_api_base)

        provider = LiteLLMProvider(
            api_key=api_key,
            api_base=api_base,
            default_model=model,
        )
        return provider, model

    async def _connect_mcp(
        self,
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

        mcp_raw = (
            config_overrides.get("tools", {}).get("mcp_servers", {})
        )
        if not mcp_raw:
            return 0

        # Resolve *_env fields and filter to HTTP-only
        mcp_servers: dict[str, MCPServerConfig] = {}
        for name, cfg_dict in mcp_raw.items():
            resolved = _resolve_env_fields(cfg_dict)
            cfg = MCPServerConfig.model_validate(resolved)
            # V1: skip stdio MCP servers (no command field)
            if cfg.url:
                mcp_servers[name] = cfg
            elif cfg.command:
                logger.info(f"Skipping stdio MCP '{name}' (deferred to V2)")

        if not mcp_servers:
            return 0

        return await connect_mcp_servers(mcp_servers, tools, stack)
