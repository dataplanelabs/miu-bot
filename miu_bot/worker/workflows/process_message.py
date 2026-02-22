"""ProcessMessage workflow — main message processing via Hatchet."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from miu_bot.db.backend import MemoryBackend
    from miu_bot.providers.base import LLMProvider
    from miu_bot.agent.tools.registry import ToolRegistry


class ProcessMessageWorkflow:
    """Hatchet workflow for processing a single inbound message.

    Registered with: on_events=["message:received"]
    Concurrency: key=input.session_id, max_runs=1
    """

    def __init__(
        self,
        backend: "MemoryBackend",
        provider: "LLMProvider",
        tools: "ToolRegistry",
        model: str,
        gateway_url: str = "http://localhost:18790",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        max_iterations: int = 20,
    ):
        self.backend = backend
        self.provider = provider
        self.tools = tools
        self.model = model
        self.gateway_url = gateway_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations

    async def process(self, workflow_input: dict[str, Any]) -> dict[str, Any]:
        """Process a message:received event."""
        from miu_bot.workspace.identity import parse_identity
        from miu_bot.agent.context import ContextBuilder
        from miu_bot.agent.processor import run_agent_loop
        from miu_bot.worker.response import send_response

        workspace_id = workflow_input["workspace_id"]
        session_id = workflow_input["session_id"]
        channel = workflow_input["channel"]
        chat_id = workflow_input["chat_id"]
        content = workflow_input["content"]
        metadata = workflow_input.get("metadata", {})

        # Load workspace
        workspace = await self.backend.get_workspace(workspace_id)
        if not workspace or workspace.status != "active":
            return {"status": "skipped", "reason": "workspace_inactive"}

        # Load context
        messages = await self.backend.get_messages(session_id, limit=50)
        memories = await self.backend.get_memories(workspace_id)

        identity = parse_identity(workspace.identity)
        memories_text = "\n".join(m.content for m in memories)
        history = [{"role": m.role, "content": m.content} for m in messages]

        context_builder = ContextBuilder(workspace_path=None)
        llm_messages = context_builder.build_workspace_messages(
            identity=identity, memories=memories_text, history=history,
            current_message=content, channel=channel, chat_id=chat_id,
        )

        # Run agent loop
        response_content, tools_used = await run_agent_loop(
            provider=self.provider, messages=llm_messages, tools=self.tools,
            model=self.model, temperature=self.temperature,
            max_tokens=self.max_tokens, max_iterations=self.max_iterations,
        )

        if response_content is None:
            response_content = "I've completed processing but have no response to give."

        # Save messages
        await self.backend.save_message(session_id, "user", content, metadata)
        await self.backend.save_message(
            session_id, "assistant", response_content,
            {"tools_used": tools_used} if tools_used else None,
        )

        # Send response via gateway
        await send_response(self.gateway_url, channel, chat_id, response_content, metadata)

        return {"status": "ok", "tools_used": tools_used}
