"""CronTask processor — executes scheduled bot jobs via agent loop."""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any, TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from miu_bot.db.backend import MemoryBackend


class CronTaskProcessor:
    """Processor for cron-triggered bot jobs.

    Follows ProcessMessageWorkflow pattern but:
    - No session persistence (fire-and-forget)
    - Multi-target delivery
    - Prompt from job config, not user message
    """

    def __init__(
        self,
        backend: "MemoryBackend",
        gateway_url: str = "http://localhost:18790",
        fallback_model: str = "",
        fallback_api_key: str = "",
        fallback_api_base: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        max_iterations: int = 20,
    ):
        self.backend = backend
        self.gateway_url = gateway_url
        self.fallback_model = fallback_model
        self.fallback_api_key = fallback_api_key
        self.fallback_api_base = fallback_api_base
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_iterations = max_iterations

    async def process(self, task_info: dict[str, Any]) -> dict[str, Any]:
        """Execute a cron job: load bot context, run agent loop, deliver to targets."""
        from miu_bot.agent.processor import run_agent_loop
        from miu_bot.agent.tools.registry import ToolRegistry
        from miu_bot.config.bots import _resolve_env_fields
        from miu_bot.memory.context_assembly import assemble_memory_context
        from miu_bot.worker.response import send_response
        from miu_bot.workspace.identity import (
            compose_from_templates,
            parse_identity,
            render_system_prompt,
        )

        workspace_id = task_info["workspace_id"]
        bot_name = task_info["bot_name"]
        job_name = task_info["job_name"]
        prompt = task_info["prompt"]
        targets = task_info.get("targets", [])

        logger.info(f"Cron job starting: {bot_name}:{job_name}")

        # Load workspace
        workspace = await self.backend.get_workspace(workspace_id)
        if not workspace or workspace.status != "active":
            return {"status": "skipped", "reason": "workspace_inactive"}

        # Create per-workspace provider
        provider, model = self._create_provider(workspace.config_overrides)

        # Setup tools and MCP
        tools = ToolRegistry()
        mcp_stack = AsyncExitStack()
        await mcp_stack.__aenter__()
        try:
            # Load templates and skills from DB
            templates = await self.backend.get_templates(workspace_id)
            db_skills = await self.backend.get_skills(workspace_id)

            # Connect MCP servers from config_overrides
            mcp_count = await self._connect_mcp(
                workspace.config_overrides, tools, mcp_stack
            )
            if mcp_count:
                logger.info(f"Connected {mcp_count} MCP server(s) for cron {bot_name}:{job_name}")

            # Build memory context
            memories_text = await assemble_memory_context(
                self.backend, workspace_id, query=prompt
            )

            # Compose base prompt: templates (new) or identity (legacy)
            if templates:
                base_prompt = compose_from_templates(templates, memories_text)
            else:
                identity = parse_identity(workspace.identity)
                base_prompt = render_system_prompt(identity, memories_text)

            # Merge skills
            skills_section = ""
            skill_mcp: dict = {}
            if db_skills:
                from miu_bot.skills.merger import merge_skills_from_db
                skills_section, skill_mcp, _ = merge_skills_from_db(db_skills)
            else:
                skill_dicts = workspace.config_overrides.get("skills", [])
                if skill_dicts:
                    from miu_bot.skills.merger import merge_skills_into_prompt
                    from miu_bot.skills.schema import SkillConfig
                    skills = [SkillConfig.model_validate(s) for s in skill_dicts]
                    skills_section, skill_mcp, _ = merge_skills_into_prompt("", skills)

            full_prompt = base_prompt
            if skills_section:
                full_prompt = f"{base_prompt}\n\n{skills_section}"

            # Connect skill-provided MCP servers
            if skill_mcp:
                from miu_bot.config.schema import MCPServerConfig
                from miu_bot.agent.tools.mcp import connect_mcp_servers
                for name, cfg_dict in skill_mcp.items():
                    resolved = _resolve_env_fields(cfg_dict)
                    cfg = MCPServerConfig.model_validate(resolved)
                    if cfg.url:
                        extra = await connect_mcp_servers({name: cfg}, tools, mcp_stack)
                        mcp_count += extra

            # Build LLM messages — no history (cron job has no conversation)
            llm_messages = [
                {"role": "system", "content": full_prompt},
                {"role": "user", "content": prompt},
            ]

            # Run agent loop
            response_content, tools_used, trace = await run_agent_loop(
                provider=provider, messages=llm_messages, tools=tools,
                model=model, temperature=self.temperature,
                max_tokens=self.max_tokens,
                max_iterations=self.max_iterations,
            )

            # Multi-target delivery
            delivered = 0
            if response_content:
                for target in targets:
                    resolved = _resolve_env_fields(target)
                    channel = resolved.get("channel", "")
                    chat_id = resolved.get("chat_id", "")
                    if not channel or not chat_id:
                        logger.warning(f"Job {bot_name}:{job_name} - invalid target: {target}")
                        continue
                    await send_response(
                        self.gateway_url, channel, chat_id,
                        response_content, bot_name=bot_name,
                    )
                    delivered += 1

            logger.info(
                f"Cron job done: {bot_name}:{job_name} "
                f"tools={tools_used} delivered={delivered}"
            )
            return {
                "status": "ok",
                "bot": bot_name,
                "job": job_name,
                "model": model,
                "tools_used": tools_used,
                "delivered": delivered,
                "response_preview": (response_content or "")[:300],
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
        """Create LLMProvider from workspace config_overrides."""
        from miu_bot.config.bots import _resolve_env_fields
        from miu_bot.providers.litellm_provider import LiteLLMProvider

        provider_cfg = config_overrides.get("provider", {})
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
        """Connect HTTP MCP servers from workspace config_overrides."""
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
