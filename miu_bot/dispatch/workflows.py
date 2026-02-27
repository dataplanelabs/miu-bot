"""Temporal workflow definitions for miu_bot dispatch."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from loguru import logger
    from miu_bot.worker.workflows.shared import _FALLBACK_MESSAGE


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
        self._current_trace: list[dict[str, Any]] = []
        self._processing_state: dict[str, Any] = {}

    @workflow.signal
    async def new_message(self, msg: dict[str, Any]) -> None:
        """Signal: new inbound message for this session."""
        self._pending_messages.append(msg)

    @workflow.query
    def get_streaming_state(self) -> dict[str, Any]:
        """Query: current streaming state for gateway polling (Phase 6)."""
        return self._streaming_state

    @workflow.query
    def get_current_trace(self) -> list[dict[str, Any]]:
        """Query: accumulated trace events for current/last message."""
        return self._current_trace

    @workflow.query
    def get_processing_state(self) -> dict[str, Any]:
        """Query: current processing metadata (model, tools, timing)."""
        return self._processing_state

    @workflow.run
    async def run(self, session_info: dict[str, Any]) -> None:
        """Main workflow loop — waits for signals, dispatches activities."""
        while True:
            await workflow.wait_condition(
                lambda: len(self._pending_messages) > 0
            )
            msg = self._pending_messages.pop(0)

            try:
                result = await workflow.execute_activity(
                    "process_message_activity",
                    args=[msg, session_info],
                    start_to_close_timeout=timedelta(minutes=10),
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=2),
                        maximum_interval=timedelta(seconds=30),
                        maximum_attempts=3,
                    ),
                )
                # Store trace from activity result for query inspection
                if isinstance(result, dict):
                    self._current_trace = result.get("trace", [])
                    self._processing_state = {
                        "status": result.get("status"),
                        "bot": result.get("bot"),
                        "model": result.get("model"),
                        "tools_used": result.get("tools_used", []),
                        "total_s": result.get("total_s"),
                    }

                    # Send response ONLY after processing fully succeeds.
                    # This prevents duplicate messages on activity retries.
                    if result.get("status") == "ok" and result.get("response_content"):
                        await workflow.execute_activity(
                            "send_response_activity",
                            args=[{
                                "channel": result["channel"],
                                "chat_id": result["chat_id"],
                                "content": result["response_content"],
                                "metadata": result.get("metadata", {}),
                                "bot_name": result.get("bot", ""),
                            }],
                            start_to_close_timeout=timedelta(seconds=30),
                            retry_policy=RetryPolicy(maximum_attempts=3),
                        )
            except ActivityError:
                logger.error(
                    f"Message processing failed after retries, "
                    f"session={session_info.get('session_id', '?')[:8]}, sending fallback"
                )
                # Send fallback so user isn't left hanging
                try:
                    await workflow.execute_activity(
                        "send_response_activity",
                        args=[{
                            "channel": msg.get("channel", ""),
                            "chat_id": msg.get("chat_id", ""),
                            "content": _FALLBACK_MESSAGE,
                            "metadata": msg.get("metadata", {}),
                            "bot_name": msg.get("bot_name", ""),
                        }],
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                except ActivityError:
                    logger.error("Failed to send fallback message, giving up")

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
