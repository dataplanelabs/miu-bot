"""Usage logging, budget enforcement, and in-memory rate limiting (MIU-26)."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from miu_bot.db.backend import MemoryBackend


class BudgetExceededError(Exception):
    """Raised when a workspace exceeds its configured hard budget."""

    def __init__(self, workspace_id: str, limit: float, current_spend: float) -> None:
        self.workspace_id = workspace_id
        self.limit = limit
        self.current_spend = current_spend
        super().__init__(
            f"Budget of ${limit:.2f} USD exceeded (spent: ${current_spend:.4f})"
        )


class RateLimitError(Exception):
    """Raised when a workspace exceeds its configured RPM limit."""

    def __init__(self, workspace_id: str, limit: int) -> None:
        self.workspace_id = workspace_id
        self.limit = limit
        super().__init__(f"Rate limit of {limit} requests/minute exceeded")


class RateLimiter:
    """In-memory sliding-window RPM limiter. Resets on worker restart (acceptable)."""

    def __init__(self) -> None:
        self._windows: dict[str, deque[float]] = defaultdict(deque)

    def check_rpm(self, workspace_id: str, limit: int) -> None:
        """Record request and raise RateLimitError if RPM exceeded.

        limit <= 0 means unlimited — returns immediately.
        """
        if limit <= 0:
            return
        now = datetime.now(timezone.utc).timestamp()
        window = self._windows[workspace_id]
        # Evict entries older than 60 seconds
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= limit:
            raise RateLimitError(workspace_id, limit)
        window.append(now)


class UsageLogger:
    """Wraps backend usage methods with error isolation and soft-budget alerting."""

    async def log_usage(
        self,
        backend: "MemoryBackend",
        workspace_id: str,
        session_id: str | None,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost_usd: float,
    ) -> None:
        """Insert usage_logs row and increment spend_current. Safe for fire-and-forget."""
        try:
            await backend.log_usage(
                workspace_id, session_id, model,
                prompt_tokens, completion_tokens, total_tokens, cost_usd,
            )
        except Exception as exc:
            logger.warning("Failed to log usage for workspace %s: %s", workspace_id, exc)

    async def check_budget(self, workspace: Any) -> None:
        """Check hard and soft budget limits against workspace spend.

        Raises BudgetExceededError on hard limit. Logs warning on soft limit.
        workspace.max_budget_usd = None means unlimited.
        """
        if workspace.max_budget_usd is None:
            return

        spend = float(workspace.spend_current or 0)
        hard = float(workspace.max_budget_usd)

        if spend >= hard:
            raise BudgetExceededError(workspace.id, hard, spend)

        # Soft alert — non-blocking
        if workspace.soft_budget_usd is not None:
            soft = float(workspace.soft_budget_usd)
            if spend >= soft:
                logger.warning(
                    "Workspace %s approaching budget limit ($%.4f spent / $%.2f soft / $%.2f hard)",
                    workspace.id, spend, soft, hard,
                )
