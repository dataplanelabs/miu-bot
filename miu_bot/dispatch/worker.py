"""Temporal worker with configurable task queues."""

from __future__ import annotations

import asyncio
from typing import Any, TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from temporalio.client import Client

# Module-level activity dependency registry (set once at worker startup)
_activity_deps: dict[str, Any] = {}


def set_activity_deps(deps: dict[str, Any]) -> None:
    """Set shared dependencies for activity functions."""
    global _activity_deps
    _activity_deps = deps


def get_activity_deps() -> dict[str, Any]:
    """Get shared dependencies for activity functions."""
    if not _activity_deps:
        raise RuntimeError("Activity deps not initialized — call set_activity_deps() first")
    return _activity_deps


async def run_temporal_worker(
    client: "Client",
    task_queues: list[str],
) -> None:
    """Start Temporal worker(s) polling specified task queues.

    Each task queue gets its own Worker instance. All run concurrently.
    """
    from temporalio.worker import Worker

    from miu_bot.dispatch.workflows import (
        BotSessionWorkflow,
        ConsolidateMemoryWorkflow,
        CronTaskWorkflow,
    )
    from miu_bot.dispatch.activities import (
        process_message_activity,
        send_response_activity,
        consolidate_memory_activity,
        run_cron_activity,
    )

    workflows = [BotSessionWorkflow, ConsolidateMemoryWorkflow, CronTaskWorkflow]
    activities = [
        process_message_activity,
        send_response_activity,
        consolidate_memory_activity,
        run_cron_activity,
    ]

    workers: list[Worker] = []
    for queue in task_queues:
        w = Worker(
            client,
            task_queue=queue,
            workflows=workflows,
            activities=activities,
        )
        workers.append(w)
        logger.info(f"Temporal worker registered: queue={queue}")

    logger.info(f"Starting {len(workers)} Temporal worker(s)...")
    await asyncio.gather(*(w.run() for w in workers))
