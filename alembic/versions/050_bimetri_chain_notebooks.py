# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency item 7): chain notebook of each PR."""

from alembic import op

revision = "b050_chain_notebooks"
down_revision = "b049_agent_quota_credits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS bimetri_chain_notebooks (
            id SERIAL PRIMARY KEY,
            project_id TEXT NOT NULL,
            pr_number INTEGER NOT NULL,
            entries JSONB NOT NULL DEFAULT '[]',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (project_id, pr_number)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bimetri_chain_notebooks")
