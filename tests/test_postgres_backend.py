"""Integration tests for PostgresBackend — requires TEST_DATABASE_URL env var.

All tests are auto-skipped when TEST_DATABASE_URL is not set.
Run with: TEST_DATABASE_URL=postgresql://... pytest tests/test_postgres_backend.py -v
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — skipping integration tests",
)


@pytest.fixture
async def pg_backend():
    import asyncpg
    from miu_bot.db.postgres import PostgresBackend

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    backend = PostgresBackend(pool)
    yield backend
    await pool.close()


async def test_create_and_get_workspace(pg_backend):
    ws = await pg_backend.create_workspace("test-ws-coverage", "You are a bot.")
    try:
        fetched = await pg_backend.get_workspace(ws.id)
        assert fetched.name == "test-ws-coverage"
        # MIU-26: budget fields default to None / 0
        assert fetched.max_budget_usd is None
        assert fetched.spend_current == 0.0
    finally:
        await pg_backend.delete_workspace(ws.id)


async def test_upsert_skill_persists_miu1_columns(pg_backend):
    """MIU-1: config, handler_type, config_schema are stored and retrieved."""
    from datetime import datetime, timezone
    from miu_bot.db.backend import WorkspaceSkill

    ws = await pg_backend.create_workspace("skill-col-test", "identity")
    try:
        now = datetime.now(timezone.utc)
        skill = WorkspaceSkill(
            id="", workspace_id=ws.id,
            name="coding", description="code help", identity="",
            rules=[], mcp_servers={}, tags=[], source="inline",
            source_version="", enabled=True,
            created_at=now, updated_at=now,
            config={"max_lines": 100},
            handler_type="function",
            config_schema={"type": "object"},
        )
        result = await pg_backend.upsert_skill(ws.id, skill)
        assert result.config == {"max_lines": 100}
        assert result.handler_type == "function"
        assert result.config_schema == {"type": "object"}

        # Flat table — retrieve and verify
        fetched = await pg_backend.get_skills(ws.id)
        assert len(fetched) == 1
        assert fetched[0].name == "coding"
        assert fetched[0].handler_type == "function"
    finally:
        await pg_backend.delete_workspace(ws.id)


async def test_log_usage_inserts_row_and_increments_spend(pg_backend):
    """MIU-26: usage_logs insert + workspaces.spend_current increment."""
    ws = await pg_backend.create_workspace("usage-test", "")
    try:
        await pg_backend.log_usage(
            workspace_id=ws.id, session_id=None, model="gpt-4o",
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
            cost_usd=0.002,
        )
        summary = await pg_backend.get_usage_summary(ws.id, days=1)
        assert summary["request_count"] == 1
        assert int(summary["total_tokens"]) == 150

        updated_ws = await pg_backend.get_workspace(ws.id)
        assert float(updated_ws.spend_current) == pytest.approx(0.002, abs=1e-6)
    finally:
        await pg_backend.delete_workspace(ws.id)


async def test_log_usage_is_immutable_append(pg_backend):
    """MIU-26: usage_logs rows are append-only — each call adds a new row."""
    ws = await pg_backend.create_workspace("usage-immutable", "")
    try:
        for _ in range(3):
            await pg_backend.log_usage(
                ws.id, None, "gpt-4o", 10, 5, 15, 0.001
            )
        summary = await pg_backend.get_usage_summary(ws.id, days=1)
        assert summary["request_count"] == 3
    finally:
        await pg_backend.delete_workspace(ws.id)
