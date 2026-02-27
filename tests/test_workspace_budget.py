"""Unit tests for Workspace budget fields and UsageLog dataclass (MIU-26)."""
from datetime import datetime, timezone

import pytest

from miu_bot.db.backend import UsageLog, Workspace


# ---------------------------------------------------------------------------
# Workspace budget field defaults
# ---------------------------------------------------------------------------

def _make_workspace(**overrides) -> Workspace:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id="ws-1",
        name="test",
        identity="You are a bot.",
        config_overrides={},
        status="active",
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return Workspace(**defaults)


def test_workspace_budget_defaults():
    ws = _make_workspace()
    assert ws.max_budget_usd is None
    assert ws.soft_budget_usd is None
    assert ws.spend_current == 0.0
    assert ws.budget_duration == "30d"
    assert ws.budget_reset_at is None


def test_workspace_budget_configured():
    ws = _make_workspace(max_budget_usd=10.0, soft_budget_usd=8.0, spend_current=3.5)
    assert ws.max_budget_usd == 10.0
    assert ws.soft_budget_usd == 8.0
    assert ws.spend_current == pytest.approx(3.5)


def test_workspace_spend_current_zero_by_default():
    ws = _make_workspace()
    assert ws.spend_current == 0.0


def test_workspace_budget_duration_default():
    ws = _make_workspace()
    assert ws.budget_duration == "30d"


def test_workspace_budget_reset_at_none_by_default():
    ws = _make_workspace()
    assert ws.budget_reset_at is None


def test_workspace_budget_reset_at_set():
    now = datetime.now(timezone.utc)
    ws = _make_workspace(budget_reset_at=now)
    assert ws.budget_reset_at == now


def test_workspace_status_field():
    ws = _make_workspace(status="paused")
    assert ws.status == "paused"


def test_workspace_config_overrides_empty_default():
    ws = _make_workspace()
    assert ws.config_overrides == {}


def test_workspace_max_budget_zero_is_not_none():
    """max_budget_usd=0.0 is distinct from None (means $0 budget, always exceeded)."""
    ws = _make_workspace(max_budget_usd=0.0)
    assert ws.max_budget_usd is not None
    assert ws.max_budget_usd == 0.0


# ---------------------------------------------------------------------------
# UsageLog dataclass
# ---------------------------------------------------------------------------

def _make_usage_log(**overrides) -> UsageLog:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id="log-1",
        workspace_id="ws-1",
        session_id="sess-1",
        model="gpt-4o",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.002,
        created_at=now,
    )
    defaults.update(overrides)
    return UsageLog(**defaults)


def test_usage_log_basic_fields():
    log = _make_usage_log()
    assert log.workspace_id == "ws-1"
    assert log.model == "gpt-4o"
    assert log.prompt_tokens == 100
    assert log.completion_tokens == 50
    assert log.total_tokens == 150
    assert log.cost_usd == pytest.approx(0.002)


def test_usage_log_session_id_can_be_none():
    log = _make_usage_log(session_id=None)
    assert log.session_id is None


def test_usage_log_cost_usd_zero():
    log = _make_usage_log(cost_usd=0.0)
    assert log.cost_usd == 0.0


def test_usage_log_tokens_sum():
    log = _make_usage_log(prompt_tokens=200, completion_tokens=100, total_tokens=300)
    assert log.prompt_tokens + log.completion_tokens == log.total_tokens


def test_usage_log_created_at_is_datetime():
    log = _make_usage_log()
    assert isinstance(log.created_at, datetime)


def test_usage_log_id_field():
    log = _make_usage_log(id="unique-log-id")
    assert log.id == "unique-log-id"
