"""CronTask workflow — event-triggered cron task execution."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from miu_bot.db.backend import MemoryBackend
    from miu_bot.providers.base import LLMProvider
    from miu_bot.agent.tools.registry import ToolRegistry


class CronTaskWorkflow:
    """Workflow for executing cron-triggered tasks."""

    def __init__(
        self,
        backend: "MemoryBackend",
        provider: "LLMProvider",
        tools: "ToolRegistry",
        model: str,
        gateway_url: str = "http://localhost:18790",
    ):
        self.backend = backend
        self.provider = provider
        self.tools = tools
        self.model = model
        self.gateway_url = gateway_url

    async def process(self, workflow_input: dict[str, Any]) -> dict[str, Any]:
        """Execute a cron task."""
        from miu_bot.agent.processor import run_agent_loop
        from miu_bot.worker.response import send_response

        workspace_id = workflow_input["workspace_id"]
        task_message = workflow_input["task_message"]
        deliver_to = workflow_input.get("deliver_to")
        channel = workflow_input.get("channel", "cli")

        messages = [
            {"role": "system", "content": "You are a task execution agent."},
            {"role": "user", "content": task_message},
        ]

        response_content, tools_used, _trace = await run_agent_loop(
            provider=self.provider, messages=messages, tools=self.tools,
            model=self.model,
        )

        if deliver_to and response_content:
            await send_response(self.gateway_url, channel, deliver_to, response_content)

        return {"status": "ok", "response": response_content or ""}
