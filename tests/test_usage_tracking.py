"""Unit tests for miu_bot.db.usage — RateLimiter, UsageLogger, budget enforcement."""
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from miu_bot.db.backend import Workspace
from miu_bot.db.usage import BudgetExceededError, RateLimitError, RateLimiter, UsageLogger


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------

def test_rate_limiter_allows_under_limit():
    limiter = RateLimiter()
    for _ in range(5):
        limiter.check_rpm("ws-1", limit=10)  # no exception


def test_rate_limiter_blocks_at_limit():
    limiter = RateLimiter()
    for _ in range(3):
        limiter.check_rpm("ws-1", limit=3)
    with pytest.raises(RateLimitError) as exc_info:
        limiter.check_rpm("ws-1", limit=3)
    assert exc_info.value.workspace_id == "ws-1"
    assert exc_info.value.limit == 3


def test_rate_limiter_zero_means_unlimited():
    limiter = RateLimiter()
    for _ in range(100):
        limiter.check_rpm("ws-unlimited", limit=0)  # no exception


def test_rate_limiter_negative_means_unlimited():
    limiter = RateLimiter()
    for _ in range(50):
        limiter.check_rpm("ws-neg", limit=-1)  # no exception


def test_rate_limiter_independent_workspaces():
    limiter = RateLimiter()
    # Fill ws-1 to limit
    for _ in range(3):
        limiter.check_rpm("ws-1", limit=3)
    # ws-2 is unaffected
    limiter.check_rpm("ws-2", limit=3)  # no exception
    # ws-1 now raises
    with pytest.raises(RateLimitError):
        limiter.check_rpm("ws-1", limit=3)


def test_rate_limiter_window_expiry(monkeypatch):
    """Entries older than 60 s are evicted, freeing capacity."""
    limiter = RateLimiter()

    # Manually inject a timestamp 61 seconds in the past
    past_ts = time.time() - 61
    limiter._windows["ws-old"].append(past_ts)
    limiter._windows["ws-old"].append(past_ts)
    limiter._windows["ws-old"].append(past_ts)

    # All three old entries should be evicted, so this call should succeed
    limiter.check_rpm("ws-old", limit=1)  # no exception


def test_rate_limit_error_message():
    err = RateLimitError("ws-x", 5)
    assert "5" in str(err)
    assert "requests/minute" in str(err)


# ---------------------------------------------------------------------------
# UsageLogger — budget checks
# ---------------------------------------------------------------------------

async def test_budget_check_passes_when_no_max(mock_workspace):
    mock_workspace.max_budget_usd = None
    mock_workspace.spend_current = 999.0
    logger = UsageLogger()
    await logger.check_budget(mock_workspace)  # no exception


async def test_budget_check_passes_when_under_limit(mock_workspace):
    mock_workspace.max_budget_usd = 5.0
    mock_workspace.spend_current = 1.0
    logger = UsageLogger()
    await logger.check_budget(mock_workspace)  # no exception


async def test_budget_check_fails_when_exceeded(mock_workspace):
    mock_workspace.max_budget_usd = 1.0
    mock_workspace.spend_current = 1.5
    logger = UsageLogger()
    with pytest.raises(BudgetExceededError) as exc_info:
        await logger.check_budget(mock_workspace)
    assert "budget" in str(exc_info.value).lower()
    assert exc_info.value.workspace_id == mock_workspace.id


async def test_budget_check_fails_at_exact_limit(mock_workspace):
    """spend_current == max_budget_usd triggers hard limit (>=)."""
    mock_workspace.max_budget_usd = 2.0
    mock_workspace.spend_current = 2.0
    logger = UsageLogger()
    with pytest.raises(BudgetExceededError):
        await logger.check_budget(mock_workspace)


async def test_budget_check_soft_limit_does_not_raise(mock_workspace):
    """Soft limit only logs a warning — no exception raised."""
    mock_workspace.max_budget_usd = 10.0
    mock_workspace.soft_budget_usd = 5.0
    mock_workspace.spend_current = 6.0  # above soft, below hard
    logger = UsageLogger()
    await logger.check_budget(mock_workspace)  # no exception


# ---------------------------------------------------------------------------
# UsageLogger — log_usage
# ---------------------------------------------------------------------------

async def test_log_usage_calls_backend(mock_backend):
    logger = UsageLogger()
    await logger.log_usage(
        mock_backend, "ws-1", "sess-1", "gpt-4o", 10, 5, 15, 0.001
    )
    mock_backend.log_usage.assert_called_once_with(
        "ws-1", "sess-1", "gpt-4o", 10, 5, 15, 0.001
    )


async def test_log_usage_swallows_backend_error(mock_backend):
    """Backend failure must not propagate — fire-and-forget semantics."""
    mock_backend.log_usage.side_effect = Exception("DB down")
    logger = UsageLogger()
    await logger.log_usage(mock_backend, "ws-1", None, "gpt-4o", 0, 0, 0, 0.0)
    # No exception raised


async def test_log_usage_none_session_id(mock_backend):
    logger = UsageLogger()
    await logger.log_usage(mock_backend, "ws-1", None, "gpt-4o", 10, 5, 15, 0.002)
    mock_backend.log_usage.assert_called_once()
    args = mock_backend.log_usage.call_args[0]
    assert args[1] is None  # session_id


# ---------------------------------------------------------------------------
# BudgetExceededError attributes
# ---------------------------------------------------------------------------

def test_budget_exceeded_error_attributes():
    err = BudgetExceededError("ws-abc", 5.0, 7.5)
    assert err.workspace_id == "ws-abc"
    assert err.limit == 5.0
    assert err.current_spend == 7.5
    assert "5.00" in str(err)
    assert "7.5" in str(err)
