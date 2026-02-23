"""Workspace templates and skills tables.

Revision ID: 003
Create Date: 2026-02-23
"""

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Workspace templates (soul, user, agents, heartbeat)
    op.execute("""
        CREATE TABLE workspace_templates (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            template_type TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            config JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(workspace_id, template_type)
        )
    """)
    op.execute("""
        CREATE INDEX idx_workspace_templates_ws
        ON workspace_templates (workspace_id)
    """)

    # Workspace skills (structured per-skill rows)
    op.execute("""
        CREATE TABLE workspace_skills (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            identity TEXT NOT NULL DEFAULT '',
            rules JSONB NOT NULL DEFAULT '[]',
            mcp_servers JSONB NOT NULL DEFAULT '{}',
            tags JSONB NOT NULL DEFAULT '[]',
            source TEXT NOT NULL DEFAULT 'inline',
            source_version TEXT NOT NULL DEFAULT '',
            enabled BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(workspace_id, name)
        )
    """)
    op.execute("""
        CREATE INDEX idx_workspace_skills_ws
        ON workspace_skills (workspace_id, enabled)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workspace_skills")
    op.execute("DROP TABLE IF EXISTS workspace_templates")
