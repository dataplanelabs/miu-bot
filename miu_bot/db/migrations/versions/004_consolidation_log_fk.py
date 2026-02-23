"""Add FK constraint on consolidation_log.workspace_id.

Revision ID: 004
Create Date: 2026-02-23
"""

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Clean up orphan rows before adding FK (safety net)
    op.execute("""
        DELETE FROM consolidation_log
        WHERE workspace_id NOT IN (SELECT id FROM workspaces)
    """)
    op.execute("""
        ALTER TABLE consolidation_log
            ADD CONSTRAINT fk_consolidation_log_workspace
            FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE consolidation_log
            DROP CONSTRAINT IF EXISTS fk_consolidation_log_workspace
    """)
