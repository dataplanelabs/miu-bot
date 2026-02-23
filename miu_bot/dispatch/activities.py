"""Temporal activity definitions — thin wrappers around core logic."""

from __future__ import annotations

from typing import Any

from temporalio import activity

from loguru import logger


@activity.defn
async def process_message_activity(
    msg: dict[str, Any], session_info: dict[str, Any]
) -> dict[str, Any]:
    """Process a single message through the agent loop.

    Delegates to ProcessMessageWorkflow (existing worker logic).
    """
    from miu_bot.worker.workflows.process_message import ProcessMessageWorkflow

    # Retrieve deps from activity-scoped context (set during worker startup)
    deps = activity.info().activity_type  # placeholder — see worker.py for injection
    # Actually, we use a module-level registry for deps (set by worker startup)
    from miu_bot.dispatch.worker import get_activity_deps

    deps = get_activity_deps()

    wf = ProcessMessageWorkflow(
        backend=deps["backend"],
        gateway_url=deps["gateway_url"],
        fallback_model=deps["fallback_model"],
        fallback_api_key=deps["fallback_api_key"],
        fallback_api_base=deps["fallback_api_base"],
        max_tokens=deps["max_tokens"],
        temperature=deps["temperature"],
        max_iterations=deps["max_iterations"],
    )

    workflow_input = {
        "workspace_id": session_info["workspace_id"],
        "session_id": session_info["session_id"],
        "channel": msg.get("channel", ""),
        "chat_id": msg.get("chat_id", ""),
        "sender_id": msg.get("sender_id", ""),
        "content": msg.get("content", ""),
        "metadata": msg.get("metadata", {}),
        "bot_name": session_info.get("bot_name", ""),
    }

    logger.info(
        f"Processing message: ws={workflow_input['workspace_id'][:8]} "
        f"bot={workflow_input['bot_name']} channel={workflow_input['channel']}"
    )
    result = await wf.process(workflow_input)
    logger.info(f"Message processed: status={result.get('status', '?')}")
    return result


@activity.defn
async def consolidate_memory_activity(
    workspace_id: str, consolidation_type: str = "daily"
) -> dict[str, Any]:
    """Thin wrapper for memory consolidation.

    Core logic lives in memory/consolidation.py — testable without Temporal.
    """
    from miu_bot.dispatch.worker import get_activity_deps
    from miu_bot.providers.litellm_provider import LiteLLMProvider

    logger.info(f"Consolidation activity: ws={workspace_id[:8]} type={consolidation_type}")

    deps = get_activity_deps()
    backend = deps["backend"]
    pool = deps.get("pool")

    if not pool:
        logger.error("No connection pool available for consolidation")
        return {"status": "error", "error": "no_pool"}

    # Create provider from fallback config
    provider = LiteLLMProvider(
        api_key=deps.get("fallback_api_key", ""),
        api_base=deps.get("fallback_api_base"),
        default_model=deps.get("fallback_model", ""),
    )
    model = deps.get("fallback_model", "")

    # Route to the appropriate consolidation class
    if consolidation_type == "weekly":
        from miu_bot.memory.weekly import WeeklyConsolidation

        consolidation = WeeklyConsolidation(backend, pool)
    elif consolidation_type == "monthly":
        from miu_bot.memory.monthly import MonthlyConsolidation

        consolidation = MonthlyConsolidation(backend, pool)
    else:
        from miu_bot.memory.consolidation import DailyConsolidation

        consolidation = DailyConsolidation(backend, pool)

    result = await consolidation.run_for_workspace(workspace_id, provider, model)
    logger.info(f"Consolidation result: ws={workspace_id[:8]} {result}")

    try:
        from miu_bot.observability.metrics import consolidation_runs

        consolidation_runs.add(1, {
            "type": consolidation_type,
            "status": result.get("status", "unknown"),
        })
    except Exception:
        pass

    return result


@activity.defn
async def run_cron_activity(task_info: dict[str, Any]) -> dict[str, Any]:
    """Run a scheduled cron task."""
    logger.info(f"Cron activity: {task_info.get('name', 'unnamed')}")
    # Cron execution will be wired in Phase 4+
    return {"status": "not_implemented"}
