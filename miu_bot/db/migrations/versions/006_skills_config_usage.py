"""Add skill config columns (MIU-1) and usage/budget tracking (MIU-26).

Revision ID: 006
Create Date: 2026-02-27
"""

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # MIU-1: Add config, handler_type, config_schema to workspace_skills
    op.execute("""
        ALTER TABLE workspace_skills
            ADD COLUMN IF NOT EXISTS config        jsonb NOT NULL DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS handler_type  text  NOT NULL DEFAULT 'prompt',
            ADD COLUMN IF NOT EXISTS config_schema jsonb NOT NULL DEFAULT '{}'
    """)

    # MIU-26: Immutable usage audit log per LLM call
    op.execute("""
        CREATE TABLE IF NOT EXISTS usage_logs (
            id                  uuid PRIMARY KEY DEFAULT uuidv7(),
            workspace_id        uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            session_id          uuid REFERENCES sessions(id) ON DELETE SET NULL,
            model               text NOT NULL DEFAULT '',
            prompt_tokens       integer NOT NULL DEFAULT 0,
            completion_tokens   integer NOT NULL DEFAULT 0,
            total_tokens        integer NOT NULL DEFAULT 0,
            cost_usd            numeric(12, 8) NOT NULL DEFAULT 0,
            created_at          timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_logs_workspace_created "
        "ON usage_logs(workspace_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_logs_session "
        "ON usage_logs(session_id)"
    )

    # MIU-26: Budget tracking columns on workspaces
    op.execute("""
        ALTER TABLE workspaces
            ADD COLUMN IF NOT EXISTS max_budget_usd  numeric(12, 4),
            ADD COLUMN IF NOT EXISTS soft_budget_usd numeric(12, 4),
            ADD COLUMN IF NOT EXISTS budget_duration text NOT NULL DEFAULT '30d',
            ADD COLUMN IF NOT EXISTS budget_reset_at timestamptz,
            ADD COLUMN IF NOT EXISTS spend_current   numeric(12, 4) NOT NULL DEFAULT 0
    """)


def downgrade() -> None:
    # MIU-26: Remove budget columns and usage_logs
    op.execute("""
        ALTER TABLE workspaces
            DROP COLUMN IF EXISTS max_budget_usd,
            DROP COLUMN IF EXISTS soft_budget_usd,
            DROP COLUMN IF EXISTS budget_duration,
            DROP COLUMN IF EXISTS budget_reset_at,
            DROP COLUMN IF EXISTS spend_current
    """)
    op.execute("DROP TABLE IF EXISTS usage_logs CASCADE")

    # MIU-1: Remove skill config columns
    op.execute("""
        ALTER TABLE workspace_skills
            DROP COLUMN IF EXISTS config,
            DROP COLUMN IF EXISTS handler_type,
            DROP COLUMN IF EXISTS config_schema
    """)
