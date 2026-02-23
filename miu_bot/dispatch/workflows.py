"""Temporal workflow definitions for miu_bot dispatch."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from loguru import logger


@workflow.defn
class BotSessionWorkflow:
    """Durable per-session workflow. One instance per (workspace, session).

    Receives message signals, dispatches processing as activities,
    and triggers consolidation periodically.
    """

    def __init__(self) -> None:
        self._pending_messages: list[dict[str, Any]] = []
        self._message_count: int = 0
        self._streaming_state: dict[str, Any] = {
            "content": "",
            "is_done": True,
        }

    @workflow.signal
    async def new_message(self, msg: dict[str, Any]) -> None:
        """Signal: new inbound message for this session."""
        self._pending_messages.append(msg)

    @workflow.query
    def get_streaming_state(self) -> dict[str, Any]:
        """Query: current streaming state for gateway polling (Phase 6)."""
        return self._streaming_state

    @workflow.run
    async def run(self, session_info: dict[str, Any]) -> None:
        """Main workflow loop — waits for signals, dispatches activities."""
        while True:
            await workflow.wait_condition(
                lambda: len(self._pending_messages) > 0
            )
            msg = self._pending_messages.pop(0)

            try:
                await workflow.execute_activity(
                    "process_message_activity",
                    args=[msg, session_info],
                    start_to_close_timeout=timedelta(minutes=5),
                    heartbeat_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=2),
                        maximum_interval=timedelta(seconds=30),
                        maximum_attempts=3,
                    ),
                )
            except ActivityError:
                logger.error(
                    f"Message processing failed after retries, "
                    f"session={session_info.get('session_id', '?')[:8]}, skipping"
                )

            self._message_count += 1

            # ContinueAsNew every 500 messages to cap history growth
            if self._message_count >= 500:
                workflow.continue_as_new(args=[session_info])


@workflow.defn
class ConsolidateMemoryWorkflow:
    """Child workflow for BASB memory consolidation (Phase 4)."""

    @workflow.run
    async def run(self, workspace_id: str, consolidation_type: str = "daily") -> dict[str, Any]:
        result = await workflow.execute_activity(
            "consolidate_memory_activity",
            args=[workspace_id, consolidation_type],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return result


@workflow.defn
class CronTaskWorkflow:
    """Scheduled workflow for cron jobs (replaces APScheduler)."""

    @workflow.run
    async def run(self, task_info: dict[str, Any]) -> dict[str, Any]:
        result = await workflow.execute_activity(
            "run_cron_activity",
            args=[task_info],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return result
