"""Gateway-side Temporal dispatch: start or signal session workflows."""

from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from temporalio.client import Client


def _build_workflow_id(bot_name: str, channel: str, chat_id: str, session_id: str) -> str:
    """Build a human-readable, deterministic workflow ID.

    Format: ``session-{bot}-{channel}-{chat_id}``
    Falls back to session UUID when bot_name is unavailable.
    """
    if bot_name:
        # Sanitise: Temporal allows [a-zA-Z0-9._-]
        safe = re.sub(r"[^a-zA-Z0-9._-]", "_", f"{bot_name}-{channel}-{chat_id}")
        return f"session-{safe}"
    return f"session-{session_id}"


async def dispatch_message(
    client: "Client",
    workspace_id: str,
    session_id: str,
    channel: str,
    chat_id: str,
    sender_id: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    bot_name: str = "",
    task_queue: str = "default-tasks",
    media: list[str] | None = None,
) -> None:
    """Start or signal a BotSessionWorkflow for the given session.

    If the workflow already exists, signals it with the new message.
    If not, starts a new workflow and then signals it.
    """
    from temporalio.client import WorkflowExecutionStatus
    from temporalio.service import RPCError

    from miu_bot.dispatch.workflows import BotSessionWorkflow

    workflow_id = _build_workflow_id(bot_name, channel, chat_id, session_id)
    msg_dict = {
        "channel": channel,
        "chat_id": chat_id,
        "sender_id": sender_id,
        "content": content,
        "metadata": metadata or {},
        "media": media or [],
    }
    session_info = {
        "workspace_id": workspace_id,
        "session_id": session_id,
        "bot_name": bot_name,
        "task_queue": task_queue,
    }

    try:
        # Try to signal existing workflow
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()
        if desc.status == WorkflowExecutionStatus.RUNNING:
            await handle.signal(BotSessionWorkflow.new_message, msg_dict)
            logger.debug(f"Signaled existing workflow: {workflow_id}")
            return
    except RPCError:
        pass  # Workflow doesn't exist — start a new one

    # Start new workflow
    await client.start_workflow(
        BotSessionWorkflow.run,
        args=[session_info],
        id=workflow_id,
        task_queue=task_queue,
    )
    # Signal the newly started workflow with the message
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(BotSessionWorkflow.new_message, msg_dict)
    logger.info(f"Started new workflow + signaled: {workflow_id} queue={task_queue}")
