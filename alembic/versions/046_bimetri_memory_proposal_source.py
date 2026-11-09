# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch: memory proposals from agents (memory MCP) next to merge proposals.

Adds ``source`` ('merge' | 'agent') and ``run_id``; ``pr_number`` becomes optional because an
agent may propose before its PR exists.
"""

from alembic import op

revision = "b046_memory_proposal_source"
down_revision = "b045_memory_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE bimetri_memory_proposals "
        "ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'merge'"
    )
    op.execute("ALTER TABLE bimetri_memory_proposals ADD COLUMN IF NOT EXISTS run_id INTEGER")
    op.execute("ALTER TABLE bimetri_memory_proposals ALTER COLUMN pr_number DROP NOT NULL")


def downgrade() -> None:
    op.execute("DELETE FROM bimetri_memory_proposals WHERE pr_number IS NULL")
    op.execute("ALTER TABLE bimetri_memory_proposals ALTER COLUMN pr_number SET NOT NULL")
    op.execute("ALTER TABLE bimetri_memory_proposals DROP COLUMN IF EXISTS run_id")
    op.execute("ALTER TABLE bimetri_memory_proposals DROP COLUMN IF EXISTS source")
